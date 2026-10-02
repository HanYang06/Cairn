# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""存储引擎：管 block 的状态与存储，把文件读写整条路替上层做掉。

**两个引擎，分工不重叠**：

- 本文件是**存储引擎**：面向载体（slot / pack / hub），负责"分配 hub、分配 pack、分配 slot"，
  把内存里的值写成字节、把字节读回来**组织成 block 对象**交还。它不认识数据库；
- `core.storage.db.engine` 是**数据库引擎**：面向索引库，只回答"这个身份在哪儿"。
  它是本引擎的**子引擎**：写入时登记定位，读取时按身份问路。

**能力靠继承拿到，身份靠调用方给。** `Block` 是那个"隐形关联"的接口面：

    self.id = ID(self)      # 身份由调用方签发——内核不代签
    ...                     # 随便怎么玩：字段、派生值、临时状态
    note = Note(self.id)    # 递给基座，能力在那一刻成立
    note.title = "标题"
    note.save()             # 引擎接手：分配、编码、落盘、回填摘要与位置

**没有 ID 就没有一切**：不递 ID 的对象不入库、不建表、不产生任何关系。

**块的落点由值决定**（`types.py` 三个判据）：

- `Body(...)` → 内容记录（按内容地址去重）；
- `Attr(...)` → 块记录载荷里的属性，**并且进反表**（用了它即进，没有开关）；
- **裸赋值** → 照样进块记录载荷，只是没有索引加持；
- `ID` 实例 → 身份，不重复落进载荷。

**策略参数向配置面要值**（`storage/conf.py`）：默认 hub、格长、封口线、索引块上限四样都在
那里声明；构造时不给就用当前配置值。故"改配置"改的是这些数，而**改不动已落盘的字节**。

**写路径发事件**（`core/event`）：落盘之后发 `object.put`、摘掉之后发 `object.deleted`。
总线是可选的：不给就没人在听，写照样成立——通知不该成为写成功的前提。

**一个块落成两条记录**：内容记录（载荷即正文，身份按内容签发，同内容只存一份）与块记录
（载荷是指向内容的指针加块自己的属性，身份是块自己的）。两条记录各自提交，不是一次事务。

**位置段是投影**：引擎写完后把坐标回填到调用方递进来的那个 ID 上。别拿 `id.in_hub` 一类
派生持久字段——压实、搬移之后它就会变，而派生值已经冻进载荷里了。
"""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Self, cast

from core.event.catalog import OBJECT_DELETED, OBJECT_PUT
from core.event.events import Event
from core.exc import (
    HubNotFoundError,
    IndexNotFoundError,
    IndexSchemaError,
    ObjectNotFoundError,
    RecordFormatError,
    SlotError,
)

from . import conf as storage_conf
from .db.engine import Index
from .db.id import ID, digest
from .db.payload import (
    ContentRef,
    decode_block,
    decode_content,
    decode_index,
    decode_tombstone,
    encode_block,
    encode_content,
    encode_index,
    encode_tombstone,
)
from .hub import Hub, find_hubs
from .slot import SlotRange
from .types import BODY_KIND, kind_of, kinds_of, unwrap

if TYPE_CHECKING:
    from collections.abc import Iterator

    from core.event.bus import Bus

    from .index.index import IndexEngine
    from .pack import Record

CATALOG_FILENAME = "catalog.db"
"""索引库文件名：**路径约定只在这里出现一次**。"""

BODY_NAME = "body"
"""内容记录的身份名：它是内容，不是块，故名字与任何块表都不同。"""

TOMBSTONE_NAME = "tombstone"
"""墓碑记录的身份名：它是内核的机制记录，不占任何类型的配额。"""

SOURCE = "core.storage"
"""事件里的发出者标识：写路径发的事件都署它。"""


BODY_FIELDS_KEY = "\x00cairn.body_fields"
"""块记录载荷里的保留键：**哪些字段的内容在内容记录里**（按写入次序）。

它只记名字、不记值——值在内容记录里。少了它，回读时不知道该往哪几个字段填值；
把值也抄一份，去重就白做了。
"""


class Engine:
    """存储引擎：分配 hub / pack / slot，把块落成两条记录，再按身份读回来。

    Args:
        root: 库根（vault 目录）。
        default_hub: 不点名时写进哪个 hub；不给即取配置面的 `hub.default`。
        slot_bytes: **新建**载体时的格长；不给即取配置面的五档之和。
            读已有载体一律看它自己的文件头，与这个数无关。
        max_bytes: 封口线；不给即取配置面的 `pack.max.byte`。它只管"什么时候换文件"，
            不构成单条记录的硬上限。
        bus: 事件总线；不给即不发事件（写路径不依赖有没有人在听）。
    """

    def __init__(
        self,
        root: str | Path,
        *,
        default_hub: str | None = None,
        slot_bytes: int | None = None,
        max_bytes: int | None = None,
        bus: Bus | None = None,
    ) -> None:
        """接上库根与索引库。**它不建库根**：建立是显式动作（`Kernel.create`）。

        索引库是**惰性开的**：第一次要用它时才建文件。故"只想读载体"的场合
        （只读工具、巡检）不会因为装配一个引擎就凭空多出一个库文件。

        **策略值在这里定下**：构造一次读一次配置面，此后这一次装配里的每个 hub 与载体
        都按同一组数判。故"这一次写入用的是哪条封口线"答得出来，不必回头猜。
        """
        self._root = Path(root)
        self._default_hub = default_hub or storage_conf.default_hub_name()
        self._slot_bytes = storage_conf.slot_bytes() if slot_bytes is None else slot_bytes
        self._max_bytes = storage_conf.pack_max_bytes() if max_bytes is None else max_bytes
        self._bus = bus
        self._index: Index | None = None
        self._indexes: IndexEngine | None = None

    @property
    def root(self) -> Path:
        """库根目录。"""
        return self._root

    @property
    def catalog_path(self) -> Path:
        """索引库文件路径：**路径约定只在这里出现一次**。"""
        return self._root / CATALOG_FILENAME

    @property
    def index(self) -> Index:
        """索引库：需要时开，并把已知类型的身份表补齐。"""
        if self._index is None:
            self._index = Index.create(self.catalog_path)
            self._sync_tables(self._index)
        return self._index

    def _sync_tables(self, index: Index) -> None:
        """把**已知的块类型**各自的身份表补齐：用 ID 就有表，一个不落。

        索引块（`AttrIndex` / `BodyIndex`）也在这份清单里——**它们也是块**，
        有自己的表，与任何块同路。
        """
        for table in (*known_tables(), *_index_tables()):
            index.ensure_table(table)

    def close(self) -> None:
        """关掉引擎手里的资源（索引库连接）。**幂等**：没开过或已关都不出错。"""
        index = self._index
        if index is not None:
            index.close()
            self._index = None

    def __enter__(self) -> Self:
        """进入 `with`：引擎可用。"""
        return self

    def __exit__(self, *_: object) -> None:
        """退出 `with`：关掉资源，无论是否异常。"""
        self.close()

    @property
    def default_hub(self) -> str:
        """默认 hub 名。"""
        return self._default_hub

    @property
    def slot_bytes(self) -> int:
        """这次装配用的格长：**只决定新建载体写进文件头的那个数**，读已有载体不看它。"""
        return self._slot_bytes

    @property
    def max_bytes(self) -> int:
        """这次装配用的封口线（字节）：只管"什么时候换文件"。"""
        return self._max_bytes

    @property
    def bus(self) -> Bus | None:
        """写路径发事件的那条总线；没有即 `None`（不发）。"""
        return self._bus

    def _notify(self, event_type: str, identity: ID, data: object = None) -> None:
        """发一条通知：**只在有人听的时候才说话**，且失败绝不回流写路径。

        `Bus.emit` 自己已隔离订阅者的异常；这里再兜住"总线本身也出岔子"那种情形——
        写成功就是写成功，通知是旁路。
        """
        if self._bus is None:
            return
        event = Event(type=event_type, source=SOURCE, subject=identity.value_uuid, data=data)
        with suppress(Exception):
            self._bus.emit(event)

    # ---- 写入 ---- #

    def save(self, block: Block, *, hub: str | None = None) -> ID:
        """把一个块落成两条记录，返回块身份（就是调用方递进来那一个，已回填）。

        Raises:
            TypeError: 这个对象没有身份（没递 ID）。
            AttrTypeError: 属性或内容编不进载荷。
        """
        identity = block.id
        fields = _fields_of(block)
        target = self._hub_name(hub)
        target_hub = self._open_hub(target)

        content = encode_content(_content_of(block, fields))
        content_id = ID.of(content, name=BODY_NAME)
        self._write_content(target_hub, content_id, content)

        payload = encode_block(
            _attrs_of(block, fields),
            ContentRef(value_uuid=content_id.value_uuid, value_hash=content_id.value_hash),
        )
        record = target_hub.append(identity, payload)
        # **改绑**：同一个块改了字段再存一次，块身份随载荷而变，故引擎要能重写这一项。
        identity.bind(payload, rebind=True)
        _place(identity, target, record.owner, record.span)
        self._register(block, identity)
        self._index_block(block)
        self._notify(
            OBJECT_PUT,
            identity,
            {"table": block.type_name, "content": content_id.value_hash},
        )
        return identity

    def _index_block(self, block: Block) -> None:
        """把这个块的**正表行**写进各类索引：**声明了 `Attr` / `Body` 就必然进来**。

        哪些字段进哪一类索引，是索引块那边声明的（:meth:`IndexBlock.holds`）；
        引擎只管把行写下去、满了续块。故这里没有一行"哪个字段该不该索引"的判断。
        """
        self.index_engine.record(block)

    def _register(self, block: Block, identity: ID) -> None:
        """把这个身份写进它那张表：**用了 ID 就有表，有了表就有一行**。

        库里的行是 ID 的镜像：列全部照 `ID_FIELDS` 搬，位置段由引擎刚回填的值给出。
        """
        table = block.type_name
        index = self.index
        index.ensure_table(table)
        index.register_hub(identity.in_hub)
        index.put(
            table,
            identity.to_record()
            | {
                "in_hub": identity.in_hub,
                "in_hub_pack": identity.in_hub_pack,
                "in_pack_slot": identity.in_pack_slot,
            },
        )

    # ---- 索引：**由正表现算反表**，索引块只声明参数 ---- #

    @property
    def index_engine(self) -> IndexEngine:
        """索引引擎：把正表行写进索引块、把反表翻出来。"""
        if self._indexes is None:
            from .index.index import IndexEngine  # noqa: PLC0415 — 打断环形引用

            self._indexes = IndexEngine(self)
        return self._indexes

    def write_index_row(self, owner: type[Block], value_uuid: str, row: dict[str, object]) -> None:
        """把一个块的**正表行**写进 `owner` 这类索引；**满了自动开下一块**。

        **身份由索引块自己签发**：这个索引还没有块时，引擎造一个空的（`owner()`）——
        那一下走的就是块的标准用法（`self.id = ID(self)` + `super().__init__(self.id)`），
        故"有 ID 才有表、才进库"这条在索引上照样成立，不是魔法。

        一条行一条记录，故写路径只有追加、没有改动——不会出"改漏一处"的事故。

        Args:
            owner: 索引块的类型（`AttrIndex` / `BodyIndex`）。
            value_uuid: 这一行属于哪个块。
            row: 字段名 → 值（一个字段一条记录）。
        """
        owner_name = owner.__name__.lower()
        limit = max(1, int(owner.max_bytes) or storage_conf.index_max_bytes())
        live = self._active_index(owner_name, limit)
        for field, value in row.items():
            if live is None:
                live = owner().id  # **索引块自己签发身份**（那两行就在它的 __init__ 里）
                self._register_index(owner_name, live)
            hub = self._open_hub(live.in_hub or self._default_hub)
            record = hub.append(
                live, encode_index(owner_name, field, value, [value_uuid], [str(value)])
            )
            _place(live, hub.name, record.owner, record.span)
            self._register_index(owner_name, live)

    def read_index_rows(self, owner: type[Any]) -> Iterator[dict[str, object]]:
        """读出一类索引的**全部正表行**：行 = `{"value_uuid", "field", "value", "text"}`。

        **多块合并**：同一类索引可以有好几块（上个满了就开了下一个），并起来才是完整的正表。
        同一个块同一字段若被写过多次，**最后写的那一条说了算**（块身份随载荷，改了字段就换了值）。
        """
        owner_name = owner.__name__.lower()
        latest: dict[tuple[str, str], dict[str, object]] = {}
        for record in self.index_records(owner_name):
            parsed = decode_index(record.payload)
            if parsed is None:  # pragma: no cover — index_records 已经筛过
                continue
            _owner, field, text, blocks, _values = parsed
            for target in blocks:
                latest[(field, target)] = {
                    "value_uuid": target,
                    "field": field,
                    "value": text,
                    "text": text.partition(":")[2],
                }
        yield from latest.values()

    def index_records(self, owner_name: str) -> Iterator[Record]:
        """顺扫出某一类索引的全部记录（多块合并的取数口）。"""
        for record in self._records():
            parsed = decode_index(record.payload)
            if parsed is not None and parsed[0] == owner_name:
                yield record

    def block_records(self) -> Iterator[Record]:
        """顺扫出**块记录**：索引行与墓碑都不算。

        块记录 = 带保留键（指向内容的两套凭证）的那些；索引行与墓碑各有自己的保留键。
        数"盘上有几个块"该用它，而不是 `scan()`——后者把索引行也数进去了。
        """
        for record in self._records():
            if decode_block(record.payload) is not None:
                yield record

    def _active_index(self, owner_name: str, limit: int) -> ID | None:
        """挑一个**还有地方**的索引块：最后一条载荷没到上限就用它，否则返回 `None`（开新的）。"""
        latest: Record | None = None
        for record in self.index_records(owner_name):
            latest = record
        if latest is None or len(latest.payload) >= limit:
            return None
        return ID(
            owner_name,
            value_uuid=latest.identity.value_uuid,
            birth_time=latest.identity.birth_time,
        )

    def _register_index(self, owner_name: str, identity: ID) -> None:
        """把索引块自己也登记进库：**它也是块，用了 ID 就有表**。

        这一步不是可选的：索引一多就"不知道它搁哪儿了"，故它必须进身份表。
        """
        index = self.index
        index.ensure_table(owner_name)
        index.register_hub(identity.in_hub)
        index.put(
            owner_name,
            identity.to_record()
            | {
                "in_hub": identity.in_hub,
                "in_hub_pack": identity.in_hub_pack,
                "in_pack_slot": identity.in_pack_slot,
            },
        )

    def _write_content(self, hub: Hub, identity: ID, payload: bytes) -> SlotRange:
        """写一条内容记录：**同内容只存一份**——已经在盘上就不重复写。

        去重判据是内容摘要（分配形态与内容无关，故不能拿它判重）。内容记录的身份名是
        `body`：它是内容，不是块。
        """
        found = self._find_content(identity.value_hash)
        if found is not None:
            return found
        return hub.append(identity, payload).span

    def _find_content(self, content_hash: str) -> SlotRange | None:
        """顺扫找一条内容记录，返回它的格区间；没有即 ``None``。

        判据有两条：载荷摘要相等（那就是同一份内容），且它**不是块记录**（不带保留键）。
        """
        for record in self._records():
            if decode_block(record.payload) is not None:
                continue
            if digest(record.payload) == content_hash:
                return record.span
        return None

    def _hub_name(self, explicit: str | None) -> str:
        """这一次写进哪个 hub。"""
        return explicit or self._default_hub

    def _open_hub(self, name: str) -> Hub:
        """取一个可写的 hub；不在即建（建立 hub 是写路径的正当动作）。

        格长与封口线在这一处交给 hub：**写路径上只有这里定"这一份载体怎么建"**，
        故"这次写入用的是哪组策略"不必回头猜。
        """
        return Hub.create(self._root / name, slot_bytes=self._slot_bytes, max_bytes=self._max_bytes)

    def _write_hub(self, name: str) -> Hub:
        """取一个**已存在**的 hub 用于追加（墓碑走这条）：同一组策略，但绝不新建。"""
        return Hub.open(self._root / name, slot_bytes=self._slot_bytes, max_bytes=self._max_bytes)

    # ---- 读取 ---- #

    def _records(self) -> Iterator[Record]:
        """顺扫全库的记录：**这是不依赖索引的取数口**。

        记录自框定、身份随记录走，故一遍扫完即得"谁在哪、装了什么"。
        数据库引擎与 GC 走的都是这一条路。
        """
        for hub in find_hubs(self._root):
            for pack in hub.packs():
                yield from pack.scan()

    def scan(self) -> Iterator[Record]:
        """顺扫全库，交出记录（公开面）。"""
        yield from self._records()

    def find_block(self, identity: ID) -> tuple[str, str, SlotRange, bytes] | None:
        """按身份找**块记录**：返回（hub 名，载体名，格区间，载荷）；找不到即 ``None``。

        **先问索引库**：身份表里有这一行，就照它记的坐标直接去读那一格——这正是
        索引库存在的理由（省掉一遍顺扫）。库里没有（或还没有库）才回退到顺扫。

        顺扫那一趟的判据落在三处：记录里的身份 = 递进来的那个、载荷带保留键
        （它是块记录而不是内容）、且**没有被墓碑标记过**。

        **取最后那一条，再判它死活**：同一个身份在盘上可能有好几条（每存一次追加一条），
        "最后写的"才是它现在的样子。判据落在**那一条自己的**摘要上——若改成"往回找第一条
        没被标记的"，删掉一次之后旧副本就会**复活**，而且不报错。
        """
        found = self._find_via_index(identity)
        if found is not None:
            return found
        marked = self.tombstones()
        latest: tuple[str, str, SlotRange, bytes] | None = None
        for hub in find_hubs(self._root):
            for pack in hub.packs():
                for record in pack.scan():
                    if record.identity.value_uuid != identity.value_uuid:
                        continue
                    if decode_block(record.payload) is None:
                        continue
                    latest = (hub.name, pack.name, record.span, record.payload)
        if latest is None or digest(latest[3]) in marked:
            return None
        return latest

    def _find_via_index(self, identity: ID) -> tuple[str, str, SlotRange, bytes] | None:
        """照索引库那一行记的坐标去读那一格；查不到、读不出来、或**读到的不是它**即 ``None``。

        **名字为空即查不了表**：身份的名字就是表名，没有名字就没有那一行可问。
        这条路直接回退顺扫——拿空名字去问 sqlite 会报"没有这张表"，而"这个身份没有类型"
        不是错误（按分配形态读回一个块正是它的用法）。

        **读完要核对身份**：库里那一行是投影，坐标会随载体重写（GC、压实、人手改动）失效。
        不核对就可能把"那一格现在住着别的记录"当成"就是这个块"，而且**不报错**。
        记录头里本来就带着身份，故核对这一步不要额外的 IO。
        """
        if not identity.name or not self.catalog_path.is_file():
            return None
        try:
            row = self.index.get(_table_of(identity), identity.value_uuid)
        except (IndexNotFoundError, IndexSchemaError):
            return None
        # 位置段不全即"这一行还没落过盘"：那样也算没这一行，回退顺扫。
        placed = None if row is None else _located(row)
        if placed is None:
            return None
        hub_name, pack_name, span = placed
        try:
            record = Hub.open(self._root / hub_name).pack(pack_name).read(span)
        except (HubNotFoundError, RecordFormatError, SlotError):
            return None
        if record.identity.value_uuid != identity.value_uuid:
            return None
        return hub_name, pack_name, span, record.payload

    def load(self, identity: ID, owner: type[Block] | None = None) -> Block:
        """按身份读回一个块：**读字节、解码、组织成对象交还**。

        Args:
            identity: 要读的那个身份。
            owner: **以哪个类为准**（`NoteData.fetch()` 就是 `NoteData`）。给了它就用它，
                不再按表名去猜——名字相同的类型满仓都是，猜会挑错那一个。

        Raises:
            ObjectNotFoundError: 盘上没有这个身份。
        """
        found = self.find_block(identity)
        if found is None:
            raise ObjectNotFoundError(f"对象不在: {identity.value_uuid}")
        hub_name, pack_name, span, payload = found
        parsed = decode_block(payload)
        if parsed is None:  # pragma: no cover — find_block 已经保证了它解得开
            raise ObjectNotFoundError(f"这一条不是块记录: {identity.value_uuid}")
        ref, attrs = parsed

        block_id = ID(identity.name, value_uuid=identity.value_uuid, birth_time=identity.birth_time)
        block_id.bind(payload)
        _place(block_id, hub_name, pack_name, span)
        block = _new_block(str(identity.name), block_id, owner=owner)
        content = self._read_content(ref.value_hash)
        index = 0
        for name, entry in attrs.items():
            if not isinstance(entry, dict) or "v" not in entry:
                setattr(block, name, entry)
                continue
            if entry.get("body"):
                # 内容字段：从内容记录里取值，值按声明写进实例（描述符收下裸值）。
                value = content[index] if index < len(content) else entry["v"]
                index += 1
                setattr(block, name, value)
                continue
            setattr(block, name, entry["v"])
        return block

    def _read_content(self, content_hash: str) -> list[object]:
        """按内容摘要读回内容记录里的值（给去重与反查用）。

        Raises:
            ObjectNotFoundError: 盘上没有这份内容（指针指向了不存在的字节）。
        """
        for record in self._records():
            if decode_block(record.payload) is not None:
                continue
            if digest(record.payload) != content_hash:
                continue
            decoded = decode_content(record.payload)
            return decoded if isinstance(decoded, list) else [decoded]
        raise ObjectNotFoundError(f"内容不在: {content_hash}")

    # ---- 删除 ---- #

    def delete(self, identity: ID) -> bool:
        """删掉一个块：返回是否确实删掉了一个。

        载体是追加写，旧字节删不掉，故删除要落两处：

        - **一条墓碑**（追加在载体末尾）：顺扫认得出"这一条不算数了"，空间由 GC 回收；
        - **摘掉索引行**：库里那一行是给"按身份问路"用的，留着它就会把已删的块又读回来。

        **墓碑必须落盘**：位置本来就是投影，只清内存里的位置等于没删。
        """
        found = self.find_block(identity)
        if found is None:
            return False
        hub_name, _pack, _span, payload = found
        tombstone = ID.unbound(name=TOMBSTONE_NAME)
        self._write_hub(hub_name).append(tombstone, encode_tombstone(digest(payload)))
        self._forget(identity)
        _clear_place(identity)
        self._notify(OBJECT_DELETED, identity)
        return True

    def _forget(self, identity: ID) -> None:
        """摘掉库里的身份行：**只摘不删载体上的字节**，那由 GC 回收。"""
        try:
            self.index.drop_row(_table_of(identity), identity.value_uuid)
        except (IndexNotFoundError, IndexSchemaError):
            return
        identity.in_hub = ""
        identity.in_hub_pack = ""
        identity.in_pack_slot = (0, 0)

    def tombstones(self) -> frozenset[str]:
        """顺扫全部墓碑：**被删掉的那些载荷摘要**。

        块身份随载荷，故墓碑认的是载荷摘要而不是分配形态——同一份载荷只会有一份
        块记录，记摘要即够。
        """
        marked: set[str] = set()
        for record in self._records():
            victim = decode_tombstone(record.payload)
            if victim is not None:
                marked.add(victim)
        return frozenset(marked)

    def __repr__(self) -> str:
        """诊断用：库根与默认 hub，不读盘。"""
        return f"Engine(root={self._root!s}, hub={self._default_hub!r})"


class Block:
    """存储单元的基座：**身份由调用方给，能力在那一刻成立**。

    没有 ID 就没有一切——拿不到 ID，内核完全不参与：不建表、不入库、不与数据库产生任何关系。
    故本类**只有一条构造路**：

        self.id = ID(self)          # 调用方签发身份
        note = Note(self.id)        # 递给基座
        note.title = "标题"          # 想怎么玩怎么玩
        note.save()                 # 引擎接手

    Attributes:
        id: 块自己的身份。**由调用方签发并递入**，本基座不代签。
    """

    max_bytes: ClassVar[int] = 0
    """这个块的**体积上限**（字节）；`0` 即用配置面的默认（`index.max.byte`）。

    它只管"什么时候该换下一个块"——引擎按它决定续块（索引块就靠这一条自动一块接一块，
    块自己不必写一行续块逻辑）。**它是配置性的参数，不是写死的格式常量**：
    故声明在这里的是"这个类型要比默认更宽还是更窄"，默认值本身在 `storage/conf.py`。
    """

    @classmethod
    def holds(cls, block: Block) -> dict[str, object]:
        """这个块在**某类索引**里正表的那一行：字段名 → 值。

        基座上默认**没有**（空映射）：普通块不进任何索引。索引块把它接上——
        `AttrIndex` 交出 `Attr(...)` 声明的字段，`BodyIndex` 交出内容地点。
        声明放在这一层，是因为"这个块能按什么被查"本来就是块自己的性质。
        """
        del block
        return {}

    def __init__(self, id: ID | None = None) -> None:
        """收下身份；**不给就现签一个**（`ID(self)`）。

        身份从哪来只有两条路，都写在这一处：

            self.id = ID(self)                   # 自己签
            super().__init__(self.id)            # 递给基座

        或把签好的递进来（`Note(self.id)`）。**零参构造是一个块**——这就是
        "索引块由引擎按需造出来"那条路：`AttrIndex()` 自己签身份，于是它自然进库、有表。
        """
        self.id = ID(self) if id is None else id
        if not isinstance(self.id, ID):
            raise TypeError(f"块必须拿到一个 ID，拿到的是 {type(self.id).__name__}")

    @property
    def type_name(self) -> str:
        """这个块的表名，**只由类的名字算出来**。

        `class NoteData` → `notedata`。没有第二个口子：表名不由声明给出，由类名算出——
        故这里也不提供任何 `__table__` 一类的覆盖。（身份的名字由 `ID(self)` 解析出来，
        与这里同一个来源。）
        """
        return type(self).__name__.lower()

    @classmethod
    def declared_kinds(cls) -> dict[str, str]:
        """这个类型声明了哪些落点：字段名 → `'body'` / `'attr'`。

        **从类体上读**：声明是描述符，活得比任何一次赋值更久，故不必在实例上再记一本账。
        是类方法而不是属性——属性会被同名的类体声明覆盖掉。
        """
        return kinds_of(cls)

    def save(self, *, hub: str | None = None) -> ID:
        """存进去：引擎分配 hub / pack / slot，回填摘要与位置，返回块身份。"""
        return engine().save(self, hub=hub)

    @classmethod
    def fetch(cls, identity: ID) -> Self:
        """按身份取回来：引擎读字节、组织成块对象交还。

        取回来的字段是**裸值**：声明 `Attr("标题")` 的字段，`block.title` 是 `"标题"`
        而不是声明对象——声明管的是落点，不管取值。

        返回类型跟着**调用它的那个类**走（`Note.fetch()` 就是 `Note`）；调用时若走的
        是基座（`Block.fetch()`），那是"这个身份没有对应的类，降级读回"那条路。
        """
        return cast("Self", engine().load(identity, owner=cls))

    @classmethod
    def find(cls, identity: ID) -> Self | None:
        """按身份找：没有即 ``None``（与 :meth:`fetch` 的分别只在要不要抛错）。"""
        current = current_engine()
        if current is None or current.find_block(identity) is None:
            return None
        return cast("Self", current.load(identity, owner=cls))

    def delete(self) -> bool:
        """摘掉这个块：返回是否确实摘掉了一个。"""
        return engine().delete(self.id)

    def __repr__(self) -> str:
        """诊断用：表名与身份。"""
        return f"{type(self).__name__}(id={self.id.value_uuid[:8]}…)"


# ---- 进程内那根线 ---- #

_BOUND: Engine | None = None
"""`Block` 的能力接到哪个库：**模块级的一根线**。

**为什么必须是模块级的**：引擎（哪个库根、哪个 hub）是**运行时**的事实，而类定义在 import
时就已经发生了。声明点能静态确定，落盘点不能——故"继承拿到能力"是类上拿到协议，
"能力接到哪个库"由装配时接一次线。

**一个进程一次**：已经绑了别的库就报错，不静默切库。多库并存是另一种设计（那时 `save()`
得知道往哪个库写），现在没有这个需求，就不假装有。
"""


def bind(instance: Engine | None) -> None:
    """把这根线接到一个引擎上；传 `None` 即解开（测试与批处理用）。

    Raises:
        RuntimeError: 想绑的引擎与已经绑着的那一个不是同一个。
    """
    global _BOUND  # noqa: PLW0603 — 这根线本来就是全局的唯一一处
    if instance is not None and _BOUND is not None and _BOUND is not instance:
        raise RuntimeError(
            f"一个进程只接一个引擎：已经绑着 {_BOUND.root}，不能再绑 {instance.root}"
            "（要换就先 bind(None)）"
        )
    _BOUND = instance


def current_engine() -> Engine | None:
    """当前接着的那个引擎；没接即 ``None``。"""
    return _BOUND


def engine() -> Engine:
    """取当前接着的那个引擎。

    Raises:
        RuntimeError: 还没接（没装配内核就 `save()` 了）。
    """
    if _BOUND is None:
        raise RuntimeError("还没有接上引擎：先装配内核（它会 bind），再 save/fetch")
    return _BOUND


# ---- 内部：字段分类、位置回填、类查找 ---- #


def _fields_of(block: Block) -> dict[str, object]:
    """把一个块的**用户字段**读出来：**以类体声明的为准，再并上实例上多出来的**。

    为什么不能只看 `vars()`：**没显式赋过值的声明字段不在 `vars()` 里**。
    `class Counted(Block): count: int = Attr(0)` 造出来只带默认值，此时 `vars()` 只有
    `id`——只看它，这个字段就既不落盘也不进索引，而且**不报错**（读回来像是"从没写过"）。
    故声明过的字段一律取出来（取值即触发描述符给出那份默认值）。

    顺序：先按类体声明的书写顺序，再补实例上多出来的（那些是裸赋值，照样落盘）。
    """
    declared = kinds_of(type(block))
    fields: dict[str, object] = {}
    for name in declared:
        fields[name] = getattr(block, name, None)
    store = getattr(block, "__dict__", None)
    if isinstance(store, dict):
        for name, value in store.items():
            if name != "id" and not name.startswith("_"):
                fields.setdefault(name, value)
    else:
        for cls in type(block).__mro__:
            for name in getattr(cls, "__slots__", ()):
                if name != "id" and not name.startswith("_"):
                    fields.setdefault(name, getattr(block, name, None))
    return fields


def _content_of(block: Block, fields: dict[str, object]) -> list[object]:
    """内容记录里装的东西：**落点为内容的那几个字段值**，按字段次序。

    内容的身份是**它的值**（字段名只是装载方式），故同值恒得同一个摘要：同一份正文
    挂在两个不同名字的字段上，也只存一份。
    """
    return [
        unwrap(value) for name, value in fields.items() if kind_of(type(block), name) == BODY_KIND
    ]


def content_digest(block: Block) -> str | None:
    """一个块的**内容地点**（摘要）；它没有内容字段时是 ``None``。

    **这是内容索引与内容记录共用的唯一口径**：索引那边按它反查，引擎这边按它写记录——
    两处若各算一份，按内容反查就永远查不到东西，而且**不报错**。
    """
    values = _content_of(block, _fields_of(block))
    if not values:
        return None
    return digest(encode_content(values))


def _attrs_of(block: Block, fields: dict[str, object]) -> dict[str, object]:
    """块记录的属性：除身份以外的全部字段，**每个字段一小段：值 + 它的落点**。

    每个字段装成一个两元映射 ``{"v": 值, "body": true}``（`body` 只在内容字段上出现）：

    - **值在这里**：块记录因此自足——顺读即得全部属性值；
    - **落点也在这里**：赋值一步就会覆盖 `Body(...)` 的声明，故落点必须与值一起存下来，
      否则回读时分不清哪些字段的内容在内容记录里。

    裸赋值与 `Attr(...)` 在这里同样是属性（`Attr` 与它的分别只在反表那一边）。
    """
    attrs: dict[str, object] = {}
    for name, value in fields.items():
        if kind_of(type(block), name) == BODY_KIND:
            attrs[name] = {"v": unwrap(value), "body": True}
            continue
        attrs[name] = {"v": unwrap(value)}
    return attrs


def _table_of(identity: ID) -> str:
    """这个身份该落在哪张表：**表名就是它的名字**（由类型推出来）。

    名字为空即"这个身份没有类型"——那它查不了表，:meth:`Engine.find_block` 回退顺扫。
    """
    return str(identity.name)


def _located(row: dict[str, object]) -> tuple[str, str, SlotRange] | None:
    """从索引行里取出物理坐标；位置段不全即 ``None``（那这一行还没落过盘）。"""
    hub = str(row.get("in_hub") or "")
    pack = str(row.get("in_hub_pack") or "")
    span = _span_of(row.get("in_pack_slot"))
    if not hub or not pack or span is None:
        return None
    return hub, pack, span


def _span_of(value: object) -> SlotRange | None:
    """把索引里那对格号读回来（落盘时写成 ``"头:末"``）。"""
    if isinstance(value, tuple | list) and len(value) == 2:
        return SlotRange(int(value[0]), int(value[1]))
    if not isinstance(value, str) or ":" not in value:
        return None
    head, _, tail = value.partition(":")
    try:
        return SlotRange(int(head), int(tail))
    except ValueError:
        return None


def _place(identity: ID, hub: str, pack: str, span: SlotRange) -> None:
    """把落盘后的物理坐标回填到身份上：**这是位置段的唯一写入口**。

    位置段是投影：记录里不带它，扫到它时位置由扫描给出。
    """
    identity.in_hub = hub
    identity.in_hub_pack = pack
    identity.in_pack_slot = (span.first, span.last)


def _clear_place(identity: ID) -> None:
    """摘掉位置段（删除之后它不该再指着一个已失效的坐标）。"""
    identity.in_hub = ""
    identity.in_hub_pack = ""
    identity.in_pack_slot = (0, 0)


def _new_block(table: str, identity: ID, owner: type[Block] | None = None) -> Block:
    """造一个空块：**有 owner 就用它**；没有才按表名去找注册过的类。

    为什么要 owner：**名字相同的类型满仓都是**（测试里两个文件各有一个 `NoteData`），
    按表名挑会挑到别处那一个——读回来的对象不是调用方那个类，`isinstance` 当场不成立。
    调用方（`NoteData.fetch()`）本来就知道自己是哪个类，故以它为准。

    按表名找是"没带类来"时的兜底；都找不到就用一个通用块——那是"不认识的类型降级读回"
    那条路：属性照旧齐全，只是没有那个类的行为方法。
    """
    if owner is not None and owner.__name__.lower() == table:
        return owner(identity)
    for cls in _known_tables().get(table, ()):
        try:
            return cls(identity)
        except TypeError:  # pragma: no cover — 签名对不上的类跳过，继续找
            continue
    generic: type[Block] = type(table.capitalize(), (Block,), {})
    return generic(identity)


def known_tables() -> tuple[str, ...]:
    """进程内已知的块类型各自的表名（按名字排序）。"""
    return tuple(sorted(_known_tables()))


def _index_owners() -> tuple[type[Any], ...]:
    """进程内已知的索引块类型（惰性引：`index/` 引本模块，故不能反过来在顶部引它）。"""
    from .index.index import owners  # noqa: PLC0415 — 打断环形引用

    return owners()


def _index_tables() -> tuple[str, ...]:
    """索引块各自的表名。"""
    return tuple(owner.__name__.lower() for owner in _index_owners())


def _known_tables() -> dict[str, tuple[type[Block], ...]]:
    """进程内已知的块类型：按表名分组。"""
    found: dict[str, list[type[Block]]] = {}
    for cls in _subclasses(Block):
        found.setdefault(cls.__name__.lower(), []).append(cls)
    return {name: tuple(classes) for name, classes in found.items()}


def _subclasses(root: type[Block]) -> list[type[Block]]:
    """递归收集全部子类。"""
    found: list[type[Block]] = []
    for child in root.__subclasses__():
        found.append(child)
        found.extend(_subclasses(child))
    return found


__all__ = [
    "BODY_NAME",
    "CATALOG_FILENAME",
    "SOURCE",
    "TOMBSTONE_NAME",
    "Block",
    "Engine",
    "bind",
    "current_engine",
    "engine",
]

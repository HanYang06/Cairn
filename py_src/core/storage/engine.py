# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""存储引擎:把块落成载体的槽,再把槽读回来,组织成块对象.

**两个引擎,分工不重叠**:

- 本文件是**存储引擎**:面向载体(pack / hub),负责"分配 hub,分配载体,分配槽",
  把内存里的值写成字节,把字节读回来**组织成 block 对象**交还;
- `core.storage.db.engine` 是**数据库引擎**:面向索引库,只回答"这个身份在哪儿".

**能力靠继承拿到,身份靠调用方给.** `Block` 是那个接口面:

    self.id = ID(self)      # 身份由调用方签发——内核不代签
    note = Note(self.id)    # 递给基座,能力在那一刻成立
    note.title = "标题"
    note.save()             # 引擎接手:分配,编码,落盘,回填位置段

**一个块占属性槽与正文槽**:

- **属性槽**:一个块的全部属性,装不下即占多格;**可原地覆盖**,不进历史;
- **正文槽**:正文分片,按正文自身的**逻辑顺序**切分;**只追加**,写过一格就不再原地改;
- **位置段**:覆盖该块自身占用的全部槽,写进索引库那一行,改一次写一次.
  属性槽排在低位,正文槽排在高位(写入时的次序),而**哪一格是属性,哪一格是正文
  靠槽头种类分辨**(`pack.ATTR_SLOT` / `pack.BODY_SLOT`)——载体上每一格本来就写着.

**坐标系的分辨**(2026-10-02 修正裁定):**槽号只在 pack 内有意义**,故越 pack(甚至越 hub)
的关联只能用摘要,不能用槽号.由此得到两条口径:

- **正文关联走摘要**:库里那一列是**当前正文的摘要**(一个,不是一串);跨 pack,跨 hub
  都成立;
- **正文的位置不挂在块身上**:一份正文的位置(hub 名 + 载体名 + 段列表)记在 `BodyIndex`
  的**位置行**里——那一块被删了,还在引用这份正文的块不该跟着断.

**存储不做版本,不做历史,不做安全**(2026-10-06 裁定):它只做"记录与修改"——
写进来就落,让改就改,让删就删;世代,回滚,崩溃恢复与影子格由上层自行解决.

**块的正文有两种形态**,由两个运行时状态分辨(:attr:`Block._body_hash` /
:attr:`Block._inline_body`,`_` 前缀,不落成列,也不落成额外的槽):

| `_inline_body` | 意思 | `_body_hash` |
|---|---|---|
| `False` | 正文内容在**本块**(本块位置段里有 body 槽) | 这份正文自己的摘要 |
| `True` | 本块**没有**正文内容,正文关联在别处 | **关联凭证**:拿它查正文索引定位那份正文 |

**一次保存只写它动过的域**(属性 / 正文 / 索引三选几),不重写整块.判据落在字节上:
正文按摘要查 `BodyIndex`,属性编出来与库里记的那几格逐字节比——故"没动"是算出来的,
不是调用方声明的.

**去重只针对 `Body` 的内容**:写入前按正文摘要查 `BodyIndex` 的位置行,命中即**本块不写
body 槽**(只占属性槽),正文关联记进库里那一列;`Attr`,裸赋值与资产类二进制(如视频)不去重.

**删除 = 摘掉索引库那一行**:载体上不留任何标记(槽上不记归属),字节由回收收敛.
**正文索引的位置行与正文槽留着**——"还有没有行里的 `body` 指着它"由回收判活.

**读路径没有顺扫回退**:库里没有那一行即显式报错——索引库是权威视角,载体上一个字节的
身份都没有,扫也扫不回来.

**策略参数向配置面要值**(`storage/conf.py`):默认 hub,格长,封口线,索引块上限
与自动回收阈值都在那里声明;构造时不给就用当前配置值.
"""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, NamedTuple, Self, cast

from core.event.catalog import OBJECT_DELETED, OBJECT_PUT
from core.event.events import Event
from core.exc import (
    HubNotFoundError,
    HubShapeError,
    IndexNotFoundError,
    IndexSchemaError,
    ObjectNotFoundError,
    SlotError,
    SlotTooLargeError,
)

from . import conf as storage_conf
from .db.engine import HUB_TABLE, META_TABLE, Index
from .db.id import (
    ID,
    SlotSpan,
    canonical_segments,
    digest,
    pack_segments,
    parse_body,
    parse_segments,
)
from .db.payload import (
    BODY_MARK,
    COLUMN_KEY,
    HUB_KEY,
    PACK_KEY,
    SEGMENTS_KEY,
    VALUE_KEY,
    decode_attrs,
    decode_index_row,
    decode_segments,
    encode_attrs,
    encode_index_row,
    encode_segments,
    index_text,
)
from .hub import Hub, find_hubs
from .pack import ATTR_SLOT, BODY_SLOT, SLOT_HEAD_SIZE, Pack, Slot
from .types import ATTR_KIND, BODY_KIND, kind_of, kinds_of, unwrap

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

    from core.event.bus import Bus

    from .index.index import IndexEngine

CATALOG_FILENAME = "catalog.db"
"""索引库文件名：**路径约定只在这里出现一次**。"""

SOURCE = "core.storage"
"""事件里的发出者标识：写路径发的事件都署它。"""

BODY_KEY = "cairn.body"
"""正文在槽里那一小段 CBOR 映射的键名，也是 `BodyIndex` 里那一列的列名。"""


class SlotPlacement(NamedTuple):
    """一个块在索引里那一行的内容:**哪一列,什么值,落在哪儿**.

    属性行的值是值本身,正文行的值是它的摘要;两者的落点都是槽号列表,
    故索引行与属性槽共用同一种"落点"写法.

    Attributes:
        value: 这一列的值(文本化,带类型名).
        hub: 落点所在的 hub.
        pack: 落点所在的载体名.
        slots: 落点占的槽号(升序).
    """

    value: str
    """这一列的值（文本化，带类型名）。"""

    hub: str
    """落点所在的 hub。"""

    pack: str
    """落点所在的载体名（**正文可能在别的 pack、别的 hub**，故它与 hub 一起记）。"""

    slots: tuple[int, ...]
    """落点占的槽号（升序）。"""


class Engine:
    """存储引擎:分配 hub / 载体 / 槽,把块落进属性槽与正文槽,再按身份读回来.

    Args:
        root: 库根(vault 目录).
        default_hub: 不点名时写进哪个 hub;不给即取配置面的 `hub.default`.
        slot_bytes: **新建**载体时的格长;不给即取配置面两档之和.
            读已有载体一律看它自己的文件头,与这个数无关.
        max_bytes: 封口线;不给即取配置面的 `pack.max.byte`.它只管"什么时候换文件".
        bus: 事件总线;不给即不发事件(写路径不依赖有没有人在听).
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
        """接上库根与索引库.**它不建库根**:建立是显式动作(`Kernel.create`).

        索引库是**惰性开的**:第一次要用它时才建文件.故"只想读载体"的场合
        (只读工具,诊断)不会因为装配一个引擎就凭空多出一个库文件.

        **策略值在这里定下**:构造一次读一次配置面,此后这一次装配里的每个 hub 与载体
        都按同一组数判.
        """
        self._root = Path(root)
        self._default_hub = default_hub or storage_conf.default_hub_name()
        self._slot_bytes = storage_conf.slot_bytes() if slot_bytes is None else slot_bytes
        self._max_bytes = storage_conf.pack_max_bytes() if max_bytes is None else max_bytes
        self._bus = bus
        self._index: Index | None = None
        self._indexes: IndexEngine | None = None

    # ---- 属性 ---- #

    @property
    def root(self) -> Path:
        """库根目录."""
        return self._root

    @property
    def catalog_path(self) -> Path:
        """索引库文件路径:**路径约定只在这里出现一次**."""
        return self._root / CATALOG_FILENAME

    @property
    def index(self) -> Index:
        """索引库:需要时开,并把已知类型的身份表补齐."""
        if self._index is None:
            self._index = Index.create(self.catalog_path)
            self._sync_tables(self._index)
        return self._index

    def _sync_tables(self, index: Index) -> None:
        """把**已知的块类型**各自的身份表补齐:用 ID 就有表,一个不落.

        索引块(`AttrIndex` / `BodyIndex`)也在这份清单里——**它们也是块**,
        有自己的表,与任何块同路.
        """
        for table in (*known_tables(), *_index_tables()):
            index.ensure_table(table)

    def close(self) -> None:
        """关掉引擎手里的资源(索引库连接).**幂等**:没开过或已关都不出错."""
        index = self._index
        if index is not None:
            index.close()
            self._index = None

    def __enter__(self) -> Self:
        """进入 `with`:引擎可用."""
        return self

    def __exit__(self, *_: object) -> None:
        """退出 `with`:关掉资源,无论是否异常."""
        self.close()

    @property
    def default_hub(self) -> str:
        """默认 hub 名."""
        return self._default_hub

    @property
    def slot_bytes(self) -> int:
        """这次装配用的格长:**只决定新建载体写进文件头的那个数**,读已有载体不看它."""
        return self._slot_bytes

    @property
    def max_bytes(self) -> int:
        """这次装配用的封口线(字节):只管"什么时候换文件"."""
        return self._max_bytes

    @property
    def bus(self) -> Bus | None:
        """写路径发事件的那条总线;没有即 `None`(不发)."""
        return self._bus

    @property
    def content_room(self) -> int:
        """一格能装的内容上限(格长减槽头)."""
        return self._slot_bytes - SLOT_HEAD_SIZE

    def _notify(self, event_type: str, identity: ID, data: object = None) -> None:
        """发一条通知:**只在有人听的时候才说话**,且失败绝不回流写路径.

        `Bus.emit` 自己已隔离订阅者的异常;这里再兜住"总线本身也出岔子"那种情形——
        写成功就是写成功,通知是旁路.
        """
        if self._bus is None:
            return
        event = Event(type=event_type, source=SOURCE, subject=identity.value_uuid, data=data)
        with suppress(Exception):
            self._bus.emit(event)

    # ---- 写入 ---- #

    def save(self, block: Block, *, hub: str | None = None) -> ID:
        """把一个块落成属性槽与正文槽,返回块身份(就是调用方递进来那一个,已回填).

        **只写它动过的域**:正文按摘要查 `BodyIndex` 的位置行,属性与库里记的那几格逐字节比.
        库里没有这一行即首次落盘,两样都写.

        **正文两条路**(2026-10-02 修正裁定):

        - **未命中**(盘上还没有同摘要的位置):写 body 槽 + 写一条"摘要 → 位置"的索引行
          + 把库里那一列改成该摘要;
        - **命中**(已有同摘要的位置):**不写 body 槽**,本块只占属性槽,那一列改成该摘要
          ——即引用型,正文的位置由那一行索引给出.

        写序是定死的:**新槽先落定,位置段与那一列摘要后写**.故新槽落稳之前,库里那一行
        仍然指着上一份正文——**上一份要不要留由上层自己留引用**,存储不替它保世代.

        Raises:
            SlotTooLargeError: 属性编出来超过一格能装的字节数.
            AttrTypeError: 值编不进槽(值不是 CBOR 认得的写法).
        """
        identity = block.id
        fields = _fields_of(block)
        hub_name = self._hub_name(hub)
        row = self._row_of(identity)
        attrs = _attrs_of(block, fields)
        chunks = _split(encode_attrs(attrs), self.content_room)
        # **槽序以这一趟的落点为准**:属性槽在前,正文槽在后.旧行那一份位置段只用来
        # 取"旧那一行记的槽",而它是哪一类要**读槽头**才分得清(库里没有那一列).
        old_attr = _attr_slots_of(self, row)
        body = _body_of(block, fields)
        body_hash = content_digest_of_body(body) if body else ""
        attr_slots = self._write_attrs(hub_name, chunks, row, old_attr)
        entries: dict[str, SlotPlacement] = self._index_entries(block, hub_name, attrs, attr_slots)
        body_slots: tuple[int, ...] = ()
        if body:
            found = self._lookup_body(body_hash)
            if found is None:
                body_slots = self._append_slots(
                    hub_name, BODY_SLOT, _split(_encode_body(body), self.content_room)
                )
                body_hub = hub_name
                body_pack = _first_pack(hub_name, self._root)
            else:
                body_hub = found.hub
                body_pack = found.pack
                # **命中即不写 body 槽**:本块只占属性槽,正文的位置由那一行索引给出
                # (2026-10-02 修正裁定).位置段的槽号只对这一份载体成立,
                # 故引用别处的正文不能把它的格号搬进本块的位置段.
                # 待作者确认:位置就是本块那几格时仍算不算自带.
                body_slots = ()
            segments = canonical_segments(body_slots)
            entries[BODY_KEY] = SlotPlacement(
                value=index_text(body_hash),
                hub=body_hub,
                pack=body_pack,
                slots=_slots_of(segments),
            )
            identity.body = body_hash
        self._place(identity, hub_name, attr_slots, body_slots)
        block.stamp_body(body_hash, inline=not body_slots)
        self._index_block(block, identity, entries)
        self._register(block, identity)
        self._notify(
            OBJECT_PUT,
            identity,
            {"table": block.type_name, "segments": pack_segments(identity.in_pack_slot)},
        )
        return identity

    def _write_attrs(
        self,
        hub_name: str,
        chunks: list[bytes],
        row: dict[str, object] | None,
        current: tuple[int, ...],
    ) -> tuple[int, ...]:
        """安排属性槽:**格数够就原地覆盖,不够才另占几格**.

        原地覆盖是本裁定给属性槽的写法,故"属性变了"不产生新槽,也不进历史;
        非到格数都不够才另占.此时旧的那几格从此不再被这一行指着,由回收收走.
        """
        if len(current) == len(chunks) and _hub_of(row) == hub_name and _pack_of(row):
            pack = self._open_pack(hub_name, _pack_of(row))
            for index, slot in enumerate(current):
                pack.overwrite(slot, ATTR_SLOT, chunks[index])
            return tuple(_slots_of(current))
        return self._append_slots(hub_name, ATTR_SLOT, chunks)

    def _lookup_body(self, content: str) -> SlotPlacement | None:
        """按正文摘要查 `BodyIndex` 的**位置行**:**写入去重只走这一条**,不扫全库.

        命中即那一份正文已经在载体上,故返回**它的坐标**(hub 名 + 载体名 + 段列表);
        没命中即要写新槽.`BodyIndex` 缺位时退化为"没命中",于是每次都写新槽——
        **数据不丢,只是不去重**.

        **位置不挂在块身上**:位置行里没有"哪个块拥有它"这一项,故那一块被删了,
        还在引用这份正文的块照样找得到它.

        Args:
            content: 正文摘要(原样;文本化由索引那一层做,免得两处各化一次).
        """
        for row in self.index_engine.search(_owner(BODY_KIND), BODY_KEY, content):
            hub_name = str(row.get(HUB_KEY) or "")
            pack_name = str(row.get(PACK_KEY) or "")
            segments = decode_segments(row.get(SEGMENTS_KEY))
            if not hub_name or not pack_name or not segments:
                continue
            return SlotPlacement(
                value=index_text(content),
                hub=hub_name,
                pack=pack_name,
                slots=_slots_of(segments),
            )
        return None

    def _index_entries(
        self,
        block: Block,
        hub_name: str,
        attrs: Mapping[str, object],
        attr_slots: tuple[int, ...],
    ) -> dict[str, SlotPlacement]:
        """这个块的属性各列在索引里那一行:列名 → 值 + 落点.

        **落点对全部属性是一样的**——它们同住那几格属性槽,故索引行的落点照抄即可;
        值另取一遍(属性槽里存的是值,直接读出来文本化).
        """
        kinds = kinds_of(type(block))
        return {
            name: SlotPlacement(
                value=index_text(getattr(block, name, None)),
                hub=hub_name,
                pack=_first_pack(hub_name, self._root),
                slots=attr_slots,
            )
            for name in attrs
            if kinds.get(name) == ATTR_KIND
        }

    def _index_block(
        self, block: Block, identity: ID, entries: Mapping[str, SlotPlacement]
    ) -> None:
        """把这个块的**正表行**写进各类索引:**声明了 `Attr` / `Body` 就必然进来**.

        哪些列进哪一类索引,由索引块自己声明的 `manages` 定.故这里没有一行
        "哪个字段该不该索引"的判断.

        **正文那一行只写"位置已经有主"的场合**:命中已有位置时本块不写 body 槽,
        位置行已经在了,故不再写一遍——`BodyIndex` 的位置行是"这份正文在哪",
        不是"哪个块提过它".
        """
        kinds = kinds_of(type(block))
        for owner in _index_owners():
            manages = owner.__dict__.get("manages")
            row: dict[str, SlotPlacement] = {}
            if manages == BODY_KIND and BODY_KEY in entries and not block.body_is_ref:
                row[BODY_KEY] = entries[BODY_KEY]
            if manages == ATTR_KIND:
                row.update(
                    {
                        name: placed
                        for name, placed in entries.items()
                        if kinds.get(name) == ATTR_KIND
                    }
                )
            if row:
                self.lay_index_row(owner, identity.value_uuid, row)

    def lay_index_row(
        self, owner: type[Any], value_uuid: str, row: Mapping[str, SlotPlacement]
    ) -> None:
        """把一个块的正表行写进 `owner` 这类索引块;**满了自动续下一块**.

        **一条行一个槽**,故写路径只有追加,没有改动.索引块也是块:它有身份,有表,
        故"查索引时它搁哪儿"由库里那一行回答.

        **两类行的形状不一样**(2026-10-02 修正裁定):

        - **属性索引行**:`field` / `value_uuid` / `value` / `hub` / `pack` / `segments`
          ——它答的是"这个块的这一列等于这个值",故要能顺 `value_uuid` 回到那个块;
        - **正文索引行**:`field` / `value` / `hub` / `pack` / `segments`——它答的是
          "这份正文在哪",**不记哪个块拥有它**.位置挂在某个块身上,那一块被删了,
          还在引用这份正文的块就断了.

        Args:
            owner: 索引块的类型(`AttrIndex` / `BodyIndex`).
            value_uuid: 这一行属于哪个块(**只有属性那一路用得上**).
            row: 列名 → 落点.
        """
        hub_name = self._default_hub
        table = owner.__name__.lower()
        is_body = owner.__dict__.get("manages") == BODY_KIND
        live = self._active_index(owner, hub_name)
        if live is None:
            # **索引块的身份按块的标准用法来**:`owner()` 自己签一个(那两行就在它的
            # `__init__` 里).它是块,故它自然进库,有表.
            live = ID(table, value_uuid=owner().id.value_uuid)
        for column, placement in row.items():
            payload = encode_index_row(
                {
                    COLUMN_KEY: column,
                    **({} if is_body else {"value_uuid": value_uuid}),
                    "value": placement.value,
                    HUB_KEY: placement.hub,
                    PACK_KEY: placement.pack or _first_pack(placement.hub, self._root),
                    SEGMENTS_KEY: encode_segments(canonical_segments(placement.slots)),
                }
            )
            if len(payload) > self.content_room:
                raise SlotTooLargeError(
                    f"一条索引行装不下: {len(payload)} 字节（可用 {self.content_room}）"
                )
            written = self._append_slots(hub_name, ATTR_SLOT, [payload])
            live.in_hub = hub_name
            live.in_hub_pack = _first_pack(hub_name, self._root)
            live.add_slot(written[0])
            self._register_index(owner, live, hub_name)

    def _active_index(self, owner: type[Any], hub_name: str) -> ID | None:
        """挑一个**还有地方**的索引块:最后写的那一块没到上限就用它,否则 ``None``(续一块).

        上限取配置 `index.max.byte`(块自己用 `max_bytes` 覆盖它).

        **挑的是"最新那一块"**:索引块按写入次序一个接一个续,故最近登记的那个就是活跃的.
        续块的场合由调用方另签一个身份(`owner()`),它随即成为新的一行.
        """
        limit = max(1, int(owner.max_bytes) or storage_conf.index_max_bytes())
        table = owner.__name__.lower()
        latest: dict[str, object] | None = None
        try:
            for candidate in self.index.rows(table):
                if str(candidate.get("in_hub") or "") == hub_name:
                    latest = candidate
        except IndexNotFoundError, IndexSchemaError:  # pragma: no cover — 表由引擎补齐
            return None
        if latest is None or len(_slots_of_place(latest)) * self._slot_bytes >= limit:
            return None
        return ID.from_row(latest)

    def _register_index(self, owner: type[Any], identity: ID, hub_name: str) -> None:
        """把索引块自己也登记进库:**它也是块,用了 ID 就有表**.

        这一步不是可选的:索引一多就"不知道它搁哪儿了",故它必须进身份表.
        """
        table = owner.__name__.lower()
        index = self.index
        index.ensure_table(table)
        index.register_hub(hub_name)
        index.put(table, identity.to_row())

    def _register(self, block: Block, identity: ID) -> None:
        """把这个身份写进它那张表:**用了 ID 就有表,有了表就有一行**.

        库里那一行的列由 `columns_of()` 现算:身份字段,位置段,再加正文摘要那一列.
        """
        table = block.type_name
        index = self.index
        index.ensure_table(table)
        index.register_hub(identity.in_hub)
        index.put(table, identity.to_row())

    def _place(
        self,
        identity: ID,
        hub_name: str,
        attr_slots: tuple[int, ...],
        body_slots: tuple[int, ...],
    ) -> None:
        """把这次的落点写进身份:**位置段是真源,改一次写一次**.

        位置段只收**这个块自己的槽**:属性槽在前,正文槽在后.
        **引用别处的正文时,那几格不进这里**——它们属于别的 pack,而位置段的槽号
        只对这一份载体成立(2026-10-02 修正裁定).故正文关联记在那一列摘要里.

        **索引块里那条正表行占的槽不进这里**——它属于索引块,而"索引块自己搁哪儿"
        写在它自己那张索引表里(`_register_index`).混进来会把位置段搅乱,而且不报错.

        载体名由 hub 当场取一份——一份块**自己**的槽落在同一个 hub,故一个名字就够.
        """
        found: list[list[int]] = []
        if body_slots:
            found.append(list(body_slots))
        found.append(list(attr_slots))
        identity.place(*found, hub=hub_name, pack=_first_pack(hub_name, self._root))

    def _hub_name(self, explicit: str | None) -> str:
        """这一次写进哪个 hub."""
        return explicit or self._default_hub

    def _open_hub(self, name: str) -> Hub:
        """取一个可写的 hub;不在即建(建立 hub 是写路径的正当动作)."""
        return Hub.create(self._root / name, slot_bytes=self._slot_bytes, max_bytes=self._max_bytes)

    def _open_pack(self, hub_name: str, pack_name: str) -> Pack:
        """打开一个已有的载体(原地覆盖与读取走这一条;**不新建**)."""
        return Hub.open(self._root / hub_name, max_bytes=self._max_bytes).pack(pack_name)

    def _append_slots(self, hub_name: str, kind: int, chunks: list[bytes]) -> tuple[int, ...]:
        """把一格一格的内容追加到 hub 里,返回它占的槽号(升序)."""
        hub = self._open_hub(hub_name)
        written: list[int] = []
        for chunk in chunks:
            _pack_name, slot = hub.append(kind, chunk)
            written.append(slot)
        return tuple(written)

    def _row_of(self, identity: ID) -> dict[str, object] | None:
        """按身份取库里那一行;没有那一行,或没有那张表即 ``None``(那是首次落盘)."""
        table = identity.name
        if not table or not self.catalog_path.is_file():
            return None
        try:
            return self.index.get(table, identity.value_uuid)
        except IndexNotFoundError, IndexSchemaError:
            return None

    # ---- 索引:**由正表现算反表**,索引块只声明参数 ---- #

    @property
    def index_engine(self) -> IndexEngine:
        """索引引擎:把正表行写进索引块,把反表翻出来."""
        if self._indexes is None:
            from .index.index import IndexEngine  # noqa: PLC0415 — 打断环形引用

            self._indexes = IndexEngine(self)
        return self._indexes

    def read_index_rows(self, owner: type[Any]) -> Iterator[dict[str, object]]:
        """读出一类索引的**全部正表行**.

        **多块合并**:同一类索引可以有好几块(上个满了就续了下一个),并起来才是完整的
        正表.同一个块同一列写过多次时,**每一条都留着**——反表是"值 → 哪些块",
        块的身份与那一次写入的值都不同,故两行都得算数;去重按(列,值,块身份)三样来.

        **指向已删块的那几行不算**:库里已经没有那一行了,它查不回任何东西.
        这一层过滤不靠顺扫,靠库里那几行在不在.

        **正文索引的行不带块的凭证**(它答的是"这份正文在哪",不是"哪个块提过它"),
        故它不参与这一层过滤——那份正文还在不在,由库里那一列的摘要与 `gc` 判活.
        """
        alive = self._alive_uuids()
        seen: set[tuple[str, str, str]] = set()
        for row in self._index_block_rows(owner):
            column = str(row.get(COLUMN_KEY) or "")
            target = str(row.get("value_uuid") or "")
            value = str(row.get("value") or "")
            if target and target not in alive:
                continue
            if (column, value, target) in seen:
                continue
            seen.add((column, value, target))
            yield row

    def _alive_uuids(self) -> frozenset[str]:
        """库里还存在的身份(全部身份表的凭证并起来)."""
        found: set[str] = set()
        for _table, row in self._identity_rows():
            uuid = str(row.get("value_uuid") or "")
            if uuid:
                found.add(uuid)
        return frozenset(found)

    def _identity_rows(self) -> Iterator[tuple[str, dict[str, object]]]:
        """逐张身份表逐行交出来:**库自用的那两张不在其中**."""
        try:
            tables = self.index.tables()
        except IndexNotFoundError, IndexSchemaError:  # pragma: no cover — 库刚开过
            return
        for table in tables:
            if table in {HUB_TABLE, META_TABLE}:
                continue
            for row in self.index.rows(table):
                yield table, row

    def identity_rows(self) -> Iterator[tuple[str, dict[str, object]]]:
        """逐张身份表逐行交出来:**库自用的那两张不在其中**.

        它是"库里那些行"的公开读口(索引引擎要按那一列的正文摘要现算"谁在用它");
        **读侧的一切定位仍走那一行给出的段列表**,这一问只服务反表与判活.
        """
        yield from self._identity_rows()

    def _index_block_rows(self, owner: type[Any]) -> Iterator[dict[str, object]]:
        """逐个索引块读出它槽里的正表行:**它也是块,行落在载体的槽上**."""
        table = owner.__name__.lower()
        try:
            rows = tuple(self.index.rows(table))
        except IndexNotFoundError, IndexSchemaError:  # pragma: no cover — 表由引擎补齐
            return
        for row in rows:
            hub_name = _hub_of(row)
            pack_name = _pack_of(row)
            if not hub_name or not pack_name:
                continue
            pack = self._open_pack(hub_name, pack_name)
            for slot in _slots_of_place(row):
                parsed = decode_index_row(pack.content_at(slot))
                if parsed is not None:
                    yield parsed

    # ---- 读取 ---- #

    def scan(self) -> Iterator[tuple[str, str, int, Slot]]:
        """顺扫全库的槽:交出(hub 名,载体名,槽号,槽).

        **它只服务诊断与回收**:读侧的一切定位都走索引库那一行给出的段列表.
        """
        for hub in find_hubs(self._root):
            for pack in hub.packs():
                for number, slot in pack.scan():
                    yield hub.name, pack.name, number, slot

    def scan_slots(self, identity: ID) -> list[Slot]:
        """按身份读回它**全部槽的原文**(按槽号升序),供命令面交出原文.

        Raises:
            ObjectNotFoundError: 库里没有这一行,或它指着的那一格读不出来.
        """
        return self._read_slots(self._locate(identity))

    def index_row(self, identity: ID) -> dict[str, object]:
        """按身份取库里那一行(身份,位置段,正文摘要都在里面).

        Raises:
            ObjectNotFoundError: 库里没有这一行.
        """
        return self._locate(identity)

    def _locate(self, identity: ID) -> dict[str, object]:
        """按身份取库里那一行;**行不在即报错**,没有顺扫回退.

        Raises:
            ObjectNotFoundError: 库里没有这一行(或它还没有落点).
        """
        row = self._row_of(identity)
        if row is None or not _hub_of(row):
            raise ObjectNotFoundError(f"对象不在: {identity.value_uuid}")
        return row

    def _read_slots(self, row: Mapping[str, object]) -> list[Slot]:
        """照库里那一行的段列表逐格读出槽.

        Raises:
            ObjectNotFoundError: 载体不在,或那一格读不出来.
        """
        try:
            pack = self._open_pack(_hub_of(row), _pack_of(row))
            return [pack.read(slot) for slot in _slots_of_place(dict(row))]
        except (HubNotFoundError, SlotError) as error:
            raise ObjectNotFoundError(f"对象不在: 槽读不出来（{_pack_of(row)}）") from error

    def find_block(self, identity: ID) -> tuple[str, str, tuple[SlotSpan, ...], bytes]:
        """按身份找**它的属性槽内容**:返回(hub 名,载体名,段列表,属性字节).

        **只走索引库这一条路**:库里没有那一行即显式报错,没有顺扫回退.

        Raises:
            ObjectNotFoundError: 库里没有这一行,或它指着的那一格读不出来.
        """
        row = self._locate(identity)
        held = self._read_slots(row)
        attrs = self._read_attrs(row, held)
        return _hub_of(row), _pack_of(row), _segments_of_place(row), attrs

    def load(self, identity: ID, owner: type[Block] | None = None) -> Block:
        """按身份读回一个块:**读属性槽与正文槽,解码,组织成对象交还**.

        **正文那两跳**(2026-10-02 修正裁定):先由库里那一行取**当前正文的摘要**;
        再看**本块位置段里有没有 body 槽**(槽头判种类)——

        - **有**(自带):读本块的 body 槽;
        - **没有**(引用型):拿摘要查正文索引的位置行,按它给出的 hub / 载体 / 段列表
          去读那一份正文.

        `_body_hash` 与 `_inline_body` 在这一跳里**推出来**并写进块对象:极性见
        :attr:`Block._inline_body`.

        Args:
            identity: 要读的那个身份.
            owner: **以哪个类为准**(`NoteData.fetch()` 就是 `NoteData`).给了它就用它,
                不再按表名去猜——名字相同的类型满仓都是,猜会挑错那一个.

        Raises:
            ObjectNotFoundError: 库里没有这个身份,或它指着的那一格读不出来.
        """
        row = self._locate(identity)
        held = self._read_slots(row)
        attrs = decode_attrs(self._read_attrs(row, held))
        block_id = _identity_from_row(identity, row)
        block = _new_block(identity.name, block_id, owner=owner)
        values, body_hash, inline = self._read_body(row, held)
        block.stamp_body(body_hash, inline=inline)
        _fill(block, attrs, values)
        return block

    def _read_attrs(self, row: Mapping[str, object], held: list[Slot]) -> bytes:
        """属性槽的内容逐格读出来并拼起来:**按槽头种类挑**.

        **不再按"末尾几格"或某一列做差**:属性槽与正文槽靠槽头分辨
        (`pack.ATTR_SLOT` / `pack.BODY_SLOT`),载体上每一格本来就写着.
        """
        del row
        return b"".join(slot.content for slot in held if slot.kind == ATTR_SLOT)

    def _read_body(
        self, row: Mapping[str, object], held: list[Slot]
    ) -> tuple[list[object], str, bool]:
        """读出正文:返回(正文值,正文摘要,是否引用型).

        **自带那一路**:位置段里那几格 body 槽就是这份正文,摘要当场算.
        **引用那一路**:位置段里没有 body 槽,故拿库里那一行那一列的摘要去
        `BodyIndex` 的位置行上查——位置行给出 hub 名,载体名与段列表.

        Raises:
            ObjectNotFoundError: 引用型而正文索引里没有那份正文,或那一格读不出来.
        """
        slots = [slot for slot in held if slot.kind == BODY_SLOT]
        if slots:
            return _decode_body([slot.content for slot in slots]), _digest_of_slots(slots), False
        digest_value = _body_of_row(row)
        if not digest_value:
            return [], "", True
        placement = self._lookup_body(digest_value)
        if placement is None:
            raise ObjectNotFoundError(f"引用已失效: 正文不在索引里（{digest_value}）")
        return (
            _decode_body([slot.content for slot in self._read_at(placement)]),
            digest_value,
            True,
        )

    def _read_at(self, placement: SlotPlacement) -> list[Slot]:
        """按一份正文的坐标读出它那几格(**跨 pack,跨 hub 也一样**).

        Raises:
            ObjectNotFoundError: 载体不在,或那一格读不出来.
        """
        try:
            pack = self._open_pack(placement.hub, placement.pack)
            return [pack.read(slot) for slot in placement.slots]
        except (HubNotFoundError, SlotError) as error:
            raise ObjectNotFoundError(
                f"引用已失效: 正文那一格读不出来（{placement.pack}）"
            ) from error

    # ---- 删除 ---- #

    def delete(self, identity: ID) -> bool:
        """删掉一个块:**摘掉索引库那一行**,返回是否确实摘掉了一个.

        **载体上不留标记**:槽上不记归属,删后的载体字节不再属于任何块,由回收收走.
        """
        if self._row_of(identity) is None:
            return False
        try:
            dropped = self.index.drop_row(_table_of(identity), identity.value_uuid)
        except IndexNotFoundError, IndexSchemaError:
            return False
        if not dropped:
            return False
        identity.clear_place()
        self._notify(OBJECT_DELETED, identity)
        return True

    def __repr__(self) -> str:
        """诊断用:库根与默认 hub,不读盘."""
        return f"Engine(root={self._root!s}, hub={self._default_hub!r})"


# ---- 槽内容的切分与拼装 ---- #


def _split(content: bytes, room: int) -> list[bytes]:
    """把一段字节按格内的可用长度切开;空内容切出空序列(不凭空占一格)."""
    if not content:
        return []
    return [content[start : start + room] for start in range(0, len(content), room)]


def _encode_body(body: list[object]) -> bytes:
    """把一份正文编成 canonical CBOR:**整份内容一个摘要**,分片只是它的切片.

    带一层映射是为了让正文能被"按值判同":canonical 编码保证同一份值恒得同一段字节.
    """
    return encode_attrs({BODY_KEY: body})


def _decode_body(fragments: Iterable[bytes]) -> list[object]:
    """把正文分片拼回一份正文:分片顺序即逻辑顺序."""
    joined = b"".join(fragments)
    if not joined:
        return []
    values = decode_attrs(joined).get(BODY_KEY)
    return list(values) if isinstance(values, list) else [values]


def content_digest_of_body(body: list[object]) -> str:
    """一份正文的摘要:**写入去重与 `BodyIndex` 共用的唯一口径**."""
    return digest(_encode_body(body))


def content_digest(block: Block) -> str | None:
    """一个块的**正文摘要**;它没有正文字段时是 ``None``.

    **这是正文索引与正文槽共用的唯一口径**:索引那边按它反查位置行,引擎这边按它写槽——
    两处若各算一份,按正文反查就永远查不到东西,而且**不报错**.
    """
    body = _body_of(block, _fields_of(block))
    return content_digest_of_body(body) if body else None


# ---- 库里那一行的读法 ---- #


def _digest_of_slots(slots: list[Slot]) -> str:
    """一份正文(它那几格)的摘要:**与写侧同一个口径**(整份内容的 canonical CBOR)."""
    return digest(b"".join(slot.content for slot in slots))


def _attr_slots_of(engine: Engine, row: Mapping[str, object] | None) -> tuple[int, ...]:
    """库里那一行里**属性槽**占的那几格:位置段里槽头是属性槽的那几格.

    **种类只从槽头读**(2026-10-02 修正裁定):库里没有哪一列记它.这一问只为写路径
    服务(属性原地覆盖要看旧的那几格),故它读一次载体;行不在,载体读不出来都当"没有".
    """
    if row is None:
        return ()
    hub_name = _hub_of(row)
    pack_name = _pack_of(row)
    if not hub_name or not pack_name:
        return ()
    try:
        pack = engine._open_pack(hub_name, pack_name)  # noqa: SLF001 — 同一层的私有读口
    except HubNotFoundError:
        return ()
    found: list[int] = []
    for slot in _slots_of_place(dict(row)):
        with suppress(SlotError, HubShapeError):
            if pack.read(slot).kind == ATTR_SLOT:
                found.append(slot)
    return tuple(found)


def _hub_of(row: Mapping[str, object] | None) -> str:
    """库里那一行的 hub 名."""
    return "" if row is None else str(row.get("in_hub") or "")


def _pack_of(row: Mapping[str, object] | None) -> str:
    """库里那一行的载体名."""
    return "" if row is None else str(row.get("in_hub_pack") or "")


def _body_of_row(row: Mapping[str, object] | None) -> str:
    """库里那一行的**当前正文摘要**;没有正文时空串."""
    return "" if row is None else parse_body(str(row.get("body") or ""))


def _segments_of_place(row: Mapping[str, object] | None) -> tuple[SlotSpan, ...]:
    """库里那一行的位置段(规范形)."""
    return () if row is None else parse_segments(str(row.get("in_pack_slot") or ""))


def _slots_of_place(row: Mapping[str, object]) -> tuple[int, ...]:
    """库里那一行覆盖的全部槽号(升序)."""
    return _slots_of(_segments_of_place(row))


def _slots_of(spans: Iterable[SlotSpan | int]) -> tuple[int, ...]:
    """把段列表展开成一串槽号,**次序照段列表**.

    **不归位**:位置段的次序有意义(属性槽在前,正文槽在后).归位会把这个次序翻过来,
    而**不报错**.要规范形的地方(回收,诊断)另行调 :func:`canonical_segments`.

    它也收"已经是一串槽号"的写法(`SlotPlacement.slots` 就是那一串).
    """
    found: list[int] = []
    for item in spans:
        if isinstance(item, int):
            found.append(item)
            continue
        found.extend(range(item[0], item[1] + 1))
    return tuple(found)


def _first_pack(hub_name: str, root: Path) -> str:
    """一个 hub 里的载体名.

    **一份块自己的槽落在同一个 hub**,故名字取哪一个都一样;取排序后的第一个,
    使同一个 hub 里的位置段恒得同一个名字.**引用别处的正文不在其中**:它的坐标
    记在正文索引的位置行里(hub 名与载体名各记一处).
    """
    hub = Hub.open(root / hub_name)
    names = hub.pack_names()
    return names[0] if names else ""


def _identity_from_row(identity: ID, row: Mapping[str, object]) -> ID:
    """由库里那一行还原块身份:**位置段与正文摘要也一并回填**."""
    restored = ID(
        identity.name,
        value_uuid=identity.value_uuid,
        birth_time=_int_or_zero(row.get("birth_time")),
    )
    restored.in_hub = _hub_of(row)
    restored.in_hub_pack = _pack_of(row)
    restored.in_pack_slot = list(_segments_of_place(row))
    restored.body = parse_body(str(row.get("body") or ""))
    return restored


def _int_or_zero(value: object) -> int:
    """把整数字段读回:缺失取 0,形态非法即抛(不静默吞掉脏值)."""
    if value is None or value == "":
        return 0
    try:
        return int(str(value))
    except ValueError as error:
        raise ObjectNotFoundError(f"库里那一行的整数字段非法: {value!r}") from error


# ---- 字段分类与装载 ---- #


def _fill(block: Block, attrs: dict[str, object], values: list[object]) -> None:
    """把属性与正文填进块对象:正文的字段按**声明次序**取正文里那一项."""
    cursor = 0
    for name, entry in attrs.items():
        if isinstance(entry, dict) and entry.get(BODY_MARK):
            value = values[cursor] if cursor < len(values) else None
            cursor += 1
            setattr(block, name, value)
            continue
        if not isinstance(entry, dict) or VALUE_KEY not in entry:
            setattr(block, name, entry)
            continue
        setattr(block, name, entry[VALUE_KEY])


def _fields_of(block: Block) -> dict[str, object]:
    """把一个块的**用户字段**读出来:**以类体声明的为准,再并上实例上多出来的**.

    为什么不能只看 `vars()`:**没显式赋过值的声明字段不在 `vars()` 里**.
    `class Counted(Block): count: int = Attr(0)` 造出来只带默认值,此时 `vars()` 只有
    `id`——只看它,这个字段就既不落盘也不进索引,而且**不报错**(读回来像是"从没写过").
    故声明过的字段一律取出来(取值即触发描述符给出那份默认值).

    顺序:先按类体声明的书写顺序,再补实例上多出来的(那些是裸赋值,照样落盘).
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


def _body_of(block: Block, fields: dict[str, object]) -> list[object]:
    """正文槽里装的东西:**落点为正文的那几个字段值**,按字段次序.

    正文的身份是**它的值**(字段名只是装载方式),故同值恒得同一个摘要:同一份正文
    挂在两个不同名字的字段上,也只存一份.
    """
    return [
        unwrap(value) for name, value in fields.items() if kind_of(type(block), name) == BODY_KIND
    ]


def _attrs_of(block: Block, fields: dict[str, object]) -> dict[str, object]:
    """属性槽的内容:**除身份与正文以外的全部字段**,每个字段装成值加它的落点.

    每个字段装成一个映射 ``{"v": 值}``;正文字段只留一个标记 ``{"body": true}``,
    **值不在属性槽里**(它在正文槽里)——这样属性槽里就没有正文的字节,两者各归各的:

    - **值在这里**:属性槽因此自足——顺读即得全部属性值;
    - **落点也在这里**:赋值一步就会覆盖 `Body(...)` 的声明,故落点必须与值一起存下来,
      否则回读时分不清哪些字段的内容在正文槽里.
    """
    attrs: dict[str, object] = {}
    for name, value in fields.items():
        if kind_of(type(block), name) == BODY_KIND:
            attrs[name] = {BODY_MARK: True}
            continue
        attrs[name] = {VALUE_KEY: unwrap(value)}
    return attrs


def _new_block(table: str, identity: ID, owner: type[Block] | None = None) -> Block:
    """造一个空块:**有 owner 就用它**;没有才按表名去找注册过的类.

    理由:**名字相同的类型满仓都是**(测试里两个文件各有一个 `NoteData`),
    按表名挑会挑到别处那一个——读回来的对象不是调用方那个类,`isinstance` 当场不成立.

    按表名找是"没带类来"时的兜底;都找不到就用一个通用块——那是"不认识的类型降级读回"
    那条路:属性照旧齐全,只是没有那个类的行为方法.
    """
    if owner is not None and owner.__name__.lower() == table:
        return owner(identity)
    for cls in _known_tables().get(table, ()):
        try:
            return cls(identity)
        except TypeError:  # pragma: no cover — 签名对不上的类跳过,继续找
            continue
    generic: type[Block] = type(table.capitalize(), (Block,), {})
    return generic(identity)


def known_tables() -> tuple[str, ...]:
    """进程内已知的块类型各自的表名(按名字排序)."""
    return tuple(sorted(_known_tables()))


def _index_owners() -> tuple[type[Any], ...]:
    """进程内已知的索引块类型(惰性引:`index/` 引本模块,故不能反过来在顶部引它)."""
    from .index.index import owners  # noqa: PLC0415 — 打断环形引用

    return owners()


def _index_tables() -> tuple[str, ...]:
    """索引块各自的表名."""
    return tuple(owner.__name__.lower() for owner in _index_owners())


def _owner(manages: str) -> type[Any]:
    """管某一类落点的索引块类型."""
    for owner in _index_owners():
        if owner.__dict__.get("manages") == manages:
            return owner
    raise LookupError(f"没有索引块管这一类落点: {manages!r}")  # pragma: no cover — 索引在册


def _known_tables() -> dict[str, tuple[type[Block], ...]]:
    """进程内已知的块类型:按表名分组."""
    found: dict[str, list[type[Block]]] = {}
    for cls in _subclasses(Block):
        found.setdefault(cls.__name__.lower(), []).append(cls)
    return {name: tuple(classes) for name, classes in found.items()}


def _subclasses(root: type[Block]) -> list[type[Block]]:
    """递归收集全部子类(含隔代)."""
    found: list[type[Block]] = []
    for child in root.__subclasses__():
        found.append(child)
        found.extend(_subclasses(child))
    return found


def _table_of(identity: ID) -> str:
    """这个身份该落在哪张表:**表名就是它的名字**(由类型推出来)."""
    return str(identity.name)


class Block:
    """存储单元的基座:**身份由调用方给,能力在那一刻成立**.

    没有 ID 就没有一切——拿不到 ID,内核完全不参与:不建表,不入库,不与数据库产生任何关系.
    故本类**只有一条构造路**:

        self.id = ID(self)          # 调用方签发身份
        note = Note(self.id)        # 递给基座
        note.title = "标题"          # 想怎么玩怎么玩
        note.save()                 # 引擎接手

    Attributes:
        id: 块自己的身份.**由调用方签发并递入**,本基座不代签.
        _body_hash: **正文摘要**.**运行时状态,不落成库的列,也不落成额外的槽**——
            载入时由库里那一行与槽头推出来.极性见 :attr:`_inline_body`.
        _inline_body: **正文在不在本块**.`False` 即正文内容在本块(本块位置段里有
            body 槽),`_body_hash` 是这份正文自己的摘要;`True` 即本块没有正文内容,
            正文关联在别处,`_body_hash` 是**关联凭证**——拿它查正文索引定位那份正文.
    """

    max_bytes: ClassVar[int] = 0
    """这个块的**体积上限**（字节）；`0` 即用配置面的默认（`index.max.byte`）。

    它只管"什么时候该续下一个块"——引擎按它决定续块（索引块就靠这一条自动一块接一块）。
    **它是配置性的参数，不是写死的格式常量**：故声明在这里的是"这个类型要比默认更宽
    还是更窄"，默认值本身在 `storage/conf.py`。
    """

    @classmethod
    def holds(cls, block: Block) -> dict[str, object]:
        """这个块在**某类索引**里正表的那一行:字段名 → 值.

        基座上默认**没有**(空映射):普通块不进任何索引.索引块把它接上——
        `AttrIndex` 交出 `Attr(...)` 声明的字段(正文那一列由引擎另行给出,它的值要算).
        声明放在这一层,是因为"这个块能按什么被查"本来就是块自己的性质.
        """
        del block
        return {}

    def __init__(self, id: ID | None = None) -> None:
        """收下身份;**不给就现签一个**(`ID(self)`).

        身份从哪来只有两条路,都写在这一处:

            self.id = ID(self)                   # 自己签
            super().__init__(self.id)            # 递给基座

        或把签好的递进来(`Note(self.id)`).**零参构造是一个块**——这就是
        "索引块由引擎按需造出来"那条路:`AttrIndex()` 自己签身份,于是它自然进库,有表.

        **两个正文状态在构造时就位**:当场造出来的块还没有正文(`_body_hash` 空,
        `_inline_body` 真),载入时由 :meth:`Engine.load` 按库里那一行与槽头改写.
        """
        self.id = ID(self) if id is None else id
        if not isinstance(self.id, ID):
            raise TypeError(f"块必须拿到一个 ID，拿到的是 {type(self.id).__name__}")
        self._body_hash = ""
        self._inline_body = True

    @property
    def type_name(self) -> str:
        """这个块的表名,**只由类的名字算出来**.

        `class NoteData` → `notedata`.没有第二个口子:表名不由声明给出,由类名算出——
        故这里也不提供任何 `__table__` 一类的覆盖.
        """
        return type(self).__name__.lower()

    @property
    def body_hash(self) -> str:
        """正文摘要:自带时是这份正文自己的摘要,引用型时是**关联凭证**.

        它不落盘:载入时由库里那一行与载体的槽头推出来(:attr:`_inline_body` 说极性).
        """
        return self._body_hash

    @property
    def body_is_ref(self) -> bool:
        """正文是不是**引用型**(本块没有正文内容,正文关联在别处).

        极性照 :attr:`_inline_body`:它是 `_inline_body` 的对外读法——
        `_` 前缀那两个是运行时状态,故"谁能读"由这一对属性开口.
        """
        return self._inline_body

    def stamp_body(self, body_hash: str, *, inline: bool) -> None:
        """**写进两个正文状态**:引擎在载入与落盘之后各调一次,别处不写它们.

        Args:
            body_hash: 正文摘要.
            inline: 正文内容在不在本块(见 :attr:`_inline_body` 的极性).
        """
        self._body_hash = body_hash
        self._inline_body = inline

    @classmethod
    def declared_kinds(cls) -> dict[str, str]:
        """这个类型声明了哪些落点:字段名 → `'body'` / `'attr'`.

        **从类体上读**:声明是描述符,活得比任何一次赋值更久,故不必在实例上再记一本账.
        是类方法而不是属性——属性会被同名的类体声明覆盖掉.
        """
        return kinds_of(cls)

    def save(self, *, hub: str | None = None) -> ID:
        """存进去:引擎分配 hub / 载体 / 槽,回填位置段,返回块身份."""
        return engine().save(self, hub=hub)

    @classmethod
    def fetch(cls, identity: ID) -> Self:
        """按身份取回来:引擎读槽,组织成块对象交还.

        取回来的字段是**裸值**:声明 `Attr("标题")` 的字段,`block.title` 是 `"标题"`
        而不是声明对象——声明管的是落点,不管取值.

        返回类型跟着**调用它的那个类**走(`Note.fetch()` 就是 `Note`);调用时若走的
        是基座(`Block.fetch()`),那是"这个身份没有对应的类,降级读回"那条路.
        """
        return cast("Self", engine().load(identity, owner=cls))

    @classmethod
    def find(cls, identity: ID) -> Self | None:
        """按身份找:没有即 ``None``(与 :meth:`fetch` 的分别只在要不要抛错)."""
        current = current_engine()
        if current is None:
            return None
        try:
            return cast("Self", current.load(identity, owner=cls))
        except ObjectNotFoundError:
            return None

    def delete(self) -> bool:
        """摘掉这个块:返回是否确实摘掉了一个."""
        return engine().delete(self.id)

    def __repr__(self) -> str:
        """诊断用:表名与身份."""
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
    """把这根线接到一个引擎上;传 `None` 即解开(测试与批处理用).

    Raises:
        RuntimeError: 想绑的引擎与已经绑着的那一个不是同一个.
    """
    global _BOUND  # noqa: PLW0603 — 这根线本来就是全局的唯一一处
    if instance is not None and _BOUND is not None and _BOUND is not instance:
        raise RuntimeError(
            f"一个进程只接一个引擎：已经绑着 {_BOUND.root}，不能再绑 {instance.root}"
            "（要换就先 bind(None)）"
        )
    _BOUND = instance


def current_engine() -> Engine | None:
    """当前接着的那个引擎;没接即 ``None``."""
    return _BOUND


def engine() -> Engine:
    """取当前接着的那个引擎.

    Raises:
        RuntimeError: 还没接(没装配内核就 `save()` 了).
    """
    if _BOUND is None:
        raise RuntimeError("还没有接上引擎：先装配内核（它会 bind），再 save/fetch")
    return _BOUND


__all__ = [
    "BODY_KEY",
    "CATALOG_FILENAME",
    "SOURCE",
    "Block",
    "Engine",
    "SlotPlacement",
    "bind",
    "content_digest",
    "content_digest_of_body",
    "current_engine",
    "engine",
    "known_tables",
]

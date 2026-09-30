# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""存储引擎：块落成记录、按身份读回、摘块、落盘后发事件。

引擎视角下只有一块盘（设计篇 §7）：写入按 hub 名分组，读取按行里的 hub 名开 hub；
**读路径不建 hub**（目录不在即报错），写路径按需建立 hub（`Hub.create` 幂等）。

一次 :meth:`Storage.store` 落**两条记录**（§3.2.1）：

- **内容记录**：载荷就是 body 字节本身，身份由内容签发，故**同内容只存一份**
  （先按地址反查，已在就不重复写）；
- **块记录**：载荷是指向 body 的**两套凭证**，身份是块自己的；`kind`（类型标号，程序给出）
  写在块那一行的索引里。

两条记录、两行定位、各自提交——**一次写入不是一次事务**。中途崩溃会留下一条没人指向的
内容记录，它无害（既读不出来也没人引用），压实回收是未来项（§12）。这个取舍是刻意的：
把两条记录绑成一次事务要引入跨行事务与崩溃恢复，而当前阶段"孤儿内容"的代价只是空间。

事件在**落盘之后**发出：订阅者看到的永远是已提交状态；通知失败不影响写入
（`Bus.emit` 自己隔离异常并把失败清单交回，引擎不抛）。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from core.event.catalog import BUDGET_EXHAUSTED, OBJECT_DELETED, OBJECT_PUT
from core.event.events import Event
from core.exc import BlockTooLargeError, ObjectNotFoundError

from .format.block import (
    BlockPayload,
    BodyRef,
    Tombstone,
    block_payload_of,
    encode_block_payload,
    encode_tombstone,
)
from .format.id import ID, digest
from .format.record import decode, encode
from .hub import Hub, PackPolicy, Placement
from .registry import REGISTRY, OverBudget, TypeDecl
from .rows import BlockRow, BodyRow

if TYPE_CHECKING:
    from collections.abc import Mapping

    from core.event.bus import Bus

    from .carrier import SlotRange
    from .index import Index

ENGINE_SOURCE = "core.storage"
"""事件来源标识：存储引擎发出的通知都带它。"""


def _place(identity: ID, hub: str, placement: Placement) -> None:
    """把落盘后的物理坐标写回 ID 的位置段。

    "在哪儿"是 ID 自己记的（`in_hub` / `in_hub_pack` / `in_pack_slot`），
    行只是它的镜像——故这条路径是唯一的写入口：坐标先落在 ID 上，再由 ID 搬进索引库。
    """
    identity.in_hub = hub
    identity.in_hub_pack = placement.pack
    identity.in_pack_slot = (placement.span.first, placement.span.last)


def _check_block_size(decl: TypeDecl | None, size: int) -> None:
    """块体积上限的判据：按**载荷**长度判，不把记录头的开销算进去。

    Raises:
        BlockTooLargeError: 载荷超过这个类型声明的上限。**分片尚未接线**，故此刻是拒写。
    """
    if decl is not None and decl.max_block_bytes is not None and size > decl.max_block_bytes:
        raise BlockTooLargeError(
            f"块超出体积上限: 载荷 {size} 字节 > {decl.max_block_bytes}（类型 {decl.table}）"
        )


class Storage:
    """存储引擎：把 body 落成记录，把身份读回 body。

    它持有一个已对齐的索引库与一个 vault 根目录：hub 按名字在这个根下开，
    故"多 hub"对上层只是**一次分组**（§7）。
    """

    def __init__(
        self,
        index: Index,
        root: str | Path,
        *,
        default_hub: str = "main",
        policy: PackPolicy | None = None,
        bus: Bus | None = None,
    ) -> None:
        """接上索引库与库根。

        Args:
            index: 已对齐的索引库（引擎不负责开库与对齐）。
            root: vault 根目录；hub 就是它下面的子目录。
            default_hub: 不指定 hub 时写进哪个 hub。
            policy: 写载体的策略（槽长与封口线）；不给即用默认。
            bus: 事件总线；不给则不发事件（测试与批处理常常不需要）。
        """
        self._index = index
        self._root = Path(root)
        self._default_hub = default_hub
        self._policy = PackPolicy() if policy is None else policy
        self._bus = bus

    @property
    def index(self) -> Index:
        """接上的索引库。"""
        return self._index

    @property
    def root(self) -> Path:
        """Vault 根目录。"""
        return self._root

    @property
    def default_hub(self) -> str:
        """默认 hub 名。"""
        return self._default_hub

    def store(
        self,
        data: bytes,
        *,
        hub: str | None = None,
        kind: str = "",
        attrs: Mapping[str, object] | None = None,
    ) -> ID:
        """把一个 body 落盘，返回**块身份**。

        `data` 是**已经规范化过的字节**：引擎不理解载荷结构，只负责落成记录
        （规范化属编码与领域，见 §4.3）。`kind` 是类型标号，程序给出、不落进记录头；
        `attrs` 是块自己的属性，编进**块记录载荷**——不进 body（那是大头内容、按地址
        去重），也不靠库里的列承载（库只是索引）。

        **写进哪个 hub、受不受配额约束，都看类型声明**：`kind` 就是表名，拿它反查
        `TypeDecl`（`__own_hub__` / `__hub__` / `__pack_budget__` / `__over_budget__` /
        `__max_block_*__`）。`hub` 参数是调用方的显式点名，优先于声明。

        **块身份随载荷**：同一份 body 配上不同的属性就是两个块；body 那侧仍按内容去重，
        故"同内容不同属性"只多一条块记录，内容面还是那一份。

        Raises:
            BlockTooLargeError: 载荷超过该类型声明的单块上限。
            BudgetExhaustedError: 配额用完，且该类型的档位声明为 `deny`。

        Returns:
            块身份：分配形态凭证新建，摘要形态凭证是块记录载荷的摘要。
        """
        decl = REGISTRY.table(kind) if kind else None
        target = self._hub(self._hub_name(decl, hub), create=True)
        content = ID.of(data)
        existing = self._index.rows.bodies_by_hash(content.value_hash)
        if existing:
            # 同内容只存一份：复用已落盘那份 body 的身份，块指针因此指向它
            body_id = ID(
                value_uuid=existing[0].value_uuid,
                value_hash=existing[0].value_hash,
                birth_time=existing[0].birth_time,
            )
        else:
            self._write_body(target, content, data, decl=decl)
            body_id = content
        pointer = encode_block_payload(
            BodyRef(value_uuid=body_id.value_uuid, value_hash=body_id.value_hash), attrs
        )
        block = ID.of(pointer)
        self._write_block(target, block, pointer, kind=kind, body=body_id, decl=decl)
        self._emit(OBJECT_PUT, block.value_uuid, {"body": body_id.value_hash, "kind": kind})
        return block

    def load(self, value_uuid: str) -> bytes:
        """按身份读回 body：**块身份与内容身份都收**。

        块身份顺着行里的指针跳一跳；内容身份本身就是 body。判据是"这张表里有没有这一行"，
        不靠载荷猜（§3.2.1）。

        Raises:
            ObjectNotFoundError: 两张表里都没有这一行，或它指向的内容读不出来。
        """
        block = self._index.rows.block(value_uuid)
        if block is not None:
            return self.body(block.body_value_hash)
        body = self._index.rows.body(value_uuid)
        if body is None:
            raise ObjectNotFoundError(f"对象不在索引里: {value_uuid}")
        return self._read_payload(body.in_hub, body.in_hub_pack, body.span)

    def body(self, address: str) -> bytes:
        """按内容地址读回 body。

        找到行之后还要**当场核对摘要**：行指向的位置上若是另一份内容，说明这份地址对应的
        字节已经没了——宁可报"内容不在"，也不能把错的内容当成对的返回。

        Raises:
            ObjectNotFoundError: 没有哪一行指向这份内容。
        """
        for row in self._index.rows.bodies_by_hash(address):
            payload = self._read_payload(row.in_hub, row.in_hub_pack, row.span)
            if digest(payload) == address:
                return payload
        raise ObjectNotFoundError(f"内容不在: {address}")

    def drop(self, value_uuid: str) -> bool:
        """删掉一个块：**先留墓碑，再摘索引行**；返回是否确实删掉了一个。

        载体是追加写，旧字节删不掉，所以删除的落法是一条**墓碑记录**（指向被删记录的位置）。
        巡检认识墓碑，不会再把被删的那条记录报成"盘上有、库里没行"。

        顺序不能反：先摘行、后写墓碑的话，中途失败就留下一条盘上有、库里没行的块，
        巡检会把它当缺行补回来（等于撤销这次删除）。先写墓碑，中途失败最多多一条指着
        空处的墓碑——无害，也不影响任何一次巡检。

        **内容面不动**（等压实回收）：同内容可能还有别的块在用，删内容要判引用。
        """
        block = self._index.rows.block(value_uuid)
        if block is None:
            return False
        self._write_tombstone(block)
        if not self._index.rows.drop_block(value_uuid):
            return False
        self._emit(OBJECT_DELETED, value_uuid)
        return True

    def _write_tombstone(self, block: BlockRow) -> None:
        """在被删记录所在的 hub 里追加一条墓碑。

        墓碑**不带归属**：它是内核自己的机制，不占任何类型的配额——否则"删得多"会挤掉
        "写得多"的额度，两件事不该互相牵连。

        它**不进索引**：索引里不该有它的行（它在盘上，顺扫即得），故位置段也不写回它。
        """
        payload = encode_tombstone(
            Tombstone(
                value_uuid=block.value_uuid,
                value_hash=block.value_hash,
                hub=block.in_hub,
                pack=block.in_hub_pack,
                span=(block.in_pack_slot[0], block.in_pack_slot[1]),
            )
        )
        hub = self._hub(block.in_hub, create=False)
        hub.append(encode(ID.of(payload), payload))

    def locate(self, value_uuid: str) -> BlockRow | None:
        """按身份取块那一行（诊断用；读数据走 :meth:`load`）。"""
        return self._index.rows.block(value_uuid)

    def block_payload(self, value_uuid: str) -> BlockPayload | None:
        """按**块身份**取块记录的两部分（body 指针与属性）；没有这一块即 ``None``。

        读数据走 :meth:`load`、读位置走 :meth:`locate`，读块自己声明的属性走这里。
        属性与指针同处一层载荷，故顺扫可还原——库里没有它的列，也不需要有。
        """
        block = self._index.rows.block(value_uuid)
        if block is None:
            return None
        payload = self._read_payload(block.in_hub, block.in_hub_pack, block.span)
        return block_payload_of(payload)

    def _hub(self, name: str, *, create: bool) -> Hub:
        """按名开 hub：写路径按需建立**并登记**，读路径一律不建。

        建了就登记：目录是 hub 的存在证明，登记是它的投影（§6）。写路径留下的 hub 若不登记，
        巡检每次都要报一处"登记缺"——那不是发现，是引擎自己欠的账。登记只认第一次，故这句幂等。
        """
        directory = self._root / name
        if not create:
            return Hub(
                directory, slot_bytes=self._policy.slot_bytes, max_bytes=self._policy.max_bytes
            )
        created = Hub.create(
            directory, slot_bytes=self._policy.slot_bytes, max_bytes=self._policy.max_bytes
        )
        self._index.rows.register_hub(name)
        return created

    def _hub_name(self, decl: TypeDecl | None, explicit: str | None) -> str:
        """这一次写进哪个 hub：调用方点名 > 类型声明（独占 / 指定）> 默认。"""
        if explicit is not None:
            return explicit
        if decl is None:
            return self._default_hub
        return decl.hub_name(self._default_hub)

    def _append_record(
        self, target: Hub, raw: bytes, *, owner: str, decl: TypeDecl | None
    ) -> Placement:
        """把一条记录落到载体上：先判配额，再交给 hub 挑位置。

        配额只管"**还许不许再开一份载体**"（`allow_new_pack`）：还有地方写就照写，
        真到了要新开一份时才按档位处置。
        """
        allow_new_pack = True
        if decl is not None and decl.pack_budget is not None:
            used = len(target.packs_by_owner(owner))
            if used >= decl.pack_budget:
                allow_new_pack = self._over_budget(decl, owner)
        return target.append(raw, owner=owner, allow_new_pack=allow_new_pack)

    def _over_budget(self, decl: TypeDecl, owner: str) -> bool:
        """配额用满之后怎么办：返回"还许不许再开一份载体"。

        `deny` 不许（真到要新开时由载体层抛错）、`notify` 先发一条通知再放行、`extend` 静默放行。
        """
        if decl.over_budget is OverBudget.DENY:
            return False
        if decl.over_budget is OverBudget.NOTIFY:
            self._emit(BUDGET_EXHAUSTED, owner, {"budget": decl.pack_budget})
        return True

    def _write_body(self, target: Hub, body: ID, data: bytes, *, decl: TypeDecl | None) -> None:
        """写内容记录，并把它落成一条内容行。"""
        owner = "" if decl is None else decl.table
        _check_block_size(decl, len(data))
        raw = encode(body, data)
        placement: Placement = self._append_record(target, raw, owner=owner, decl=decl)
        _place(body, target.name, placement)
        self._index.rows.put_body(
            BodyRow(
                name=body.name,
                value_uuid=body.value_uuid,
                value_hash=body.value_hash,
                birth_time=body.birth_time,
                in_hub=body.in_hub,
                in_hub_pack=body.in_hub_pack,
                in_pack_slot=body.in_pack_slot,
            )
        )

    def _write_block(  # noqa: PLR0913 — 一条记录要的那些东西，散开比收成结构体直白
        self,
        target: Hub,
        block: ID,
        payload: bytes,
        *,
        kind: str,
        body: ID,
        decl: TypeDecl | None,
    ) -> None:
        """写块记录，并把它落成一条块行（指针落成两列）。

        类型标号**写进记录本身**（`encode(..., kind=…)`），索引那一列是它的投影：
        否则索引一重扫，全库的块就不知道自己是什么类型。
        """
        owner = "" if decl is None else decl.table
        _check_block_size(decl, len(payload))
        raw = encode(block, payload, kind=kind)
        placement: Placement = self._append_record(target, raw, owner=owner, decl=decl)
        _place(block, target.name, placement)
        self._index.rows.put_block(
            BlockRow(
                name=block.name,
                value_uuid=block.value_uuid,
                value_hash=block.value_hash,
                birth_time=block.birth_time,
                in_hub=block.in_hub,
                in_hub_pack=block.in_hub_pack,
                in_pack_slot=block.in_pack_slot,
                body_value_uuid=body.value_uuid,
                body_value_hash=body.value_hash,
                kind=kind,
            )
        )

    def _read_payload(self, hub: str, pack: str, span: SlotRange) -> bytes:
        """按位置读回记录载荷（槽长从载体文件头读）。"""
        target = self._hub(hub, create=False)
        return decode(target.read(Placement(pack=pack, span=span))).payload

    def _emit(self, event_type: str, subject: str, data: object = None) -> None:
        """落盘之后发通知；不是通知就什么都不做。"""
        if self._bus is None:
            return
        self._bus.emit(Event(type=event_type, source=ENGINE_SOURCE, subject=subject, data=data))


__all__ = ["ENGINE_SOURCE", "Storage"]

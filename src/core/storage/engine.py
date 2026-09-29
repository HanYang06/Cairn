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

from core.clock import now_ms
from core.event.bus import Bus
from core.event.catalog import OBJECT_DELETED, OBJECT_PUT
from core.event.events import Event
from core.exc import ObjectNotFoundError

from .carrier import SlotRange
from .format.block import BodyRef, encode_block_payload
from .format.id import ID, digest
from .format.record import decode, encode
from .hub import Hub, PackPolicy, Placement
from .rows import BlockRow, BodyRow

if TYPE_CHECKING:
    from core.event.bus import Bus

    from .index import Index

ENGINE_SOURCE = "core.storage"
"""事件来源标识：存储引擎发出的通知都带它。"""


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

    def store(self, data: bytes, *, hub: str | None = None, kind: str = "") -> ID:
        """把一个 body 落盘，返回**块身份**。

        `data` 是**已经规范化过的字节**：引擎不理解载荷结构，只负责落成记录
        （规范化属编码与领域，见 §4.3）。`kind` 是类型标号，程序给出、不落进记录头。

        Returns:
            块身份：分配形态凭证新建，摘要形态凭证是块记录载荷的摘要。
        """
        target = self._hub(self._default_hub if hub is None else hub, create=True)
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
            self._write_body(target, content, data)
            body_id = content
        pointer = encode_block_payload(
            BodyRef(value_uuid=body_id.value_uuid, value_hash=body_id.value_hash)
        )
        block = ID.of(pointer)
        self._write_block(target, block, pointer, kind=kind, body=body_id)
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
        return self._read_payload(body.hub, body.pack, body.span)

    def body(self, address: str) -> bytes:
        """按内容地址读回 body。

        找到行之后还要**当场核对摘要**：行指向的位置上若是另一份内容，说明这份地址对应的
        字节已经没了——宁可报"内容不在"，也不能把错的内容当成对的返回。

        Raises:
            ObjectNotFoundError: 没有哪一行指向这份内容。
        """
        for row in self._index.rows.bodies_by_hash(address):
            payload = self._read_payload(row.hub, row.pack, row.span)
            if digest(payload) == address:
                return payload
        raise ObjectNotFoundError(f"内容不在: {address}")

    def drop(self, value_uuid: str) -> bool:
        """摘掉块那一行，返回是否确实摘掉了一行。

        **内容面不动**（等压实回收，§12）：同内容可能还有别的块在用，删内容要判引用。
        """
        if not self._index.rows.drop_block(value_uuid):
            return False
        self._emit(OBJECT_DELETED, value_uuid)
        return True

    def locate(self, value_uuid: str) -> BlockRow | None:
        """按身份取块那一行（诊断用；读数据走 :meth:`load`）。"""
        return self._index.rows.block(value_uuid)

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

    def _write_body(self, target: Hub, body: ID, data: bytes) -> None:
        """写内容记录，并把它落成一条内容行。"""
        raw = encode(body, data)
        placement: Placement = target.append(raw)
        stamp = now_ms()
        self._index.rows.put_body(
            BodyRow(
                value_uuid=body.value_uuid,
                value_hash=body.value_hash,
                hub=target.name,
                pack=placement.pack,
                span=placement.span,
                size=len(raw),
                birth_time=body.birth_time,
                created=stamp,
                updated=stamp,
            )
        )

    def _write_block(self, target: Hub, block: ID, payload: bytes, *, kind: str, body: ID) -> None:
        """写块记录，并把它落成一条块行（指针落成两列）。"""
        raw = encode(block, payload)
        placement: Placement = target.append(raw)
        stamp = now_ms()
        self._index.rows.put_block(
            BlockRow(
                value_uuid=block.value_uuid,
                value_hash=block.value_hash,
                body_value_uuid=body.value_uuid,
                body_value_hash=body.value_hash,
                hub=target.name,
                pack=placement.pack,
                span=placement.span,
                size=len(raw),
                kind=kind,
                birth_time=block.birth_time,
                created=stamp,
                updated=stamp,
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


__all__ = ["ENGINE_SOURCE", "SlotRange", "Storage"]

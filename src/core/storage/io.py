# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""载体文件：**追加写**的载体，读 / 写 / 顺扫。

设计见 `docs/architecture/storage-design.md` §5。职责边界：

- 这一层只管"一个文件 + 一串记录"：写文件头、追加记录、按槽区间读、顺扫重建；
- **不认识桶、目录、索引、事务**——那些归上层（第 2、3 阶段）。

写入纪律（与现有 `Bucket._append` 一致）：写完 `flush` + `fsync`，
**先落字节、后记目录**，故目录指向的位置必然已经存在；反过来只会留下空洞，不会读到半条。

顺扫是"库可重建"的落点（§8.5 档一）：记录自框定，故顺着文件读一遍就能还原
全部 ``(Id, 载荷)``，不依赖任何索引。坏点即停并**显式报错**，不跳过、不猜。
"""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import TYPE_CHECKING

from core.types import CairnError, RecordFormatError, SlotError, SlotRange

from .carrier import CARRIER_HEADER_BYTES, CarrierLayout
from .record import Record

if TYPE_CHECKING:
    from collections.abc import Iterator

_LEN_FIELD = struct.Struct(">I")


def _configured_slot_bytes() -> int:
    """向配置要槽长（建载体时的默认）。

    **先引入声明模块再取值**：配置引擎按"谁声明谁报到"工作，没导入过的声明它不认识；
    在别处引用本模块时，声明未必已经报到。延迟导入同时避免存储地基在加载期拉起引擎。
    """
    from . import conf as _declared  # noqa: PLC0415 — 先让声明报到

    slot_bytes: int = _declared.conf.pack_slot_bytes
    return slot_bytes


class CarrierFile:
    """一个载体文件（``packs/`` 下的一个文件）。"""

    def __init__(self, path: Path, layout: CarrierLayout) -> None:
        self.path = path
        self.layout = layout

    # ---- 生命周期 ----
    @classmethod
    def create(cls, path: Path | str, slot_bytes: int | None = None) -> CarrierFile:
        """新建载体：写入文件头（魔数 + 槽长 + 预留零）。

        槽长在**文件头里落定**，故载体自描述：只拿到这一个文件也能算偏移。

        ``slot_bytes`` 不给时向配置要（``storage.pack.slot_bytes``）：**配置只在建的这一刻读一次**，
        此后一律从文件头读——否则改一次配置，已落盘的载体就全被解释成另一个布局。
        允许显式传参，是为了"按指定布局造一个载体"（迁移、压实、测试）。
        """
        target = Path(path)
        layout = CarrierLayout(
            slot_bytes=slot_bytes if slot_bytes is not None else _configured_slot_bytes()
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as handle:
            handle.write(layout.encode_header())
            handle.flush()
            os.fsync(handle.fileno())
        return cls(target, layout)

    @classmethod
    def open(cls, path: Path | str) -> CarrierFile:
        """打开已有载体并读回它的槽长。"""
        target = Path(path)
        with target.open("rb") as handle:
            raw = handle.read(CARRIER_HEADER_BYTES)
        return cls(target, CarrierLayout.decode_header(raw))

    # ---- 只读视图 ----
    @property
    def used_bytes(self) -> int:
        """已用字节数（文件头之后的部分）——即全部记录的总长之和。"""
        return self.path.stat().st_size - self.layout.header_bytes

    @property
    def slot_count(self) -> int:
        """已占用的槽数（由字节数算出，不额外记账）。"""
        used = self.used_bytes
        if used <= 0:
            return 0
        return -(-used // self.layout.slot_bytes)

    # ---- 写 ----
    def append(self, record: Record) -> SlotRange:
        """把一条记录追加到载体末尾，返回它占用的槽区间。

        返回的槽区间**由实际写入位置算出**（不是调用方给的）：
        调用方拿它填索引库，故库里的位置永远与文件一致。
        """
        raw = record.encode()
        offset = self.path.stat().st_size - self.layout.header_bytes
        if offset < 0:
            raise CairnError(f"载体文件头缺失: {self.path}")
        span = self.layout.span_of(self.layout.header_bytes + offset, len(raw))
        with self.path.open("ab") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        return span

    # ---- 读 ----
    def read(self, span: SlotRange) -> bytes:
        """按槽区间读回**一条记录**的原始字节。

        长度不写在索引里：槽数给出上界，再由记录头里的总长收敛到精确长度。
        起点取 ``offset_of_span``（含槽内偏移），否则同槽记录会读串。
        """
        if span.count < 1:
            raise SlotError(f"槽区间非法: {span}")
        upper = span.count * self.layout.slot_bytes
        start = self.layout.offset_of_span(span)
        with self.path.open("rb") as handle:
            handle.seek(start)
            buffered = handle.read(upper)
        if len(buffered) < _LEN_FIELD.size:
            raise RecordFormatError(f"记录读取不足: {self.path} @ 槽 {span.start}")
        (total_len,) = _LEN_FIELD.unpack(buffered[: _LEN_FIELD.size])
        if total_len > len(buffered):
            raise RecordFormatError(
                f"记录超出声明槽数: 声明 {total_len} 字节，槽区间只容 {len(buffered)}"
            )
        return buffered[:total_len]

    def scan(self) -> Iterator[Record]:
        """顺扫全部记录（重建的入口）。

        每条由头里的总长自框定；文件尾若残留不足一条的字节，
        说明载体被截断，**报错而不是静默丢弃**。
        """
        offset = 0
        limit = self.used_bytes
        with self.path.open("rb") as handle:
            handle.seek(self.layout.header_bytes)
            while offset < limit:
                head = handle.read(_LEN_FIELD.size)
                if len(head) < _LEN_FIELD.size:
                    raise RecordFormatError(f"载体尾部截断: {self.path} @ 偏移 {offset}")
                (total_len,) = _LEN_FIELD.unpack(head)
                rest = handle.read(total_len - _LEN_FIELD.size)
                if len(rest) != total_len - _LEN_FIELD.size:
                    raise RecordFormatError(
                        f"载体尾部截断: {self.path} @ 偏移 {offset}（声明 {total_len} 字节）"
                    )
                yield Record.decode(head + rest, self.layout)
                offset += total_len


__all__ = ["CarrierFile"]

# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""载体（pack）的**槽布局**：定长槽与字节偏移的算术互推。

设计见 `docs/architecture/storage-design.md` §5。要点：

- **槽长随载体走**：文件头里写死 ``slot_bytes``，故载体自描述、可独立定位（§5.6）；
- **槽是记账与定位单位**，不是写入对齐单位：记录紧接前一条连续写入，
  只有"起始槽"取整到槽边界（§5.2）；
- 于是**物理坐标算得出来、不用枚举**：槽 n 的偏移 = 文件头长 + n × 槽长；
- 槽区间只是投影：压缩 / 合并只改映射，不改记录本身（§9.2）。

本模块只有纯计算与文件头编解码，**不碰记录体、不碰 IO**（那是 `record` 与 `io` 的事）。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from core.types import RecordFormatError, SlotError, SlotRange

CARRIER_MAGIC = b"CAIRNPK1"
"""载体文件头的魔数（8 字节）：认得出"这是个载体、且是第 1 版布局"。"""

_BYTES_FIELD = struct.Struct(">Q")
"""8 字节无符号：槽长字段。"""

_RESERVED_BYTES = 8
"""文件头预留字节（置零）：将来加字段不必改已有布局。"""

MIN_SLOT_BYTES = 1
"""槽长下限：至少 1 字节。"""

CARRIER_HEADER_BYTES = len(CARRIER_MAGIC) + _BYTES_FIELD.size + _RESERVED_BYTES
"""文件头定长长度。"""

MAX_SLOT_BYTES = (1 << 64) - 1
"""槽长上限：受 8 字节字段约束。"""


def slots_for(length: int, slot_bytes: int) -> int:
    """占用 ``length`` 字节需要多少个槽（向上取整，至少 1 个）。"""
    if length < 0:
        raise SlotError(f"长度非法: {length}")
    if slot_bytes < MIN_SLOT_BYTES:
        raise SlotError(f"槽长非法: {slot_bytes}")
    return max(1, -(-length // slot_bytes))


def slot_offset(slot: int, slot_bytes: int) -> int:
    """第 ``slot`` 个槽的字节偏移（**相对载体起点**，即文件头之后）。"""
    if slot < 0:
        raise SlotError(f"槽号非法: {slot}")
    if slot_bytes < MIN_SLOT_BYTES:
        raise SlotError(f"槽长非法: {slot_bytes}")
    return slot * slot_bytes


def slot_span(offset: int, length: int, slot_bytes: int) -> SlotRange:
    """一段字节落进哪些槽：起点**向下取整**到槽边界，槽内偏移留在 ``head``。

    这是唯一的"字节 → 槽"入口：**槽区间由偏移算出，不由写入方指定**。
    ``head`` 必须留下：只给 (起始槽, 槽数) 会丢掉槽内偏移，
    两条同槽记录的区间将无法区分，读写随即错位。

    槽数**必须把 ``head`` 算进去**：区间要盖住 ``[offset, offset + length)``，
    起点取了整之后末字节落在 ``(head + length - 1) // 槽长`` 号槽里，
    故跨度是 ``ceil((head + length) / 槽长)``。只按 ``length`` 取整会少算：
    ``offset=1``、``length=4``、槽长 4 时字节落在 ``[1, 5)``，横跨第 0、1 两槽，
    而 ``ceil(4 / 4)`` 只报 1 槽。

    这与 :func:`slots_for` 是**两套口径，不可混用**：``slots_for`` 算的是"起点落在槽边界"
    时的槽数（记录头自检用它），本函数算的是**实际占用**（进索引的 ``slot_count``）。
    记录起点不落槽边界时两者本来就不等，谁都没错——上一轮评审把这两件事混成一个数，
    故在此写明。
    """
    if offset < 0:
        raise SlotError(f"偏移非法: {offset}")
    if length < 0:
        raise SlotError(f"长度非法: {length}")
    if slot_bytes < MIN_SLOT_BYTES:
        raise SlotError(f"槽长非法: {slot_bytes}")
    start, head = divmod(offset, slot_bytes)
    return SlotRange(start, max(1, -(-(head + length) // slot_bytes)), head)


@dataclass(frozen=True, slots=True)
class CarrierLayout:
    """一个载体的槽布局：槽长固定，文件头定长。

    槽长由**载体文件头**给出（不是全局配置），故不同批次的载体可以不同槽长，
    而每个载体自身仍可精确算术定位。
    """

    slot_bytes: int
    header_bytes: int = CARRIER_HEADER_BYTES

    def __post_init__(self) -> None:
        """校验槽长与头长：槽长必须为正、头长必须足够容纳文件头。"""
        if not MIN_SLOT_BYTES <= self.slot_bytes <= MAX_SLOT_BYTES:
            raise SlotError(f"槽长非法: {self.slot_bytes}")
        if self.header_bytes < CARRIER_HEADER_BYTES:
            raise SlotError(f"文件头长度非法: {self.header_bytes}")

    def offset_of(self, slot: int) -> int:
        """槽号 → 绝对字节偏移（含文件头）；槽内偏移请用 :meth:`offset_of_span`。"""
        return self.header_bytes + slot_offset(slot, self.slot_bytes)

    def offset_of_span(self, span: SlotRange) -> int:
        """槽区间 → 绝对字节偏移（含文件头与槽内偏移）。

        与 :meth:`span_of` 互为逆运算，这是"位置可无损往返"的保证。
        """
        return self.header_bytes + slot_offset(span.start, self.slot_bytes) + span.head

    def span_of(self, offset: int, length: int) -> SlotRange:
        """绝对字节偏移 → 槽区间（先减去文件头长度）。"""
        relative = offset - self.header_bytes
        if relative < 0:
            raise SlotError(f"偏移非法: {offset}")
        return slot_span(relative, length, self.slot_bytes)

    def record_bytes(self, slot_count: int) -> int:
        """占 ``slot_count`` 个槽的记录，最少需要多少字节（**槽对齐起点**下的下界）。

        下界：起点落在槽边界时，记录必须越出前 ``slot_count - 1`` 个槽，故至少
        ``(slot_count - 1) × 槽长 + 1``。用于校验头里声明的槽数与长度是否自洽。
        起点偏在槽内的记录**不适用**这条下界（那时槽数由 :func:`slot_span` 给出）。
        """
        if slot_count < 1:
            raise SlotError(f"槽数非法: {slot_count}")
        return (slot_count - 1) * self.slot_bytes + 1

    def encode_header(self) -> bytes:
        """编码载体文件头：魔数 + 槽长 + 预留零。"""
        return CARRIER_MAGIC + _BYTES_FIELD.pack(self.slot_bytes) + b"\x00" * _RESERVED_BYTES

    @classmethod
    def decode_header(cls, raw: bytes) -> CarrierLayout:
        """解码载体文件头；魔数不符或长度不足即抛 ``RecordFormatError``。

        认不出来就**不猜**：静默按默认槽长继续读，会把"这不是载体"伪装成"载体空"。
        """
        if len(raw) < CARRIER_HEADER_BYTES:
            raise RecordFormatError(f"载体文件头长度不足: {len(raw)} < {CARRIER_HEADER_BYTES}")
        if raw[: len(CARRIER_MAGIC)] != CARRIER_MAGIC:
            raise RecordFormatError(f"载体魔数不符: {raw[: len(CARRIER_MAGIC)]!r}")
        start = len(CARRIER_MAGIC)
        (slot_bytes,) = _BYTES_FIELD.unpack(raw[start : start + _BYTES_FIELD.size])
        if not MIN_SLOT_BYTES <= slot_bytes <= MAX_SLOT_BYTES:
            raise RecordFormatError(f"载体槽长非法: {slot_bytes}")
        return cls(slot_bytes=slot_bytes)


__all__ = [
    "CARRIER_HEADER_BYTES",
    "CARRIER_MAGIC",
    "MAX_SLOT_BYTES",
    "MIN_SLOT_BYTES",
    "CarrierLayout",
    "slot_offset",
    "slot_span",
    "slots_for",
]

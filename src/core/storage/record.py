# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""载体中的**一条记录**：定长头 + ID 段 + 载荷，自框定、自校验、自描述。

设计见 `docs/architecture/storage-design.md` §5.3。布局（长度均指字节）::

    +----------------+------------------+---------------------+----------------+
    | total_len (4)  | checksum (64)    | id (canonical CBOR) | payload (rest) |
    +----------------+------------------+---------------------+----------------+
     大端无符号        摘要十六进制        落盘子集，长度由编码自报   记录内容

四条约定：

1. **总长在最前**（定长 4 字节）：故记录**自框定**——顺着文件扫就能切出每一条，
   不需要索引库（§5.4、§8.5 档一）。
2. **ID 段取落盘子集**（`Id.record`）：只含身份与定位必需项（§3.5）。
3. **校验和覆盖载荷**：它与载荷的摘要凭证同源，故一次比较同时验"读到的是不是原文"
   与"ID 声明的内容与实际内容是否一致"（§5.3）。
4. **类型标号不落盘**：记录里没有类型字段，类型由程序按 ID 给出（§3.3 第 4、5 条）。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from io import BytesIO

import cbor2

from core.types import (
    CorruptObjectError,
    Id,
    InvalidIdError,
    RecordFormatError,
    SlotError,
    SlotRange,
    ValueHash,
)

from .carrier import CarrierLayout, slots_for

_LEN_FIELD = struct.Struct(">I")
"""4 字节大端无符号：记录总长。"""

_CHECKSUM_BYTES = 64
"""摘要凭证的十六进制长度（32 字节摘要）。"""

_HEADER_BYTES = _LEN_FIELD.size + _CHECKSUM_BYTES
"""定长头部长度：总长字段 + 摘要字段。"""


def encode_id_segment(record_id: Id) -> bytes:
    """把 ID 的落盘子集编成确定性 CBOR（同一 ID 恒得同一字节）。"""
    return cbor2.dumps(record_id.record(), canonical=True)


@dataclass(frozen=True, slots=True)
class RecordHeader:
    """记录头四项：总长、校验和、ID（两套凭证）、槽数。

    **落盘的只有长度与摘要**（外加 ID 段与载荷，见 :meth:`Record.encode`）；
    身份与槽数是从字节派生的，不进文件，用来做自校验。

    ``aligned_slots`` 是**槽对齐约定**下的槽数：假定记录起点落在槽边界，
    装下 ``total_len`` 需要几个槽。它**不是**记录在载体里的实际占用——起点偏在槽内时，
    实际跨槽数由 :meth:`Record.span` 给出，也就是索引行的 ``slot_count`` 列。两者可以不等
    （槽长 4、``offset=1``、``total_len=4``：本字段 1，实际 2）。

    名字刻意不叫 ``slot_count``：同一个名字在两处指两个数，正是上一轮评审指出的坑。
    """

    total_len: int
    checksum: ValueHash
    id: Id
    aligned_slots: int

    def __post_init__(self) -> None:
        """校验：总长至少能装下头与一字节载荷、槽数至少为 1。"""
        if self.total_len < _HEADER_BYTES + 1:
            raise RecordFormatError(f"记录总长过小: {self.total_len}")
        if self.aligned_slots < 1:
            raise SlotError(f"记录槽数非法: {self.aligned_slots}")

    def verify(self, layout: CarrierLayout) -> None:
        """与载体布局对账：**槽对齐约定**下声明的槽数与长度必须自洽。

        两个方向都核：长度不得超出声明槽数所容，也不得小到占不满声明槽数。
        这套判据是给**手工构造**的记录头把关（槽数由 :func:`slots_for` 推出时它恒真）；
        实际占用装不装得下在**读**那一侧核——`CarrierFile.read` 拿得到记录落在槽内的位置。
        """
        if self.total_len > layout.slot_bytes * self.aligned_slots:
            raise SlotError(
                f"记录超出声明槽数: {self.total_len} 字节 > {self.aligned_slots} 槽"
                f"（槽长 {layout.slot_bytes}）"
            )
        if self.total_len < layout.record_bytes(self.aligned_slots):
            raise SlotError(
                f"记录不足以占用声明槽数: {self.total_len} 字节 < "
                f"{layout.record_bytes(self.aligned_slots)}"
            )


@dataclass(frozen=True, slots=True)
class Record:
    """一条记录：ID（身份与定位）+ 载荷（内容字节）。

    块记录与内容记录是**同一种记录**，区别只在 ``value_hash`` 指向谁：
    块记录指向其内容，内容记录的 ``value_hash`` 就是它自己的摘要。
    """

    id: Id
    payload: bytes

    @property
    def checksum(self) -> ValueHash:
        """载荷的摘要凭证（与 :attr:`Id.value_hash` 同源）。"""
        return ValueHash.of(self.payload)

    @property
    def total_len(self) -> int:
        """本记录的总字节数（定长头 + ID 段 + 载荷），由内容推出。"""
        return _HEADER_BYTES + len(encode_id_segment(self.id)) + len(self.payload)

    def encode(self) -> bytes:
        """编码为落盘字节：定长头 + ID 段 + 载荷。"""
        head = _LEN_FIELD.pack(self.total_len) + str(self.checksum).encode("ascii")
        return head + encode_id_segment(self.id) + self.payload

    def header(self, slot_bytes: int) -> RecordHeader:
        """算出头四项（总长与槽数都从实际字节推出，不由调用方给）。

        槽数是**槽对齐约定**下的值，不是实际占用；要看实际占用得给出记录在载体里的偏移，
        见 :meth:`span`。
        """
        total_len = self.total_len
        return RecordHeader(
            total_len=total_len,
            checksum=self.checksum,
            id=self.id,
            aligned_slots=slots_for(total_len, slot_bytes),
        )

    def span(self, layout: CarrierLayout, *, offset: int = 0) -> SlotRange:
        """本条记录在载体中的槽区间；``offset`` 为它在文件里的相对偏移。"""
        return layout.span_of(layout.header_bytes + offset, self.total_len)

    @classmethod
    def create(cls, record_id: Id, payload: bytes, slot_bytes: int) -> Record:
        """造一条记录，并按**槽对齐约定**自检一次槽算术。

        把"长度与槽数对不上"挡在落盘之前；实际占用的核对在读那一侧
        （`CarrierFile.read` 拿得到记录落在槽内的位置，见 :meth:`header`）。
        """
        record = cls(id=record_id, payload=bytes(payload))
        record.header(slot_bytes).verify(CarrierLayout(slot_bytes=slot_bytes))
        return record

    @classmethod
    def decode(cls, raw: bytes, layout: CarrierLayout | None = None) -> Record:
        """解码**恰好一条**记录；``raw`` 必须正好是这一条的字节。

        失败一律**显式抛出**：长度不足、总长与实长不符、ID 段解不出、载荷摘要不符，
        各报各的错，不静默返回半条记录。
        """
        if len(raw) < _HEADER_BYTES + 1:
            raise RecordFormatError(f"记录长度不足: {len(raw)} < {_HEADER_BYTES + 1}")
        (declared_len,) = _LEN_FIELD.unpack(raw[: _LEN_FIELD.size])
        if declared_len != len(raw):
            raise RecordFormatError(f"记录总长与实际不符: 声明 {declared_len}，实际 {len(raw)}")
        checksum_raw = raw[_LEN_FIELD.size : _HEADER_BYTES]
        try:
            checksum = ValueHash.parse(checksum_raw.decode("ascii"))
        except (UnicodeDecodeError, InvalidIdError) as exc:
            raise RecordFormatError(f"记录摘要字段非法: {checksum_raw!r}") from exc
        id_start = _HEADER_BYTES
        payload_start = _payload_start(raw, id_start, declared_len)
        try:
            raw_map = cbor2.loads(raw[id_start:payload_start])
        except Exception as exc:
            raise RecordFormatError("记录 ID 段解码失败") from exc
        if not isinstance(raw_map, dict):
            raise RecordFormatError(f"记录 ID 段不是映射: {type(raw_map).__name__}")
        try:
            record_id = Id.from_record(raw_map)
        except InvalidIdError as exc:
            raise RecordFormatError(f"记录 ID 段字段非法: {exc}") from exc
        payload = raw[payload_start:]
        actual = ValueHash.of(payload)
        if actual != checksum:
            raise CorruptObjectError(f"记录校验失败: 声明 {checksum}，实际 {actual}")
        if record_id.value_hash != checksum:
            raise CorruptObjectError(
                f"记录内容与身份不符: ID 声明 {record_id.value_hash}，实际 {actual}"
            )
        record = cls(id=record_id, payload=payload)
        if layout is not None:
            RecordHeader(
                total_len=declared_len,
                checksum=checksum,
                id=record_id,
                aligned_slots=slots_for(declared_len, layout.slot_bytes),
            ).verify(layout)
        return record

    def __eq__(self, other: object) -> bool:
        """相等性只看**身份与载荷**：总长是派生值，不参与比较。"""
        if not isinstance(other, Record):
            return NotImplemented
        return self.id == other.id and self.payload == other.payload

    def __hash__(self) -> int:
        """按身份与载荷求哈希（与 :meth:`__eq__` 同一口径）。"""
        return hash((self.id, self.payload))


def _payload_start(raw: bytes, start: int, total_len: int) -> int:
    """找出载荷起点：让 CBOR 解码器自报 ID 段读了多少字节。

    不手写"扫到某个字节为止"的启发式——ID 段长度由编码本身给出，
    这样将来加减字段都不会让解析器错位。
    """
    stream = BytesIO(raw[start:total_len])
    decoder = cbor2.CBORDecoder(stream)
    try:
        decoder.decode()
    except Exception as exc:
        raise RecordFormatError("记录 ID 段无法定位") from exc
    consumed = stream.tell()
    if consumed <= 0 or start + consumed > total_len:
        raise RecordFormatError(f"记录 ID 段长度非法: {consumed}")
    return start + consumed


__all__ = ["Record", "RecordHeader", "encode_id_segment"]

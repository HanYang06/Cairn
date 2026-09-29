# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""载体记录：总长自框定 + 校验和 + ID 段 + 载荷。

一条记录的字节布局（长度均指字节，见设计篇 §5.3）::

    +--------------+----------------+---------------------+----------------+
    | total_len(4) | checksum (64)  | id (canonical CBOR) | payload (rest) |
    +--------------+----------------+---------------------+----------------+

- ``total_len`` **大端无符号**，含自身；故记录自框定——顺扫一遍即得全部记录，
  不必依赖任何外部目录，索引库丢了也能重建；
- ``checksum`` 是载荷摘要的 64 位小写十六进制；与 ID 的摘要形态**同源**，
  故一次比较同时回答"读到的是不是原文"与"ID 声称的内容与实际内容是否一致"；
- ``id`` 只取落盘必需子集（§3.5，即两套凭证），用 canonical CBOR 编码——
  同一份 ID 恒得同一段字节，这是"按内容判重"在字节层成立的前提；
- ``payload`` 是记录内容，结构由上层决定，本层只当字节。

**"槽数"不进记录头**：槽对齐值是推导值（假定起点落在槽边界时装下总长需要几个槽），
记录在载体里的实际占用由起点偏移与长度一起推出（§5.2、§5.3），两者不落盘。
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING

import cbor2

from core.exc import RecordFormatError

from .id import ID, digest

if TYPE_CHECKING:
    from collections.abc import Mapping

LEN_BYTES = 4
"""总长字段的字节数（大端无符号）。"""

CHECKSUM_CHARS = 64
"""校验和字段的字节数：32 字节摘要的小写十六进制写法。"""

HEADER_BYTES = LEN_BYTES + CHECKSUM_CHARS
"""记录头（总长 + 校验和）的字节数；其后是 ID 段与载荷。"""

_MAX_TOTAL_LEN = (1 << (8 * LEN_BYTES)) - 1
_HEX_DIGITS = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class Record:
    """一条已解码的记录。

    Attributes:
        id: 记录携带的 ID（由落盘子集还原；名字、签发时间、位置不在记录里）。
        payload: 载荷字节，原样。
        total_len: 记录总长（自框定字段）。
        checksum: 记录头里的载荷摘要。
    """

    id: ID
    payload: bytes
    total_len: int
    checksum: str


def encode(record_id: ID, payload: bytes) -> bytes:
    """把一份 ID 与载荷编成一条记录。

    ID 未绑定内容（摘要为空串）时，由本函数把载荷摘要补进记录；已绑定但与载荷不符则拒绝——
    那说明"ID 声称的内容"与"实际内容"不是一回事，落盘只会把这个矛盾固化下来。

    Raises:
        RecordFormatError: ID 声明的摘要与载荷不符，或记录总长超出总长字段的表示范围。
    """
    checksum = digest(payload)
    if record_id.value_hash and record_id.value_hash != checksum:
        raise RecordFormatError(
            f"ID 声明的内容与载荷不符: id={record_id.value_hash} payload={checksum}"
        )
    id_record = record_id.to_record()
    id_record["value_hash"] = checksum
    section = cbor2.dumps(id_record, canonical=True)
    total_len = HEADER_BYTES + len(section) + len(payload)
    if total_len > _MAX_TOTAL_LEN:
        raise RecordFormatError(f"记录总长超出 {LEN_BYTES} 字节字段的表示范围: {total_len}")
    return _frame(total_len, checksum, section, payload)


def decode(raw: bytes) -> Record:
    """把一条记录的字节解回 ID 与载荷，并逐项自校验。

    校验顺序即失败原因的可分辨度：先总长自框定（截断／越界），再校验和（内容被改），
    最后 ID 段（身份不可解析）。任何一项不符都抛错，不降级、不猜。

    Raises:
        RecordFormatError: 总长与实际字节数不符、校验和非十六进制、ID 段不可解析、
            或载荷摘要与记录头不符。
        InvalidIdError: ID 段里缺少两套凭证或凭证为空。
    """
    if len(raw) < HEADER_BYTES:
        raise RecordFormatError(f"记录短于记录头: {len(raw)} < {HEADER_BYTES}")
    total_len = int.from_bytes(raw[:LEN_BYTES], "big")
    if total_len != len(raw):
        raise RecordFormatError(f"总长与实际字节数不符: 声明 {total_len}，实际 {len(raw)}")
    checksum = _parse_checksum(raw[LEN_BYTES:HEADER_BYTES])
    section = io.BytesIO(raw[HEADER_BYTES:])
    mapping = _decode_section(section)
    id_len = section.tell()
    payload = raw[HEADER_BYTES + id_len :]
    if digest(payload) != checksum:
        raise RecordFormatError("载荷摘要与记录头校验和不符：内容已被改动或截断")
    record_id = ID.from_record(mapping)
    if record_id.value_hash != checksum:
        raise RecordFormatError(
            f"ID 声明的摘要与载荷不符: id={record_id.value_hash} payload={checksum}"
        )
    return Record(id=record_id, payload=payload, total_len=total_len, checksum=checksum)


def _frame(total_len: int, checksum: str, section: bytes, payload: bytes) -> bytes:
    """按布局拼出记录字节。"""
    return total_len.to_bytes(LEN_BYTES, "big") + checksum.encode("ascii") + section + payload


def _parse_checksum(raw: bytes) -> str:
    """解析记录头里的校验和字段：必须是 64 位小写十六进制。"""
    try:
        checksum = raw.decode("ascii")
    except UnicodeDecodeError as error:
        raise RecordFormatError(f"校验和字段不是 ASCII: {raw!r}") from error
    if len(checksum) != CHECKSUM_CHARS or not set(checksum) <= _HEX_DIGITS:
        raise RecordFormatError(f"校验和字段不是 64 位小写十六进制: {checksum!r}")
    return checksum


def _decode_section(section: io.BytesIO) -> Mapping[str, object]:
    """解出 ID 段（只吃一个 CBOR 项，余下字节留给载荷）。

    用流式解码而不是 ``cbor2.loads``：后者会把"ID 段后面紧跟载荷"当成多余字节处理，
    而载荷未必是合法 CBOR 的延续，靠它切不出边界。键必须是字符串——CBOR 允许任意键，
    而 ID 段是字符串到值的映射，非字符串键在这里就是一份不认识的记录，不当成合法。
    """
    try:
        decoded = cbor2.CBORDecoder(section).decode()
    except (cbor2.CBORDecodeError, EOFError) as error:
        raise RecordFormatError(f"ID 段不是合法 CBOR: {error}") from error
    if not isinstance(decoded, dict):
        raise RecordFormatError(f"ID 段不是映射: {type(decoded).__name__}")
    mapping: dict[str, object] = {}
    for key, value in decoded.items():
        if not isinstance(key, str):
            raise RecordFormatError(f"ID 段的键不是字符串: {key!r}")
        mapping[key] = value
    return mapping


__all__ = ["CHECKSUM_CHARS", "HEADER_BYTES", "LEN_BYTES", "Record", "decode", "encode"]

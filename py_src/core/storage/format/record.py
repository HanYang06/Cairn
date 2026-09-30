# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
r"""载体记录：总长自框定 + 校验和 + ID 段 + 载荷。

一条记录的字节布局（长度均指字节，见设计篇 §5.3）::

    +--------------+----------------+---------------------+----------------+
    | total_len(4) | checksum (64)  | id (canonical CBOR) | payload (rest) |
    +--------------+----------------+---------------------+----------------+

- ``total_len`` **大端无符号**，含自身；故记录自框定——顺扫一遍即得全部记录，
  不必依赖任何外部目录，索引库丢了也能重建；
- ``checksum`` 是载荷摘要的 64 位小写十六进制；与 ID 的摘要形态**同源**，
  故一次比较同时回答"读到的是不是原文"与"ID 声称的内容与实际内容是否一致"；
- ``id`` 段是 canonical CBOR 映射，装 **ID 的落盘部分**（两套凭证、名字、签发时刻，
  见 `ID.to_record`）与**记录自报的类型标号**（保留键 ``\x00cairn.kind``）。
  保留键带不可打印前缀，业务数据不可能占用它；未知键一律忽略（§3.2.1、§3.5）；
- ``payload`` 是记录内容，结构由上层决定，本层只当字节。

**类型标号为什么在记录里**：索引库只做索引，它里面的每一个值都必须能从载体算回来。
`kind` 曾经只活在索引行里，于是索引一重扫，全库的块就不知道自己是什么类型
（"可重建的投影"当场不成立）。故类型由记录自报，索引那一列退成它的投影。

**"槽数"不进记录头**：槽对齐值是推导值（假定起点落在槽边界时装下总长需要几个槽），
记录在载体里的实际占用由起点偏移与长度一起推出（§5.2、§5.3），两者不落盘。
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING

import cbor2

from core.exc import InvalidIdError, RecordFormatError

from .id import ID, digest

if TYPE_CHECKING:
    from collections.abc import Mapping

LEN_BYTES = 4
"""总长字段的字节数（大端无符号）。"""

CHECKSUM_CHARS = 64
"""校验和字段的字节数：32 字节摘要的小写十六进制写法。"""

HEADER_BYTES = LEN_BYTES + CHECKSUM_CHARS
"""记录头（总长 + 校验和）的字节数；其后是 ID 段与载荷。"""

KIND_KEY = "\x00cairn.kind"
"""ID 段里的保留键：记录自报的类型标号（与 `block.BODY_REF_KEY` 同一套命名空间）。

它属于**记录**而不属于内容：同一段 body 字节可以被不同类型的块用（内容按地址去重），
故类型标号不能写进载荷——写进去就成了内容的一部分，去重会被类型切碎。
"""

_MAX_TOTAL_LEN = (1 << (8 * LEN_BYTES)) - 1
_HEX_DIGITS = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class Record:
    """一条已解码的记录。

    Attributes:
        id: 记录携带的 ID（由落盘部分还原；位置段不在记录里，由扫到的位置给出）。
        payload: 载荷字节，原样。
        total_len: 记录总长（自框定字段）。
        checksum: 记录头里的载荷摘要。
        kind: 记录自报的类型标号；没写即空串（内容记录不带类型标号）。
    """

    id: ID
    payload: bytes
    total_len: int
    checksum: str
    kind: str = ""


def encode(record_id: ID, payload: bytes, *, kind: str = "") -> bytes:
    """把一份 ID、一个类型标号与载荷编成一条记录。

    ID 未绑定内容（摘要为空串）时，由本函数把载荷摘要补进记录；已绑定但与载荷不符则拒绝——
    那说明"ID 声称的内容"与"实际内容"不是一回事，落盘只会把这个矛盾固化下来。

    类型标号只在非空时写下：内容记录没有类型，多写一个空键会让同一份内容的记录字节变长。

    Raises:
        RecordFormatError: ID 声明的摘要与载荷不符，或记录总长超出总长字段的表示范围。
    """
    checksum = digest(payload)
    if record_id.value_hash and record_id.value_hash != checksum:
        raise RecordFormatError(
            f"ID 声明的内容与载荷不符: id={record_id.value_hash} payload={checksum}"
        )
    section_record = record_id.to_record()
    section_record["value_hash"] = checksum
    if kind:
        section_record[KIND_KEY] = kind
    section = cbor2.dumps(section_record, canonical=True)
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
    try:
        record_id = ID.from_record(mapping)
    except InvalidIdError as error:
        raise RecordFormatError(f"ID 段身份非法: {error}") from error
    if record_id.value_hash != checksum:
        raise RecordFormatError(
            f"ID 声明的摘要与载荷不符: id={record_id.value_hash} payload={checksum}"
        )
    return Record(
        id=record_id,
        payload=payload,
        total_len=total_len,
        checksum=checksum,
        kind=_text_or_empty(mapping.get(KIND_KEY)),
    )


def _text_or_empty(value: object) -> str:
    """取一段可选文本：缺了或不是字符串即当空串（未知键的宽容读法）。"""
    return value if isinstance(value, str) else ""


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
    except Exception as error:
        raise RecordFormatError(f"ID 段解析失败: {error}") from error
    if not isinstance(decoded, dict):
        raise RecordFormatError(f"ID 段不是映射: {type(decoded).__name__}")
    mapping: dict[str, object] = {}
    for key, value in decoded.items():
        if not isinstance(key, str):
            raise RecordFormatError(f"ID 段的键不是字符串: {key!r}")
        mapping[key] = value
    return mapping


__all__ = ["CHECKSUM_CHARS", "HEADER_BYTES", "KIND_KEY", "LEN_BYTES", "Record", "decode", "encode"]

# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""记录层契约：自框定、校验和、ID 段落盘子集、逐项自校验。"""

from __future__ import annotations

import cbor2
import pytest

from core.exc import InvalidIdError, RecordFormatError
from core.storage.format.id import ID, digest
from core.storage.format.record import HEADER_BYTES, LEN_BYTES, decode, encode

_PAYLOAD = b"cairn-record-payload"


def _frame(payload: bytes, section: bytes, *, total_len: int | None = None) -> bytes:
    """按布局手工拼一条记录，用于构造"正常编码器不会产出"的坏样本。"""
    length = HEADER_BYTES + len(section) + len(payload) if total_len is None else total_len
    return length.to_bytes(LEN_BYTES, "big") + digest(payload).encode("ascii") + section + payload


def _credentials(**extra: object) -> bytes:
    """造一段合法的 ID 段（两套凭证），可附加额外键。"""
    return cbor2.dumps(
        {"value_uuid": "u-1", "value_hash": digest(_PAYLOAD), **extra}, canonical=True
    )


def test_roundtrip_keeps_identity_and_payload():
    """编码再解码：身份、载荷、总长原样回来。"""
    record_id = ID.of(_PAYLOAD)
    raw = encode(record_id, _PAYLOAD)

    record = decode(raw)

    assert record.payload == _PAYLOAD
    assert record.id.value_uuid == record_id.value_uuid
    assert record.id.value_hash == digest(_PAYLOAD)
    assert record.checksum == digest(_PAYLOAD)
    assert record.total_len == len(raw)


def test_the_record_carries_the_identity_fields_the_index_stores():
    """索引里有的 ID 字段都要能从记录还原：名字与签发时刻随之落盘（位置段除外）。"""
    record_id = ID(name="有名字的块", value_hash=digest(_PAYLOAD), birth_time=123456789)

    record = decode(encode(record_id, _PAYLOAD))

    assert record.id.name == "有名字的块"
    assert record.id.birth_time == 123456789


def test_the_record_reports_its_own_kind():
    """类型标号由记录自报：索引那一列是它的投影，故索引重扫之后类型不会丢。"""
    raw = encode(ID.of(_PAYLOAD), _PAYLOAD, kind="notedata")

    assert decode(raw).kind == "notedata"


def test_a_record_without_a_kind_reads_back_empty():
    """没写类型即空串：内容记录不带类型标号，不猜、也不降级成别的值。"""
    assert decode(encode(ID.of(_PAYLOAD), _PAYLOAD)).kind == ""


def test_total_len_self_frames_the_record():
    """总长在最前且含自身：顺扫即可切出记录，无需外部目录。"""
    raw = encode(ID.of(_PAYLOAD), _PAYLOAD)

    assert int.from_bytes(raw[:LEN_BYTES], "big") == len(raw)


def test_encode_binds_unbound_identity_without_mutating_caller():
    """未绑定内容的 ID 由编码处补上摘要；调用方手里的对象不被改写。"""
    record_id = ID()

    record = decode(encode(record_id, _PAYLOAD))

    assert record.id.value_hash == digest(_PAYLOAD)
    assert record_id.value_hash == ""


def test_encode_refuses_identity_that_contradicts_payload():
    """ID 声称的内容与实际载荷不符即拒绝：落盘只会把矛盾固化。"""
    record_id = ID(value_hash=digest(b"other"))

    with pytest.raises(RecordFormatError, match="不符"):
        encode(record_id, _PAYLOAD)


def test_record_is_canonical():
    """同一份 ID 与载荷编出的字节必须一致，否则字节层判重失效。"""
    record_id = ID.of(_PAYLOAD)

    assert encode(record_id, _PAYLOAD) == encode(record_id, _PAYLOAD)


def test_decode_detects_tampered_payload():
    """改动载荷一个字节即被校验和拦下。"""
    raw = bytearray(encode(ID.of(_PAYLOAD), _PAYLOAD))
    raw[-1] ^= 0xFF

    with pytest.raises(RecordFormatError, match="校验和"):
        decode(bytes(raw))


def test_decode_detects_truncation():
    """总长与实际字节数不符（截断）即被拦下。"""
    raw = encode(ID.of(_PAYLOAD), _PAYLOAD)

    with pytest.raises(RecordFormatError, match="总长"):
        decode(raw[:-1])


def test_decode_rejects_record_shorter_than_header():
    """短于记录头的字节不是记录。"""
    with pytest.raises(RecordFormatError, match="短于记录头"):
        decode(b"\x00" * (HEADER_BYTES - 1))


def test_decode_rejects_non_hex_checksum():
    """校验和字段必须是 64 位小写十六进制。"""
    raw = _frame(_PAYLOAD, _credentials())
    broken = raw[:LEN_BYTES] + b"Z" * (HEADER_BYTES - LEN_BYTES) + raw[HEADER_BYTES:]

    with pytest.raises(RecordFormatError, match="十六进制"):
        decode(broken)


def test_decode_rejects_non_mapping_id_section():
    """ID 段必须是映射。"""
    raw = _frame(_PAYLOAD, cbor2.dumps([1, 2], canonical=True))

    with pytest.raises(RecordFormatError, match="映射"):
        decode(raw)


def test_decode_rejects_unparsable_id_section():
    """ID 段不是合法 CBOR 即报错（载荷再长也不能被当成 CBOR 的延续）。

    样本是一段声称有一兆字节、实际没有的字节串：解码器读到流尾即失败，
    不会把后面的载荷一并读成 ID 段的一部分。
    """
    raw = _frame(_PAYLOAD, b"\x5b" + (1_000_000).to_bytes(8, "big"))

    with pytest.raises(RecordFormatError, match="CBOR"):
        decode(raw)


def test_decode_rejects_bad_birth_time():
    """可选字段形态非法即抛，不静默吞掉脏字节（记录层统一抛记录错，见 `decode`）。"""
    section = _credentials(birth_time="not-a-number")

    with pytest.raises(RecordFormatError, match="整数"):
        decode(_frame(_PAYLOAD, section))


def test_decode_ignores_unknown_keys_and_keeps_known_optionals():
    """向前兼容：未知键忽略；认识的字段有就读回，没有就取空值。"""
    section = _credentials(name="note-block", birth_time=1234, future_key="x")
    record = decode(_frame(_PAYLOAD, section))

    assert record.id.name == "note-block"
    assert record.id.birth_time == 1234


def test_decode_does_not_invent_birth_time():
    """记录里没有签发时间时取 0（未知），不得凭空填当前时刻。"""
    record = decode(_frame(_PAYLOAD, _credentials()))

    assert record.id.birth_time == 0
    assert record.id.name == ""


def test_decode_requires_both_credentials():
    """两套凭证缺一即报错；`decode` 对外只暴露记录错，`InvalidIdError` 在此归一并保留原因链。"""
    section = cbor2.dumps({"value_uuid": "u-1"}, canonical=True)

    with pytest.raises(RecordFormatError) as caught:
        decode(_frame(_PAYLOAD, section))

    assert isinstance(caught.value.__cause__, InvalidIdError)


def test_decode_rejects_non_ascii_checksum_field():
    """校验和字段是二进制垃圾时按格式错报，不让 UnicodeDecodeError 漏出去。"""
    raw = _frame(_PAYLOAD, _credentials())
    broken = raw[:LEN_BYTES] + b"\xff" * (HEADER_BYTES - LEN_BYTES) + raw[HEADER_BYTES:]

    with pytest.raises(RecordFormatError, match="ASCII"):
        decode(broken)


def test_decode_rejects_id_that_disagrees_with_checksum():
    """载荷与校验和都对得上，但 ID 段声明的摘要不是这份载荷：同样是记录损坏。"""
    section = cbor2.dumps({"value_uuid": "u-1", "value_hash": digest(b"other")}, canonical=True)

    with pytest.raises(RecordFormatError, match="ID 声明的摘要"):
        decode(_frame(_PAYLOAD, section))


def test_decode_rejects_non_string_keys_in_id_section():
    """CBOR 允许任意映射键，但 ID 段是字符串到值的映射；非字符串键即不认识。"""
    section = cbor2.dumps(
        {1: "x", "value_uuid": "u-1", "value_hash": digest(_PAYLOAD)}, canonical=True
    )

    with pytest.raises(RecordFormatError, match="键不是字符串"):
        decode(_frame(_PAYLOAD, section))


def test_from_record_rejects_empty_credentials():
    """凭证存在但为空串（例如显式 null 被写成空）同样不是合法身份。"""
    section = cbor2.dumps({"value_uuid": "", "value_hash": digest(_PAYLOAD)}, canonical=True)

    with pytest.raises(RecordFormatError):
        decode(_frame(_PAYLOAD, section))


def test_payload_may_be_empty_or_binary():
    """载荷结构不收窄：空载荷与含零字节的二进制都原样往返。"""
    for payload in (b"", b"\x00\x01\x00\xff"):
        assert decode(encode(ID.of(payload), payload)).payload == payload

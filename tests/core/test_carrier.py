# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""载体层用例：槽布局算术、记录编解码、载体读写与顺扫重建。

设计依据：`docs/architecture/storage-design.md` §5。
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest

from core.storage import CarrierFile, CarrierLayout, Record, RecordHeader
from core.storage.carrier import (
    CARRIER_HEADER_BYTES,
    CARRIER_MAGIC,
    slot_offset,
    slot_span,
    slots_for,
)
from core.types import (
    CorruptObjectError,
    Id,
    RecordFormatError,
    SlotError,
    SlotRange,
    ValueHash,
)

if TYPE_CHECKING:
    from pathlib import Path

SLOT = 64


def _record(payload: bytes, **place: object) -> Record:
    """造一条记录（内容凭证由载荷算出，位置字段可选）。"""
    return Record.create(Id.new(payload, **place), payload, SLOT)  # type: ignore[arg-type]


def _carrier(tmp_path: Path) -> CarrierFile:
    return CarrierFile.create(tmp_path / "pack", slot_bytes=SLOT)


# ---- 槽算术 ----


@pytest.mark.parametrize(
    ("length", "expected"),
    [(0, 1), (1, 1), (64, 1), (65, 2), (128, 2), (129, 3)],
)
def test_slots_for_rounds_up(length: int, expected: int) -> None:
    assert slots_for(length, SLOT) == expected


def test_slot_offset_is_linear() -> None:
    assert slot_offset(0, SLOT) == 0
    assert slot_offset(3, SLOT) == 3 * SLOT


@pytest.mark.parametrize(
    ("offset", "start", "head"),
    [(0, 0, 0), (1, 0, 1), (63, 0, 63), (64, 1, 0), (70, 1, 6)],
)
def test_slot_span_keeps_head(offset: int, start: int, head: int) -> None:
    span = slot_span(offset, 10, SLOT)
    assert (span.start, span.head) == (start, head)


def test_slot_span_count_covers_length() -> None:
    assert slot_span(0, 65, SLOT).count == 2


@pytest.mark.parametrize(("offset", "length"), [(-1, 1), (0, -1)])
def test_slot_helpers_reject_negative(offset: int, length: int) -> None:
    with pytest.raises(SlotError):
        slot_span(offset, length, SLOT)


def test_slot_helpers_reject_bad_slot_bytes() -> None:
    with pytest.raises(SlotError):
        slots_for(1, 0)
    with pytest.raises(SlotError):
        slot_offset(1, 0)


def test_layout_offset_and_span_are_inverse() -> None:
    layout = CarrierLayout(slot_bytes=SLOT)
    for offset in (0, 1, 63, 64, 200, 1000):
        span = layout.span_of(layout.header_bytes + offset, 137)
        assert layout.offset_of_span(span) == layout.header_bytes + offset


def test_layout_rejects_bad_values() -> None:
    with pytest.raises(SlotError):
        CarrierLayout(slot_bytes=0)
    with pytest.raises(SlotError):
        CarrierLayout(slot_bytes=SLOT, header_bytes=CARRIER_HEADER_BYTES - 1)


def test_layout_record_bytes_lower_bound() -> None:
    layout = CarrierLayout(slot_bytes=SLOT)
    assert layout.record_bytes(1) == 1
    assert layout.record_bytes(3) == 2 * SLOT + 1
    with pytest.raises(SlotError):
        layout.record_bytes(0)


# ---- 载体文件头 ----


def test_header_roundtrip() -> None:
    layout = CarrierLayout(slot_bytes=4096)
    back = CarrierLayout.decode_header(layout.encode_header())
    assert back.slot_bytes == 4096
    assert back.header_bytes == CARRIER_HEADER_BYTES


def test_header_starts_with_magic_and_reserves_room() -> None:
    raw = CarrierLayout(slot_bytes=SLOT).encode_header()
    assert raw.startswith(CARRIER_MAGIC)
    assert len(raw) > len(CARRIER_MAGIC) + 8


def test_header_rejects_short_input() -> None:
    with pytest.raises(RecordFormatError):
        CarrierLayout.decode_header(CARRIER_MAGIC)


def test_header_rejects_bad_magic() -> None:
    raw = bytearray(CarrierLayout(slot_bytes=SLOT).encode_header())
    raw[0] ^= 0xFF
    with pytest.raises(RecordFormatError):
        CarrierLayout.decode_header(bytes(raw))


def test_header_rejects_zero_slot_bytes() -> None:
    raw = CARRIER_MAGIC + struct.pack(">Q", 0) + b"\x00" * 8
    with pytest.raises(RecordFormatError):
        CarrierLayout.decode_header(raw)


def test_create_writes_header_and_open_reads_it_back(tmp_path: Path) -> None:
    path = tmp_path / "pack"
    CarrierFile.create(path, slot_bytes=4096)
    assert path.stat().st_size == CARRIER_HEADER_BYTES
    assert CarrierFile.open(path).layout.slot_bytes == 4096


def test_open_rejects_foreign_file(tmp_path: Path) -> None:
    path = tmp_path / "not_a_pack"
    path.write_bytes(b"hello world" * 4)
    with pytest.raises(RecordFormatError):
        CarrierFile.open(path)


# ---- 槽长来自配置，此后按文件头读 ----


def test_slot_bytes_comes_from_declaration(tmp_path: Path) -> None:
    from core.storage.conf import conf as storage_conf  # noqa: PLC0415 — 按需取声明

    declared: int = storage_conf.pack_slot_bytes
    assert CarrierFile.create(tmp_path / "pack").layout.slot_bytes == declared


def test_explicit_slot_bytes_overrides_config(tmp_path: Path) -> None:
    carrier = CarrierFile.create(tmp_path / "pack", slot_bytes=4096)
    assert carrier.layout.slot_bytes == 4096
    assert CarrierFile.open(tmp_path / "pack").layout.slot_bytes == 4096


def test_changing_config_does_not_reinterpret_existing_carrier(tmp_path: Path) -> None:
    """槽长只在**建载体**时读一次配置；已落盘的载体永远按自己文件头解释。

    否则改一次配置，老载体的偏移全部错位——这是"物理坐标是投影"的前提。
    """
    from core.conf import conf as engine_conf  # noqa: PLC0415

    original = engine_conf.get("storage.pack.slot_bytes")
    carrier = CarrierFile.create(tmp_path / "pack", slot_bytes=4096)
    try:
        engine_conf.set("storage.pack.slot_bytes", 8192)
        assert CarrierFile.open(tmp_path / "pack").layout.slot_bytes == 4096
        record = _record(b"still readable")
        span = carrier.append(record)
        assert Record.decode(carrier.read(span), carrier.layout) == record
    finally:
        engine_conf.set("storage.pack.slot_bytes", original)


# ---- 记录编解码 ----


def test_record_header_reports_derived_values() -> None:
    record = _record(b"hello")
    header = record.header(SLOT)
    assert header.total_len == record.total_len
    assert header.slot_count == slots_for(record.total_len, SLOT)
    assert header.checksum == ValueHash.of(b"hello")
    assert header.id == record.id


def test_record_roundtrip_preserves_id_and_payload() -> None:
    record = _record(b"payload-bytes", name="body ID", issuer="cairn", in_bucket_name="main")
    back = Record.decode(record.encode(), CarrierLayout(slot_bytes=SLOT))
    assert back == record
    assert back.id.value_hash == record.id.value_hash
    assert back.payload == b"payload-bytes"


def test_record_roundtrip_empty_payload() -> None:
    record = _record(b"")
    assert Record.decode(record.encode()).payload == b""


def test_record_roundtrip_large_payload() -> None:
    payload = bytes(range(256)) * 4096  # 1 MiB
    record = _record(payload)
    back = Record.decode(record.encode(), CarrierLayout(slot_bytes=SLOT))
    assert back.payload == payload
    assert back == record


def test_record_create_rejects_slot_mismatch() -> None:
    record = _record(b"x")
    with pytest.raises(SlotError):
        RecordHeader(
            total_len=record.total_len,
            checksum=record.checksum,
            id=record.id,
            slot_count=1,  # 实际需要 5 槽
        ).verify(CarrierLayout(slot_bytes=SLOT))


def test_record_header_rejects_tiny_total_len() -> None:
    with pytest.raises(RecordFormatError):
        RecordHeader(total_len=1, checksum=ValueHash.of(b""), id=Id.new(b""), slot_count=1)


def test_record_header_rejects_zero_slots() -> None:
    with pytest.raises(SlotError):
        RecordHeader(total_len=1024, checksum=ValueHash.of(b""), id=Id.new(b""), slot_count=0)


def test_decode_rejects_short_buffer() -> None:
    with pytest.raises(RecordFormatError):
        Record.decode(b"\x00\x00")


def test_decode_rejects_length_mismatch() -> None:
    raw = _record(b"hello").encode()
    with pytest.raises(RecordFormatError):
        Record.decode(raw[:-1])
    with pytest.raises(RecordFormatError):
        Record.decode(raw + b"extra")


def test_decode_rejects_corrupt_payload() -> None:
    record = _record(b"hello world")
    raw = bytearray(record.encode())
    raw[-1] ^= 0xFF
    with pytest.raises(CorruptObjectError):
        Record.decode(bytes(raw))


def test_decode_rejects_corrupt_id_segment() -> None:
    record = _record(b"hello world")
    raw = bytearray(record.encode())
    raw[CARRIER_HEADER_BYTES + 8] ^= 0xFF  # 落在 ID 段里
    with pytest.raises(RecordFormatError):
        Record.decode(bytes(raw))


def test_decode_rejects_checksum_field_corruption() -> None:
    raw = bytearray(_record(b"hello world").encode())
    raw[4] = ord("z")  # 摘要字段第一位
    with pytest.raises(RecordFormatError):
        Record.decode(bytes(raw))


# ---- 载体读写 ----


def test_append_returns_span_for_actual_position(tmp_path: Path) -> None:
    carrier = _carrier(tmp_path)
    first = _record(b"a" * 10)
    second = _record(b"b" * 10)
    first_span = carrier.append(first)
    second_span = carrier.append(second)
    assert first_span == SlotRange(0, slots_for(first.total_len, SLOT), 0)
    # 第二条紧接前一条：起点落在同一条记录的末尾（同槽或次槽），槽内偏移非零
    expected_start, expected_head = divmod(first.total_len, SLOT)
    assert (second_span.start, second_span.head) == (expected_start, expected_head)
    assert second_span.head != 0  # 若丢掉 head，两条记录的起点就会撞在一起


def test_read_returns_exactly_one_record(tmp_path: Path) -> None:
    carrier = _carrier(tmp_path)
    records = [_record(payload) for payload in (b"one", b"two-two", b"three")]
    spans = [carrier.append(record) for record in records]
    for record, span in zip(records, spans, strict=True):
        assert Record.decode(carrier.read(span), carrier.layout) == record


def test_used_bytes_and_slot_count_track_writes(tmp_path: Path) -> None:
    carrier = _carrier(tmp_path)
    assert carrier.used_bytes == 0
    assert carrier.slot_count == 0
    record = _record(b"x" * 100)
    carrier.append(record)
    assert carrier.used_bytes == record.total_len
    assert carrier.slot_count == slots_for(record.total_len, SLOT)


def test_read_rejects_span_beyond_file(tmp_path: Path) -> None:
    carrier = _carrier(tmp_path)
    carrier.append(_record(b"x"))
    with pytest.raises(RecordFormatError):
        carrier.read(SlotRange(carrier.slot_count + 5, 1))


def test_read_rejects_zero_count() -> None:
    with pytest.raises(ValueError, match="槽区间"):
        SlotRange(0, 0)


# ---- 顺扫重建 ----


def test_scan_rebuilds_every_record_in_order(tmp_path: Path) -> None:
    carrier = _carrier(tmp_path)
    records = [_record(payload) for payload in (b"first", b"", b"x" * 300, b"last")]
    spans = [carrier.append(record) for record in records]
    scanned = list(carrier.scan())
    assert [record for _span, record in scanned] == records
    # 顺扫给出的位置必须与写入时算出的那个一致：重建正是靠这一条把索引接回去。
    assert [span for span, _record in scanned] == spans
    assert [item.payload for _span, item in scanned] == [item.payload for item in records]


def test_scan_of_empty_carrier_is_empty(tmp_path: Path) -> None:
    assert list(_carrier(tmp_path).scan()) == []


def test_scan_rejects_truncated_tail(tmp_path: Path) -> None:
    carrier = _carrier(tmp_path)
    carrier.append(_record(b"first"))
    second = _record(b"second")
    carrier.append(second)
    raw = carrier.path.read_bytes()
    carrier.path.write_bytes(raw[: len(raw) - 3])
    with pytest.raises(RecordFormatError):
        list(CarrierFile.open(carrier.path).scan())


def test_scan_rejects_corrupt_payload(tmp_path: Path) -> None:
    carrier = _carrier(tmp_path)
    record = _record(b"important")
    span = carrier.append(record)
    start = carrier.layout.offset_of_span(span)
    raw = bytearray(carrier.path.read_bytes())
    raw[start + record.total_len - 1] ^= 0xFF
    carrier.path.write_bytes(bytes(raw))
    with pytest.raises(CorruptObjectError):
        list(CarrierFile.open(carrier.path).scan())

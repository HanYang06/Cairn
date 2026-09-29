# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""载体契约：文件头、槽算术、追加写、按槽区间读、顺扫。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core.exc import RecordFormatError, SlotError
from core.storage.carrier import (
    HEADER_BYTES,
    MAGIC,
    Carrier,
    SlotRange,
    aligned_slots,
    build_header,
    occupied_slots,
    parse_header,
)
from core.storage.format.id import ID
from core.storage.format.record import HEADER_BYTES as RECORD_HEADER_BYTES
from core.storage.format.record import decode, encode

if TYPE_CHECKING:
    from pathlib import Path

_SLOT = 64
_BIG_SLOT = 4096


def _record(payload: bytes) -> bytes:
    """造一条真实记录。"""
    return encode(ID.of(payload), payload)


# ---- 文件头 ----


def test_file_header_roundtrip():
    """文件头写槽长、读槽长；长度是设计篇记的 24 字节。"""
    raw = build_header(_BIG_SLOT)

    assert len(raw) == HEADER_BYTES == 24
    assert raw.startswith(MAGIC)
    assert parse_header(raw) == _BIG_SLOT


def test_header_rejects_foreign_or_short_bytes():
    """认不出魔数就不猜；文件头不足即报错。"""
    with pytest.raises(RecordFormatError, match="不是载体"):
        parse_header(b"NOTAPACK" + bytes(HEADER_BYTES - 8))
    with pytest.raises(RecordFormatError, match="不足"):
        parse_header(MAGIC)


def test_header_rejects_non_positive_slot():
    """槽长为 0 的载体算不出任何偏移，直接拒绝。"""
    with pytest.raises(SlotError, match="槽长"):
        parse_header(MAGIC + (0).to_bytes(8, "big") + bytes(8))


# ---- 槽算术 ----


def test_slot_count_has_two_meanings():
    """两套口径各算各的：槽对齐值 1，实际占用 2（设计篇 §5.3 的例子）。"""
    assert aligned_slots(4, 4) == 1
    assert occupied_slots(1, 4, 4) == 2


def test_slot_arithmetic_rounds_up():
    """装不下就多占一个槽；正好整除时不多占。"""
    assert aligned_slots(64, 64) == 1
    assert aligned_slots(65, 64) == 2
    assert occupied_slots(0, 65, 64) == 2
    assert occupied_slots(63, 1, 64) == 1


def test_slot_arithmetic_rejects_nonsense():
    """长度为零、槽长非正、偏移为负都不是合法输入。"""
    with pytest.raises(SlotError):
        aligned_slots(0, 64)
    with pytest.raises(SlotError):
        occupied_slots(0, 5, 0)
    with pytest.raises(SlotError):
        occupied_slots(-1, 5, 64)


def test_slot_range_validates_and_converts():
    """槽区间自校验，且与字节偏移互为逆运算。"""
    span = SlotRange(start=3, count=2, head=5)

    assert span.end == 4
    assert span.offset(64) == 197
    assert str(span) == "3:2:5"
    with pytest.raises(SlotError):
        SlotRange(start=-1, count=1)
    with pytest.raises(SlotError):
        SlotRange(start=0, count=0)
    with pytest.raises(SlotError):
        SlotRange(start=0, count=1, head=-1)


# ---- 载体 ----


def test_new_carrier_writes_header(tmp_path: Path):
    """新建载体：文件头先落地，文件长度即文件头长度。"""
    with Carrier(tmp_path / "p1", slot_bytes=_SLOT) as carrier:
        assert carrier.slot_bytes == _SLOT
        assert carrier.size == HEADER_BYTES


def test_new_carrier_needs_slot_bytes(tmp_path: Path):
    """新建时不给槽长就不知道该按什么粒度定位，拒绝。"""
    with pytest.raises(SlotError, match="槽长"):
        Carrier(tmp_path / "p2")


def test_open_reads_slot_from_header(tmp_path: Path):
    """槽长以文件头为准：重开时给不给都要一致，给错了拒绝。"""
    path = tmp_path / "p3"
    Carrier(path, slot_bytes=_SLOT).close()

    without_slot = Carrier(path)
    assert without_slot.slot_bytes == _SLOT
    without_slot.close()

    same_slot = Carrier(path, slot_bytes=_SLOT)
    assert same_slot.slot_bytes == _SLOT
    same_slot.close()

    with pytest.raises(SlotError, match="不符"):
        Carrier(path, slot_bytes=_BIG_SLOT)


def test_open_rejects_foreign_file(tmp_path: Path):
    """不是载体的文件一律拒开。"""
    path = tmp_path / "foreign"
    path.write_bytes(b"not a carrier at all" * 4)

    with pytest.raises(RecordFormatError):
        Carrier(path)


def test_append_reports_span_and_read_returns_bytes(tmp_path: Path):
    """追加写出槽区间，按区间能读回原始字节。"""
    raw = _record(b"hello")
    with Carrier(tmp_path / "p4", slot_bytes=_SLOT) as carrier:
        span = carrier.append(raw)

        assert span.start == 0
        assert span.head == HEADER_BYTES
        assert span.count == occupied_slots(HEADER_BYTES, len(raw), _SLOT)
        assert carrier.read(span) == raw
        assert carrier.size == HEADER_BYTES + len(raw)


def test_small_records_share_a_slot_but_keep_distinct_heads(tmp_path: Path):
    """小记录同槽共存：起点槽相同、槽内偏移不同；只记 (起始槽, 槽数) 会读出错位内容。

    这是"槽区间第三项不可省"的回归线。
    """
    first, second = _record(b"one"), _record(b"two")
    with Carrier(tmp_path / "p5", slot_bytes=_BIG_SLOT) as carrier:
        span_a = carrier.append(first)
        span_b = carrier.append(second)

        assert span_a.start == span_b.start == 0
        assert span_a.head != span_b.head
        assert carrier.read(span_a) == first
        assert carrier.read(span_b) == second


def test_read_rejects_span_that_disagrees_with_record(tmp_path: Path):
    """索引里的槽数与记录长度推出的实际占用不符即报错，不读错位内容。"""
    raw = _record(b"x" * 200)
    with Carrier(tmp_path / "p6", slot_bytes=_SLOT) as carrier:
        span = carrier.append(raw)
        wrong = SlotRange(start=span.start, count=span.count + 1, head=span.head)

        with pytest.raises(SlotError, match="槽数"):
            carrier.read(wrong)


def test_scan_yields_every_record_in_order(tmp_path: Path):
    """顺扫交出全部记录，顺序即写入顺序。"""
    payloads = [b"alpha", b"beta", b"gamma"]
    with Carrier(tmp_path / "p7", slot_bytes=_SLOT) as carrier:
        for payload in payloads:
            carrier.append(_record(payload))

        scanned = [decode(raw).payload for _span, raw in carrier.scan()]

    assert scanned == payloads


def test_scan_detects_truncation(tmp_path: Path):
    """记录被截断时顺扫当场报错，不静默跳过（跳过是巡检的策略，不是本层）。"""
    path = tmp_path / "p8"
    with Carrier(path, slot_bytes=_SLOT) as carrier:
        carrier.append(_record(b"first"))
        carrier.append(_record(b"second"))

    raw = path.read_bytes()
    path.write_bytes(raw[:-10])

    with Carrier(path) as carrier, pytest.raises(RecordFormatError, match="截断"):
        list(carrier.scan())


def test_carrier_exposes_its_path(tmp_path: Path):
    """载体认得自己的路径（桶与巡检要从它推出位置）。"""
    path = tmp_path / "p12"
    with Carrier(path, slot_bytes=_SLOT) as carrier:
        assert carrier.path == path


def test_read_reports_missing_record_header(tmp_path: Path):
    """按区间读到文件尾之外：读不到总长，报错而不是返回空。"""
    path = tmp_path / "p13"
    with Carrier(path, slot_bytes=_SLOT) as carrier:
        span = SlotRange(start=0, count=1, head=HEADER_BYTES)
        with pytest.raises(RecordFormatError, match="读不到记录总长"):
            carrier.read(span)


def test_read_rejects_bogus_total_len(tmp_path: Path):
    """记录头的总长小于记录头本身：这种脏值会让顺扫打转，当场报错。"""
    path = tmp_path / "p14"
    path.write_bytes(build_header(_SLOT) + (2).to_bytes(4, "big") + bytes(60))

    with Carrier(path) as carrier, pytest.raises(RecordFormatError, match="总长非法"):
        carrier.read(SlotRange(start=0, count=1, head=HEADER_BYTES))


def test_read_reports_truncated_record(tmp_path: Path):
    """记录头在、载荷不全：截断即报错，不返回半条记录。"""
    path = tmp_path / "p15"
    with Carrier(path, slot_bytes=_SLOT) as carrier:
        carrier.append(_record(b"first"))
        span = carrier.append(_record(b"second"))

    with path.open("r+b") as handle:
        handle.truncate(span.offset(_SLOT) + RECORD_HEADER_BYTES)

    with Carrier(path) as carrier, pytest.raises(RecordFormatError, match="截断"):
        carrier.read(span)


def test_append_refuses_record_shorter_than_header(tmp_path: Path):
    """短于记录头的字节根本不是记录，不许落盘。"""
    with (
        Carrier(tmp_path / "p16", slot_bytes=_SLOT) as carrier,
        pytest.raises(RecordFormatError, match="短于记录头"),
    ):
        carrier.append(b"short")


def test_append_refuses_broken_record(tmp_path: Path):
    """写入前核对自框定字段：总长与实际字节数不符的记录不许落盘。"""
    raw = bytearray(_record(b"data"))
    raw[0] = 0xFF
    with Carrier(tmp_path / "p9", slot_bytes=_SLOT) as carrier, pytest.raises(RecordFormatError):
        carrier.append(bytes(raw))


def test_sealed_is_a_threshold_judgement(tmp_path: Path):
    """封口是策略判断：达到封口线即"已封口"，且不阻止继续写入大记录。"""
    with Carrier(tmp_path / "p10", slot_bytes=_SLOT) as carrier:
        carrier.append(_record(b"a"))
        assert not carrier.sealed(carrier.size + 1)
        assert carrier.sealed(carrier.size)

        big = _record(b"b" * 500)
        span = carrier.append(big)

        assert carrier.read(span) == big


def test_context_manager_closes_handle(tmp_path: Path):
    """退出 with 即关闭句柄。"""
    with Carrier(tmp_path / "p11", slot_bytes=_SLOT) as carrier:
        carrier.append(_record(b"a"))
    with pytest.raises(ValueError, match="closed"):
        _ = carrier.size

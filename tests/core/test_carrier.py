# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""载体契约：文件头、格算术、追加写、按格区间读、顺扫。

模型是"一串等大的格子、记录从格边界开始、写不下往后拼格子"，故这里的用例同时钉住它的
**代价**：一条记录至少占一格，格尾补零——那不是实现细节，是这套定位方式的前提。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core.exc import RecordFormatError, SlotError
from core.storage.carrier import (
    HEADER_BYTES,
    MAGIC,
    Carrier,
    SlotRange,
    build_header,
    owner_digest,
    parse_header,
    slots_needed,
)
from core.storage.format.id import ID
from core.storage.format.record import HEADER_BYTES as RECORD_HEADER_BYTES
from core.storage.format.record import decode, encode

if TYPE_CHECKING:
    from pathlib import Path

_SLOT = 512
_TIGHT = 256


def _record(payload: bytes) -> bytes:
    """造一条真实记录。"""
    return encode(ID.of(payload), payload)


# ---- 文件头 ----


def test_file_header_roundtrip():
    """文件头写槽长、读槽长；长度是设计篇记的 24 字节。"""
    raw = build_header(_SLOT)

    assert len(raw) == HEADER_BYTES == 24
    assert raw.startswith(MAGIC)
    header = parse_header(raw)
    assert header.slot_bytes == _SLOT
    assert not header.has_owner, "没给归属名即全零，读回来是「无归属」"


def test_file_header_carries_owner():
    """归属摘要写进预留段：同一个名字恒得同一份摘要，不同的名字不该撞。"""
    header = parse_header(build_header(_SLOT, "attrindex"))

    assert header.slot_bytes == _SLOT
    assert header.has_owner
    assert header.owner == owner_digest("attrindex")
    assert header.owner != owner_digest("notedata")


def test_reserved_bytes_left_zero_read_as_no_owner():
    """旧版本留下的文件（预留段没写东西）读回来是「无归属」这个合法状态，不报错。"""
    legacy = MAGIC + _SLOT.to_bytes(8, "big") + bytes(8)

    header = parse_header(legacy)

    assert header.slot_bytes == _SLOT
    assert not header.has_owner


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


# ---- 格算术 ----


def test_slots_needed_rounds_up_and_never_zero():
    """装不下就多占一格；正好整除不多占；一条记录至少算一格。"""
    assert slots_needed(1, 512) == 1
    assert slots_needed(512, 512) == 1
    assert slots_needed(513, 512) == 2
    assert slots_needed(4096, 512) == 8


def test_slots_needed_rejects_nonsense():
    """长度为零、槽长非正都不是合法输入。"""
    with pytest.raises(SlotError):
        slots_needed(0, 512)
    with pytest.raises(SlotError):
        slots_needed(10, 0)


def test_slot_range_is_two_numbers():
    """两个数字即位置：头格与末格，闭区间；格数与字节偏移都由它推出。"""
    span = SlotRange(first=3, last=5)

    assert span.count == 3
    assert span.offset(512) == HEADER_BYTES + 3 * 512
    assert str(span) == "3-5"
    assert SlotRange(first=7, last=7).count == 1


def test_slot_range_validates_order():
    """末格不得小于起始格，起始格不得为负。"""
    with pytest.raises(SlotError):
        SlotRange(first=-1, last=0)
    with pytest.raises(SlotError):
        SlotRange(first=5, last=4)


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
        Carrier(path, slot_bytes=_TIGHT)


def test_open_rejects_foreign_file(tmp_path: Path):
    """不是载体的文件一律拒开。"""
    path = tmp_path / "foreign"
    path.write_bytes(b"not a carrier at all" * 4)

    with pytest.raises(RecordFormatError):
        Carrier(path)


def test_append_starts_at_slot_boundary(tmp_path: Path):
    """第一条记录从第 0 格的格边界开始；返回的两个数字即它的位置。"""
    raw = _record(b"hello")
    with Carrier(tmp_path / "p4", slot_bytes=_SLOT) as carrier:
        span = carrier.append(raw)

        assert span.first == 0
        assert span.last == slots_needed(len(raw), _SLOT) - 1
        assert span.offset(_SLOT) == HEADER_BYTES
        assert carrier.read(span) == raw


def test_tail_is_padded_to_whole_slots(tmp_path: Path):
    """写完后末格补零：记录区恒为整格，下一格自然落在格边界。"""
    raw = _record(b"hello")
    with Carrier(tmp_path / "p5", slot_bytes=_SLOT) as carrier:
        carrier.append(raw)

        assert (carrier.size - HEADER_BYTES) % _SLOT == 0
        assert carrier.size == HEADER_BYTES + slots_needed(len(raw), _SLOT) * _SLOT


def test_record_filling_whole_slots_needs_no_padding(tmp_path: Path):
    """记录正好占满整数格时不补零（补零只发生在末格写不满时）。"""
    overhead = len(encode(ID.of(b""), b""))
    payload = b"\x00" * (_SLOT * 2 - overhead)
    raw = encode(ID.of(payload), payload)
    assert len(raw) == _SLOT * 2

    with Carrier(tmp_path / "p5b", slot_bytes=_SLOT) as carrier:
        span = carrier.append(raw)

        assert span == SlotRange(first=0, last=1)
        assert carrier.size == HEADER_BYTES + _SLOT * 2
        assert carrier.read(span) == raw


def test_each_record_takes_whole_slots(tmp_path: Path):
    """**代价的契约**：一条记录至少占一格，再小也独占一整格，第二条从下一格开始。

    这是"记录从格边界开始"换来的简单定位所必须付的账；若哪天改成紧凑排布，
    这条用例会红，提醒定位模型也跟着变了。
    """
    first, second = _record(b"one"), _record(b"two")
    with Carrier(tmp_path / "p6", slot_bytes=_SLOT) as carrier:
        span_a = carrier.append(first)
        span_b = carrier.append(second)

        assert span_a == SlotRange(first=0, last=0)
        assert span_b.first == 1
        assert carrier.read(span_a) == first
        assert carrier.read(span_b) == second


def test_record_larger_than_one_slot_spans_more(tmp_path: Path):
    """写不下就往后拼格子：一条大记录占连续的若干格。"""
    raw = _record(b"x" * (_SLOT * 3))
    with Carrier(tmp_path / "p7", slot_bytes=_SLOT) as carrier:
        span = carrier.append(raw)

        assert span.count == slots_needed(len(raw), _SLOT)
        assert span.count >= 4
        assert carrier.read(span) == raw


def test_read_rejects_range_whose_last_slot_disagrees(tmp_path: Path):
    """声明的末格与记录总长推出的不一致即报错，不读错位内容。"""
    raw = _record(b"x" * 200)
    with Carrier(tmp_path / "p8", slot_bytes=_SLOT) as carrier:
        span = carrier.append(raw)
        wrong = SlotRange(first=span.first, last=span.last + 1)

        with pytest.raises(SlotError, match="末格"):
            carrier.read(wrong)


def test_read_reports_missing_record_header(tmp_path: Path):
    """按区间读到文件尾之外：读不到总长，报错而不是返回空。"""
    with (
        Carrier(tmp_path / "p9", slot_bytes=_SLOT) as carrier,
        pytest.raises(RecordFormatError, match="读不到记录总长"),
    ):
        carrier.read(SlotRange(first=0, last=0))


def test_read_rejects_bogus_total_len(tmp_path: Path):
    """记录头的总长小于记录头本身：这种脏值会让顺扫打转，当场报错。"""
    path = tmp_path / "p10"
    path.write_bytes(build_header(_SLOT) + (2).to_bytes(4, "big") + bytes(_SLOT - 4))

    with Carrier(path) as carrier, pytest.raises(RecordFormatError, match="总长非法"):
        carrier.read(SlotRange(first=0, last=0))


def test_read_reports_truncated_record(tmp_path: Path):
    """记录头在、载荷不全：截断即报错，不返回半条记录。"""
    path = tmp_path / "p11"
    with Carrier(path, slot_bytes=_SLOT) as carrier:
        carrier.append(_record(b"first"))
        span = carrier.append(_record(b"second"))

    with path.open("r+b") as handle:
        handle.truncate(span.offset(_SLOT) + RECORD_HEADER_BYTES)

    with Carrier(path) as carrier, pytest.raises(RecordFormatError, match="截断"):
        carrier.read(span)


def test_append_refuses_unaligned_tail(tmp_path: Path):
    """尾部不是整格（残写或外来改动）：拒绝续写，不猜从哪儿接。"""
    path = tmp_path / "p12"
    with Carrier(path, slot_bytes=_SLOT) as carrier:
        carrier.append(_record(b"first"))
        size = carrier.size

    with path.open("r+b") as handle:
        handle.truncate(size + 17)

    with Carrier(path) as carrier, pytest.raises(RecordFormatError, match="格边界"):
        carrier.append(_record(b"second"))


def test_append_refuses_record_shorter_than_header(tmp_path: Path):
    """短于记录头的字节根本不是记录，不许落盘。"""
    with (
        Carrier(tmp_path / "p13", slot_bytes=_SLOT) as carrier,
        pytest.raises(RecordFormatError, match="短于记录头"),
    ):
        carrier.append(b"short")


def test_append_refuses_broken_record(tmp_path: Path):
    """写入前核对自框定字段：总长与实际字节数不符的记录不许落盘。"""
    raw = bytearray(_record(b"data"))
    raw[0] = 0xFF
    with Carrier(tmp_path / "p14", slot_bytes=_SLOT) as carrier, pytest.raises(RecordFormatError):
        carrier.append(bytes(raw))


def test_scan_yields_every_record_in_order(tmp_path: Path):
    """顺扫交出全部记录，顺序即写入顺序（末格补零不被当成下一条记录）。"""
    payloads = [b"alpha", b"beta", b"gamma"]
    with Carrier(tmp_path / "p15", slot_bytes=_SLOT) as carrier:
        for payload in payloads:
            carrier.append(_record(payload))

        scanned = [decode(raw).payload for _span, raw in carrier.scan()]

    assert scanned == payloads


def test_scan_reports_spans_matching_writes(tmp_path: Path):
    """顺扫报出的格区间与写入时返回的一致。"""
    with Carrier(tmp_path / "p16", slot_bytes=_SLOT) as carrier:
        written = [carrier.append(_record(b"a" * (i * 300))) for i in range(1, 4)]

        assert [span for span, _raw in carrier.scan()] == written


def test_scan_detects_truncation(tmp_path: Path):
    """记录被截断时顺扫当场报错，不静默跳过（跳过是巡检的策略，不是本层）。"""
    path = tmp_path / "p17"
    with Carrier(path, slot_bytes=_SLOT) as carrier:
        carrier.append(_record(b"first"))
        carrier.append(_record(b"second"))

    path.write_bytes(path.read_bytes()[: HEADER_BYTES + _SLOT + 10])

    with Carrier(path) as carrier, pytest.raises(RecordFormatError, match="截断"):
        list(carrier.scan())


def test_sealed_is_a_threshold_judgement(tmp_path: Path):
    """封口是策略判断：达到封口线即"已封口"，且不阻止继续写入大记录。"""
    with Carrier(tmp_path / "p18", slot_bytes=_SLOT) as carrier:
        carrier.append(_record(b"a"))
        assert not carrier.sealed(carrier.size + 1)
        assert carrier.sealed(carrier.size)

        big = _record(b"b" * 500)
        span = carrier.append(big)

        assert carrier.read(span) == big


def test_carrier_exposes_its_path(tmp_path: Path):
    """载体认得自己的路径（桶与巡检要从它推出位置）。"""
    path = tmp_path / "p19"
    with Carrier(path, slot_bytes=_SLOT) as carrier:
        assert carrier.path == path


def test_context_manager_closes_handle(tmp_path: Path):
    """退出 with 即关闭句柄。"""
    with Carrier(tmp_path / "p20", slot_bytes=_SLOT) as carrier:
        carrier.append(_record(b"a"))
    with pytest.raises(ValueError, match="closed"):
        _ = carrier.size

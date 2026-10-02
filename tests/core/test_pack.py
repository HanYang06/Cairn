# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""载体的契约：格算术、记录框定与身份、顺扫、自校验。

本文件钉五件事：

- **一个块可以跨多个格**：一条记录占几格由总长与格长算出，位置就是头格与末格两个整数；
- **身份随记录走**：每条记录自带 ID（两套凭证、名字、签发时刻），故索引库丢了也能复原
  "这一格是谁"——这是"库丢了能重建"的前提；
- **自校验**：改了载荷里任何一个字节，读出来时当场报错，不把错的内容当成对的返回；
- **载体自描述**：格长写在文件头里，打开时从盘上读，不看配置；
- **位置是投影**：记录里不带位置，它由 `span` 给出。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cbor2
import pytest

from core.exc import HubShapeError, RecordFormatError, SlotError
from core.storage.conf import slot_bytes
from core.storage.db.id import ID
from core.storage.pack import HEADER_SIZE, MAGIC, RECORD_HEAD_SIZE, Pack, frame, unframe
from core.storage.slot import SlotRange, offset_of, span_of

if TYPE_CHECKING:
    from pathlib import Path


def _id(name: str = "notedata") -> ID:
    """一条记录的身份：名字与凭证都由调用方给，内核不代签。"""
    return ID.unbound(name=name)


def _pack(tmp_path: Path, *, slot: int = 512) -> Pack:
    """新建一个载体：路径在临时目录里，格长按用例给。"""
    return Pack(tmp_path / "pack-1", slot_bytes=slot)


def _record_head_size(identity: ID) -> int:
    """记录头的实际长度：定长部分 + 身份段的编码长度。

    **不手算**：身份段的长度随字段值而变，写死一个数字就会在改格式时静默失效。
    """
    segment = cbor2.dumps(identity.to_record(), canonical=True)
    return RECORD_HEAD_SIZE + len(segment)


# ---- 格算术 ----


def test_a_record_occupies_enough_slots_from_its_total_length():
    """一条记录占几格由总长与格长算出：向上取整，**一条记录至少占一格**。"""
    assert span_of(1, slot=512) == SlotRange(0, 0)
    assert span_of(512, slot=512) == SlotRange(0, 0)
    assert span_of(513, slot=512) == SlotRange(0, 1)
    assert span_of(1024, slot=512) == SlotRange(0, 1)
    assert span_of(1025, slot=512) == SlotRange(0, 2)


def test_slot_range_size_and_length_agree():
    """`size` 与 `len()` 同义，都是"占了几格"。"""
    span = SlotRange(3, 7)
    assert span.size == 5
    assert len(span) == 5


def test_offset_arithmetic_starts_after_the_file_header():
    """偏移 = 文件头长度 + 格号 × 格长；**文件头不必凑成整格**。"""
    assert offset_of(0, head=24, slot=512) == 24
    assert offset_of(2, head=24, slot=512) == 24 + 1024


def test_span_and_offset_reject_illegal_numbers():
    """总长、格长、格号写歪了当场报错，不返回一个"看起来对"的数。"""
    with pytest.raises(SlotError):
        span_of(0, slot=512)
    with pytest.raises(SlotError):
        span_of(100, slot=0)
    with pytest.raises(SlotError):
        offset_of(-1, head=24, slot=512)
    with pytest.raises(SlotError):
        offset_of(0, head=24, slot=0)


def test_slot_size_comes_from_the_two_tiers_summed(monkeypatch: pytest.MonkeyPatch) -> None:
    """格长是两档之和：不写的档算零，**写 1 KB + 1 B 就是 1025 字节**。

    这里 monkeypatch 的是**配置面那一个读口**（两档声明与相加都在 `core.storage.conf`），
    故不必去动真的值文件。
    """

    def one_of_each_tier(path: str) -> int:
        """字节档与千字节档各给 1；本层没有别的档。"""
        return 1 if path in {"slot.max.byte.b", "slot.max.byte.kb"} else 0

    monkeypatch.setattr("core.storage.conf.conf", one_of_each_tier)

    assert slot_bytes() == 1025


# ---- 文件头 ----


def test_a_new_pack_writes_a_header_with_the_magic_and_slot_size(tmp_path: Path):
    """文件头（24 字节）装魔数与格长：故**载体自描述**，只凭这个文件就能算偏移。"""
    pack = _pack(tmp_path, slot=4096)
    raw = pack.path.read_bytes()
    assert raw[:8] == MAGIC
    assert len(raw) == HEADER_SIZE
    layout = pack.layout()
    assert layout.head == HEADER_SIZE
    assert layout.slot == 4096
    assert pack.size == HEADER_SIZE


def test_opening_a_pack_reads_the_slot_size_from_its_header(tmp_path: Path):
    """格长**写的时候定、读的时候从文件头读回来**：改配置不会让已落盘的载体错位。"""
    path = tmp_path / "pack-1"
    Pack(path, slot_bytes=2048).append(_id("body"), b"hello")

    reopened = Pack.open(path)

    assert reopened.layout().slot == 2048
    assert reopened.size == HEADER_SIZE + 2048


def test_opening_rejects_a_file_that_is_not_a_pack(tmp_path: Path):
    """魔数不符即报错：不推断，也不当作"此处没有载体"。"""
    path = tmp_path / "stranger"
    path.write_bytes(b"not a pack at all, really not")
    with pytest.raises(HubShapeError, match="魔数"):
        Pack.open(path)


def test_opening_rejects_a_truncated_header(tmp_path: Path):
    """文件头不完整同样报错，不按能读到的那几字节去猜格长。"""
    path = tmp_path / "short"
    path.write_bytes(MAGIC)
    with pytest.raises(HubShapeError, match="不完整"):
        Pack.open(path)


def test_opening_a_missing_pack_reports_it(tmp_path: Path):
    """读路径不建东西：文件不在即报错。"""
    with pytest.raises(HubShapeError, match="不在"):
        Pack.open(tmp_path / "nope")


# ---- 写入与顺扫 ----


def test_records_go_in_and_come_back_whole(tmp_path: Path):
    """写进去、顺扫出来，载荷一个字节不差；身份也一并回来了。"""
    pack = _pack(tmp_path)
    identity = _id("notedata")
    first = pack.append(identity, b"a")
    second = pack.append(_id("body"), b"x" * 600)

    scanned = list(pack.scan())

    assert [record.payload for record in scanned] == [b"a", b"x" * 600]
    assert [record.span for record in scanned] == [first, second]
    assert scanned[0].identity.value_uuid == identity.value_uuid
    assert scanned[0].identity.name == "notedata"


def test_a_record_larger_than_one_slot_spans_several_slots(tmp_path: Path):
    """一个块跨多个格：600 字节的记录在 512 格里占两格，尾部补零，下一格从格边界起。"""
    pack = _pack(tmp_path)
    span = pack.append(_id(), b"x" * 600)

    assert len(span) == 2
    assert pack.size == HEADER_SIZE + 2 * 512
    assert next(iter(pack.scan())).span == span


def test_records_start_on_slot_boundaries(tmp_path: Path):
    """下一条记录从上一条占满的格之后开始：**定位没有第二套口径**，不存在"格内偏移"。"""
    pack = _pack(tmp_path)
    first = pack.append(_id(), b"a")
    second = pack.append(_id(), b"b" * 700)

    assert first == SlotRange(0, 0)
    assert second == SlotRange(1, 2)


def test_an_empty_pack_scans_to_nothing(tmp_path: Path):
    """空载体扫出空序列——它是"这里本来就为空"的证据，而不是错误。"""
    assert list(_pack(tmp_path).scan()) == []


def test_an_empty_payload_is_a_legal_record(tmp_path: Path):
    """载荷可以为空：记录头自己就够一格，故它不是"坏记录"。"""
    pack = _pack(tmp_path)
    pack.append(_id(), b"")

    record = next(iter(pack.scan()))
    assert record.payload == b""
    assert record.span == SlotRange(0, 0)


def test_sealing_is_a_policy_not_a_stored_mark(tmp_path: Path):
    """封口是策略判断：文件里没有封印标记，故改了封口线判定随之变，不会与事实不符。"""
    pack = Pack(tmp_path / "pack-1", slot_bytes=512, max_bytes=HEADER_SIZE + 513)
    assert not pack.sealed
    pack.append(_id(), b"x" * 513)
    assert pack.sealed
    assert pack.path.read_bytes()[:8] == MAGIC


def test_appending_refuses_a_file_whose_tail_is_not_a_whole_slot(tmp_path: Path):
    """文件尾不是整格一律拒写：那是残写或外来改动，**不推断续写起点**。"""
    path = tmp_path / "pack-1"
    pack = Pack(path, slot_bytes=512)
    pack.append(_id(), b"hello")
    with path.open("ab") as handle:
        handle.write(b"stray")

    with pytest.raises(RecordFormatError, match="不是整格"):
        Pack.open(path).append(_id(), b"more")


# ---- 自校验 ----


def test_a_flipped_byte_in_a_payload_is_caught(tmp_path: Path):
    """改掉载荷里一个字节即报错：不把错的内容当成对的返回。"""
    path = tmp_path / "pack-1"
    identity = _id()
    Pack(path, slot_bytes=512).append(identity, b"verify me")
    raw = bytearray(path.read_bytes())
    start = HEADER_SIZE + _record_head_size(identity)
    raw[start] ^= 0xFF  # 翻掉载荷的第一个字节
    path.write_bytes(bytes(raw))

    with pytest.raises(RecordFormatError, match="校验和"):
        list(Pack.open(path).scan())


def test_a_record_that_claims_more_than_it_has_is_caught(tmp_path: Path):
    """记录自称的总长超出载体尾部即报错，不读出半条记录当成功。"""
    path = tmp_path / "pack-1"
    Pack(path, slot_bytes=512).append(_id(), b"short")
    raw = bytearray(path.read_bytes())
    raw[HEADER_SIZE : HEADER_SIZE + 4] = (10**6).to_bytes(4, "big")
    path.write_bytes(bytes(raw))

    with pytest.raises(RecordFormatError):
        list(Pack.open(path).scan())


def test_a_broken_identity_segment_is_caught(tmp_path: Path):
    """身份段长度写坏即报错：身份随记录走，读不出身份就没有"这一格是谁"。"""
    path = tmp_path / "pack-1"
    Pack(path, slot_bytes=512).append(_id(), b"payload")
    raw = bytearray(path.read_bytes())
    raw[HEADER_SIZE + 8 : HEADER_SIZE + 12] = (10**6).to_bytes(4, "big")
    path.write_bytes(bytes(raw))

    with pytest.raises(RecordFormatError):
        list(Pack.open(path).scan())


def test_a_tail_that_is_not_a_whole_slot_is_caught_by_scan(tmp_path: Path):
    """顺扫遇到不足一整格的尾部同样报错——残写不静默丢掉。"""
    path = tmp_path / "pack-1"
    Pack(path, slot_bytes=512)
    with path.open("ab") as handle:
        handle.write(b"tail")

    with pytest.raises(RecordFormatError, match="不是整格"):
        list(Pack.open(path).scan())


# ---- 记录框定 ----


def test_framing_round_trips_identity_and_payload():
    """框起来再解开：身份与载荷一字不差。"""
    identity = ID.of(b"payload", name="notedata")
    raw = frame(identity, b"payload")

    restored, total, payload = unframe(raw + b"\x00" * 512, slot=512)

    assert total == len(raw)
    assert payload == b"payload"
    assert restored.value_uuid == identity.value_uuid
    assert restored.value_hash == identity.value_hash
    assert restored.name == "notedata"
    assert restored.birth_time == identity.birth_time


def test_the_record_head_does_not_carry_a_position():
    """位置不入记录：它是投影，扫到记录时位置已经由扫描给出。"""
    identity = ID.of(b"payload", name="notedata")
    raw = frame(identity, b"payload")

    restored, _total, _payload = unframe(raw + b"\x00" * 512, slot=512)

    assert not restored.located


# ---- Slot：一条记录占的那一段 ----


def test_a_slot_is_the_span_a_record_occupies_not_a_single_cell(tmp_path: Path):
    """`Slot` 是"一条记录占的那一段"，故一条跨格记录只对应**一个** slot 对象。"""
    pack = _pack(tmp_path)
    span = pack.append(_id(), b"z" * 1000)

    slot = pack.slot(span.first, span.last)

    assert slot.first == 0
    assert slot.last == span.last
    assert slot.count == len(span)
    assert len(slot) == len(span)
    assert slot.pack is pack
    assert slot.span == span


def test_a_slot_reports_where_it_sits_without_reading_the_disk(tmp_path: Path):
    """偏移与总字节数都由文件头的格长算出：同一个对象上这两项是派生的，不是存的。"""
    pack = _pack(tmp_path)
    pack.append(_id(), b"a" * 600)
    second = pack.append(_id(), b"b" * 10)

    slot = pack.slot(second.first, second.last)

    assert slot.offset == HEADER_SIZE + 2 * 512
    assert slot.byte_size == len(second) * 512
    assert slot.payload() == b"b" * 10
    assert 2 in slot
    assert 0 not in slot


def test_reading_a_span_beyond_the_file_end_is_refused(tmp_path: Path):
    """格区间越界即报错：读到一个不存在的位置不该返回空字节。"""
    pack = _pack(tmp_path)
    pack.append(_id(), b"a")
    with pytest.raises(SlotError, match="越界"):
        pack.slot(5, 6).read()

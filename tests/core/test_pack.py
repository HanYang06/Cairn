# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""载体的契约:格算术,槽头布局,两类槽,原地覆盖,自校验,封口.

本文件钉七件事:

- **一格即一个槽**:地址由 ``文件头长度 + 槽号 × 格长`` 当场算出,不查表;
- **文件头 24 字节**:魔数 ``CairnPk2`` + 格长 + 预留,长度与字段不变;
- **槽头 16 字节**:槽种类 1 + crc32 4 + 内容长度 4 + 预留 7;
- **两类槽**:属性槽(1)可原地覆盖,正文槽(2)只追加;
- **载体上不写身份**:槽头只描述本格,没有归属,片号,世代号,墓碑;
- **自校验**:改了内容里任何一个字节,读出来当场报错,不把错的内容当成对的返回;
- **封口是策略**:文件里没有封印标记,判据是"剩下的地方装不下下一格".
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest

from core.exc import HubShapeError, SlotError, SlotFormatError, SlotTooLargeError
from core.storage.pack import (
    ATTR_SLOT,
    BODY_SLOT,
    EMPTY_SLOT,
    HEADER_SIZE,
    MAGIC,
    SLOT_HEAD_SIZE,
    Pack,
    Slot,
    offset_of,
)

if TYPE_CHECKING:
    from pathlib import Path

_SLOT = 64


def _pack(tmp_path: Path, *, slot: int = _SLOT, max_bytes: int | None = None) -> Pack:
    """新建一个载体:路径在临时目录里,格长按用例给."""
    if max_bytes is None:
        return Pack(tmp_path / "pack-1", slot_bytes=slot)
    return Pack(tmp_path / "pack-1", slot_bytes=slot, max_bytes=max_bytes)


# ---- 格算术 ----


def test_offset_arithmetic_starts_after_the_file_header():
    """偏移 = 文件头长度 + 槽号 × 格长;**文件头不必凑成整格**."""
    assert offset_of(0, slot_bytes=512) == HEADER_SIZE
    assert offset_of(2, slot_bytes=512) == HEADER_SIZE + 1024


def test_offset_arithmetic_rejects_illegal_numbers():
    """格号或格长写歪了当场报错,不返回一个"看起来对"的数."""
    with pytest.raises(SlotError):
        offset_of(-1, slot_bytes=512)
    with pytest.raises(SlotError):
        offset_of(0, slot_bytes=0)


def test_the_slot_head_is_sixteen_bytes():
    """槽头定 16 字节:必需项 9 + 预留 7.格式串写错即当场拦下."""
    assert SLOT_HEAD_SIZE == 16
    assert struct.calcsize(">BII7s") == SLOT_HEAD_SIZE


def test_the_two_slot_kinds_are_distinct_numbers():
    """槽种类只有两种:属性槽与正文槽;没写过的格是第三种(零)."""
    assert len({ATTR_SLOT, BODY_SLOT, EMPTY_SLOT}) == 3
    assert EMPTY_SLOT not in {ATTR_SLOT, BODY_SLOT}


# ---- 文件头 ----


def test_a_new_pack_writes_a_header_with_the_magic_and_slot_size(tmp_path: Path):
    """文件头(24 字节)装魔数与格长:故**载体自描述**,只凭这个文件就能算地址."""
    pack = _pack(tmp_path, slot=4096)

    raw = pack.path.read_bytes()

    assert raw[:8] == MAGIC
    assert raw[:8] == b"CairnPk2", "魔数末位是布局版本号，本次由 1 加到 2"
    assert len(raw) == HEADER_SIZE
    layout = pack.layout()
    assert layout.head == HEADER_SIZE
    assert layout.slot == 4096
    assert pack.size == HEADER_SIZE
    assert pack.slot_count == 0


def test_opening_a_pack_reads_the_slot_size_from_its_header(tmp_path: Path):
    """格长**写的时候定,读的时候从文件头读回来**:改配置不会让已落盘的载体错位."""
    path = tmp_path / "pack-1"
    Pack(path, slot_bytes=2048).append(BODY_SLOT, b"hello")

    reopened = Pack.open(path)

    assert reopened.slot_bytes == 2048
    assert reopened.size == HEADER_SIZE + 2048


def test_opening_rejects_a_file_that_is_not_a_pack(tmp_path: Path):
    """魔数不符即报错:不推断,也不当作"此处没有载体"."""
    path = tmp_path / "stranger"
    path.write_bytes(b"not a pack at all, really not")

    with pytest.raises(HubShapeError, match="魔数"):
        Pack.open(path)


def test_opening_rejects_a_truncated_header(tmp_path: Path):
    """文件头不完整同样报错,不按能读到的那几字节去猜格长."""
    path = tmp_path / "short"
    path.write_bytes(MAGIC)

    with pytest.raises(HubShapeError, match="不完整"):
        Pack.open(path)


def test_opening_a_missing_pack_reports_it(tmp_path: Path):
    """读路径不建东西:文件不在即报错."""
    with pytest.raises(HubShapeError, match="不在"):
        Pack.open(tmp_path / "nope")


def test_a_slot_size_that_cannot_hold_a_head_is_refused(tmp_path: Path):
    """格长装不下槽头即报错:那样的载体连一格内容都放不了."""
    with pytest.raises(SlotError, match="大于槽头"):
        Pack(tmp_path / "pack-1", slot_bytes=SLOT_HEAD_SIZE)


# ---- 写入与顺扫 ----


def test_slots_go_in_and_come_back_whole(tmp_path: Path):
    """写进去,顺扫出来,种类与内容一个字节不差."""
    pack = _pack(tmp_path)
    first = pack.append(ATTR_SLOT, b"a")
    second = pack.append(BODY_SLOT, b"x" * 40)

    scanned = list(pack.scan())

    assert [number for number, _slot in scanned] == [0, 1]
    assert [slot.content for _number, slot in scanned] == [b"a", b"x" * 40]
    assert [slot.kind for _number, slot in scanned] == [ATTR_SLOT, BODY_SLOT]
    assert (first, second) == (0, 1)
    assert pack.slot_count == 2
    assert pack.size == HEADER_SIZE + 2 * _SLOT


def test_a_slot_starts_on_a_slot_boundary(tmp_path: Path):
    """下一槽从格边界起:**定位没有第二套口径**,不存在"格内偏移"."""
    pack = _pack(tmp_path)
    pack.append(ATTR_SLOT, b"a")

    assert pack.append(BODY_SLOT, b"b") == 1
    assert pack.size == HEADER_SIZE + 2 * _SLOT


def test_an_empty_pack_scans_to_nothing(tmp_path: Path):
    """空载体扫出空序列——它是"这里本来就为空"的证据,而不是错误."""
    assert list(_pack(tmp_path).scan()) == []


def test_an_empty_content_is_a_legal_slot(tmp_path: Path):
    """内容可以为空:槽头自己就够一格,故它不是"坏槽"."""
    pack = _pack(tmp_path)
    slot = pack.append(ATTR_SLOT, b"")

    read = pack.read(slot)

    assert read.content == b""
    assert read.kind == ATTR_SLOT
    assert pack.size == HEADER_SIZE + _SLOT


def test_content_longer_than_a_slot_is_refused(tmp_path: Path):
    """内容超过"格长减槽头"即报错:**不得静默截断**."""
    pack = _pack(tmp_path)

    with pytest.raises(SlotTooLargeError, match="装不下"):
        pack.append(BODY_SLOT, b"x" * (_SLOT - SLOT_HEAD_SIZE + 1))


def test_a_slot_exactly_filling_the_room_is_accepted(tmp_path: Path):
    """正好装满可用内容区是合法的:边界不多不少."""
    pack = _pack(tmp_path)

    slot = pack.append(BODY_SLOT, b"x" * (_SLOT - SLOT_HEAD_SIZE))

    assert len(pack.read(slot).content) == _SLOT - SLOT_HEAD_SIZE


def test_sealing_is_a_policy_not_a_stored_mark(tmp_path: Path):
    """封口是策略判断:文件里没有封印标记,故改了封口线判定随之变,不会与事实不符."""
    pack = Pack(tmp_path / "pack-1", slot_bytes=_SLOT, max_bytes=HEADER_SIZE + _SLOT + 1)
    assert not pack.sealed

    pack.append(ATTR_SLOT, b"x" * 10)

    assert pack.sealed, "剩下的地方装不下下一格"
    assert pack.path.read_bytes()[:8] == MAGIC


def test_a_pack_with_room_left_is_not_sealed(tmp_path: Path):
    """还剩格子就不该封:封口线只管"下一次换不换文件"."""
    pack = Pack(tmp_path / "pack-1", slot_bytes=_SLOT, max_bytes=HEADER_SIZE + 2 * _SLOT)

    pack.append(ATTR_SLOT, b"x")

    assert not pack.sealed


# ---- 原地覆盖 ----


def test_an_attr_slot_can_be_overwritten_in_place(tmp_path: Path):
    """属性槽**原地覆盖**:写在同一格号上,位置不变,文件不增长."""
    pack = _pack(tmp_path)
    slot = pack.append(ATTR_SLOT, b"first")
    size = pack.size

    pack.overwrite(slot, ATTR_SLOT, b"second")

    assert slot == 0
    assert pack.size == size, "覆盖不追加一个字节"
    assert pack.read(slot).content == b"second"


def test_overwriting_a_slot_that_was_never_written_is_refused(tmp_path: Path):
    """覆盖只发生在已写过的格上:没写过就没有"原地"可言."""
    pack = _pack(tmp_path)
    pack.append(ATTR_SLOT, b"a")

    with pytest.raises(SlotError, match="已写过的格"):
        pack.overwrite(5, ATTR_SLOT, b"b")


def test_writing_behind_the_end_pads_with_zero_slots(tmp_path: Path):
    """写到文件尾之后即补零拉长:格号由调用方给定,这正是"地址是算术"的用法."""
    pack = _pack(tmp_path)

    pack.write_at(2, BODY_SLOT, b"far")

    assert pack.slot_count == 3
    assert pack.read(0).kind == EMPTY_SLOT
    assert pack.read(2).content == b"far"


def test_a_negative_slot_number_is_refused(tmp_path: Path):
    """槽号不能为负."""
    with pytest.raises(SlotError, match="不能为负"):
        _pack(tmp_path).write_at(-1, ATTR_SLOT, b"x")


def test_reading_beyond_the_file_end_is_refused(tmp_path: Path):
    """槽号越界即报错:读到一个不存在的位置不该返回空字节."""
    pack = _pack(tmp_path)
    pack.append(ATTR_SLOT, b"a")

    with pytest.raises(SlotError, match="越界"):
        pack.read(5)


def test_a_closed_pack_refuses_to_write(tmp_path: Path):
    """关掉的载体不再写."""
    pack = _pack(tmp_path)
    pack.close()

    with pytest.raises(HubShapeError, match="已关闭"):
        pack.append(ATTR_SLOT, b"x")


# ---- 自校验 ----


def test_a_flipped_byte_in_the_content_is_caught(tmp_path: Path):
    """改掉内容里一个字节即报错:不把错的内容当成对的返回."""
    path = tmp_path / "pack-1"
    Pack(path, slot_bytes=_SLOT).append(BODY_SLOT, b"verify me")
    raw = bytearray(path.read_bytes())
    raw[HEADER_SIZE + SLOT_HEAD_SIZE] ^= 0xFF
    path.write_bytes(bytes(raw))

    with pytest.raises(SlotFormatError, match="校验和"):
        Pack.open(path).read(0)


def test_a_content_length_beyond_the_slot_is_caught(tmp_path: Path):
    """内容长度越出格长即报错,不读出半格内容当成功."""
    path = tmp_path / "pack-1"
    Pack(path, slot_bytes=_SLOT).append(BODY_SLOT, b"short")
    raw = bytearray(path.read_bytes())
    raw[HEADER_SIZE + 5 : HEADER_SIZE + 9] = (10**6).to_bytes(4, "big")
    path.write_bytes(bytes(raw))

    with pytest.raises(SlotFormatError, match="越出格长"):
        Pack.open(path).read(0)


def test_a_tail_that_is_not_a_whole_slot_is_refused(tmp_path: Path):
    """文件尾不是整格一律拒写:那是残写或外来改动,**不推断续写起点**."""
    path = tmp_path / "pack-1"
    Pack(path, slot_bytes=_SLOT).append(ATTR_SLOT, b"hello")
    with path.open("ab") as handle:
        handle.write(b"stray")

    with pytest.raises(SlotFormatError, match="不是整格"):
        Pack.open(path).append(ATTR_SLOT, b"more")


def test_the_slot_kind_has_a_readable_name():
    """槽种类有可读名字(诊断用),未知种类不冒充满上."""
    assert Slot(kind=ATTR_SLOT, content=b"").kind_name == "属性槽"
    assert Slot(kind=BODY_SLOT, content=b"").kind_name == "正文槽"
    assert "未知" in Slot(kind=99, content=b"").kind_name


def test_the_layout_reports_what_the_header_says(tmp_path: Path):
    """几何由文件头给出:`layout()` 交出文件头长度与格长,两者都不读配置."""
    layout = _pack(tmp_path, slot=128).layout()

    assert layout.head == HEADER_SIZE
    assert layout.slot == 128


def test_the_content_room_is_the_slot_minus_the_head(tmp_path: Path):
    """一格能装的内容上限 = 格长减槽头."""
    assert _pack(tmp_path, slot=128).content_room == 128 - SLOT_HEAD_SIZE


def test_a_pack_repr_names_itself_without_reading_the_disk(tmp_path: Path):
    """诊断用:名字,格长与当前长度."""
    text = repr(_pack(tmp_path, slot=128))

    assert "pack-1" in text
    assert "128" in text


def test_content_at_skips_the_head(tmp_path: Path):
    """只取内容(跳过槽头)是常用面,单列一个入口."""
    pack = _pack(tmp_path)
    slot = pack.append(BODY_SLOT, b"payload")

    assert pack.content_at(slot) == b"payload"

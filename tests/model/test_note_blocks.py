# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""载体的落盘契约：用**真引擎**跑往返——一个块落两条记录，多个内容字段共处一份内容。

载体继承 ``Block``，故 `save` / `fetch` 都挂在块自己身上，本文件不碰文件、hub 与格。
钉五件事：内容字段按**声明次序**装进同一份内容记录、标量属性跟着块记录往返、
标签表（一个 `Body` 字段的字典）往返后仍能按标签取笔记、**同内容只写一份内容记录**、
以及裸赋值照样落盘。

**缺口**：`NoteLine` 是 dataclass，而 ``cbor2`` 编不出 dataclass，故非空 ``lines``
的完整往返要等 ``py_src/model/note/format/`` 落地——那一层**尚未实现**。
本文件因此不写"非空 `lines` 存得进去"的用例，也不写断言它会失败的用例：
临时限制不该被钉死。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core.storage.db.id import ID
from core.storage.db.payload import decode_block, decode_index, decode_tombstone
from core.storage.engine import Block, Engine, bind
from model.note.types import NoteGroup, NoteTag

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """接上一个干净的引擎，并把这根线接通（用例结束解开并关掉连接）。"""
    instance = Engine(tmp_path / "vault", slot_bytes=512)
    bind(instance)
    yield instance
    bind(None)
    instance.close()


def _is_content(payload: bytes) -> bool:
    """这条载荷是不是**内容记录**：块记录、索引条目与墓碑各有保留键，故要一起比。"""
    return (
        decode_block(payload) is None
        and decode_index(payload) is None
        and decode_tombstone(payload) is None
    )


def _content_records(engine: Engine) -> list[bytes]:
    """盘上的内容记录（含旧字节，故与当前块数无关）。"""
    return [record.payload for record in engine._records() if _is_content(record.payload)]


def _records_named(engine: Engine, name: str) -> list[bytes]:
    """盘上某个表名下的**块记录**（索引条目与墓碑不算）。"""
    return [record.payload for record in engine.block_records() if record.identity.name == name]


def test_a_group_round_trips_both_content_fields(engine: Engine):
    """一个块落两条记录，两个内容字段**按声明次序**装进同一份内容记录。

    故 `notes` 与 `groups` 各自的内容与次序，往返之后都要对得上。
    """
    group = NoteGroup()
    group.notes.extend(["n2", "n1"])
    group.groups.extend(["g1", "g2"])
    identity = group.save()

    bind(None)
    bind(engine)
    fetched = NoteGroup.fetch(identity)

    assert fetched.notes == ["n2", "n1"], "次序即用户摆的顺序，不许排序"
    assert fetched.groups == ["g1", "g2"]
    assert len(_records_named(engine, "notegroup")) == 1, "一个块只有一条块记录"
    assert len(_content_records(engine)) == 1, "两个内容字段共处一份内容记录"


def test_scalar_attributes_round_trip_and_keep_their_class(engine: Engine):
    """标量属性跟着块记录走：往返后值一致，且取回来的是**同一个类**。"""
    group = NoteGroup()
    group.title = "待整理"
    group.collapsed = True
    identity = group.save()

    bind(None)
    bind(engine)
    fetched = NoteGroup.fetch(identity)

    assert isinstance(fetched, NoteGroup)
    assert fetched.title == "待整理"
    assert fetched.collapsed is True


def test_a_tag_table_round_trips_its_entries(engine: Engine):
    """标签表往返：`entries` 是标签 → 笔记 ID 列表，取回来仍能按标签取到笔记。"""
    tag = NoteTag()
    tag.entries["x"] = ["n1", "n2"]
    tag.entries["y"] = ["n2"]
    identity = tag.save()

    bind(None)
    bind(engine)
    fetched = NoteTag.fetch(identity)

    assert isinstance(fetched, NoteTag)
    assert fetched.notes_of("x") == ["n1", "n2"]
    assert fetched.notes_of("y") == ["n2"]
    assert fetched.notes_of("z") == []


def test_storing_the_same_content_again_writes_no_second_content_record(engine: Engine):
    """内容去重：两个 `NoteTag` 的 `entries` 相同，盘上内容记录仍只有一份。"""
    first = NoteTag()
    first.entries["x"] = ["n1"]
    first.save()

    second = NoteTag(ID(NoteTag))
    second.entries["x"] = ["n1"]
    second.save()

    assert len(_records_named(engine, "notetag")) == 2, "两份块记录：身份各自签"
    assert len(_content_records(engine)) == 1, "同内容只写一份内容记录"


def test_a_bare_value_can_be_put_on_a_block(engine: Engine):
    """裸值不在声明之内，但引擎照样落盘（`_fields_of` 会并上实例上多出来的公开字段）。"""
    group = NoteGroup()
    group.z_scratch = "只落盘"  # type: ignore[attr-defined]

    identity = group.save()

    bind(None)
    bind(engine)
    assert Block.fetch(identity).z_scratch == "只落盘"  # type: ignore[attr-defined]

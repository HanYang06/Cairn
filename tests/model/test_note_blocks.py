# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""载体的落盘契约:用**真引擎**跑往返——属性进属性槽,正文进正文槽.

载体继承 ``Block``,故 `save` / `fetch` 都挂在块自己身上,本文件不碰文件,hub 与槽.
钉五件事:多个正文字段按**声明次序**装进正文槽,标量属性跟着属性槽往返,
标签表(一个 `Body` 字段的字典)往返后仍能按标签取笔记,**同内容只写一份正文槽**,
以及裸赋值照样落盘.

**缺口**:`NoteLine` 是 dataclass,而 ``cbor2`` 编不出 dataclass,故非空 ``lines``
的完整往返要等 ``py_src/model/note/format/`` 落地——那一层**尚未实现**.
本文件因此不写"非空 `lines` 存得进去"的用例,也不写断言它会失败的用例:
临时限制不该被钉死.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core.storage.db.id import ID
from core.storage.engine import Block, Engine, bind
from core.storage.pack import BODY_SLOT
from model.note.types import NoteGroup, NoteTag

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_SLOT = 512


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """接上一个干净的引擎,并把这根线接通(用例结束解开并关掉连接)."""
    instance = Engine(tmp_path / "vault", slot_bytes=_SLOT)
    bind(instance)
    yield instance
    bind(None)
    instance.close()


def _body_slots(engine: Engine) -> list[bytes]:
    """盘上的正文槽(含旧字节,故与当前块数无关)."""
    return [slot.content for _hub, _pack, _number, slot in engine.scan() if slot.kind == BODY_SLOT]


def test_a_group_round_trips_both_content_fields(engine: Engine):
    """两个正文字段**按声明次序**装进正文槽:`notes` 与 `groups` 的次序往返后都对得上."""
    group = NoteGroup()
    group.notes.extend(["n2", "n1"])
    group.groups.extend(["g1", "g2"])
    identity = group.save()

    bind(None)
    bind(engine)
    fetched = NoteGroup.fetch(identity)

    assert fetched.notes == ["n2", "n1"], "次序即用户摆的顺序，不许排序"
    assert fetched.groups == ["g1", "g2"]
    assert len(_body_slots(engine)) == 1, "两个正文字段共处一格正文槽"


def test_scalar_attributes_round_trip_and_keep_their_class(engine: Engine):
    """标量属性跟着属性槽走:往返后值一致,且取回来的是**同一个类**."""
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
    """标签表往返:`entries` 是标签 → 笔记 ID 列表,取回来仍能按标签取到笔记."""
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


def test_storing_the_same_content_again_writes_no_second_body_slot(engine: Engine):
    """正文去重:两个 `NoteTag` 的 `entries` 相同,盘上正文槽仍只有一格."""
    first = NoteTag()
    first.entries["x"] = ["n1"]
    first.save()

    second = NoteTag(ID(NoteTag))
    second.entries["x"] = ["n1"]
    second.save()

    assert len(_body_slots(engine)) == 1, "同内容只写一格正文槽"


def test_a_changed_body_appends_a_new_body_slot(engine: Engine):
    """**正文槽只追加**:改一段正文即新建一格,旧的那一格留在载体上."""
    tag = NoteTag()
    tag.entries["x"] = ["n1"]
    tag.save()
    before = len(_body_slots(engine))

    bind(None)
    bind(engine)
    tag.entries["x"] = ["n1", "n2"]
    tag.save()

    assert len(_body_slots(engine)) == before + 1, "新世代落在新的一格上"
    bind(None)
    bind(engine)
    assert NoteTag.fetch(tag.id).notes_of("x") == ["n1", "n2"]


def test_a_bare_value_can_be_put_on_a_block(engine: Engine):
    """裸值不在声明之内,但引擎照样落盘(`_fields_of` 会并上实例上多出来的公开字段)."""
    group = NoteGroup()
    group.z_scratch = "只落盘"  # type: ignore[attr-defined]

    identity = group.save()

    bind(None)
    bind(engine)
    assert Block.fetch(identity).z_scratch == "只落盘"  # type: ignore[attr-defined]


def test_a_deleted_note_takes_its_row_away(engine: Engine):
    """删除 = 摘掉库里那一行:载体上不留标记,正文槽仍在盘上等回收."""
    tag = NoteTag()
    tag.entries["x"] = ["n1"]
    identity = tag.save()
    before = len(_body_slots(engine))

    bind(None)
    bind(engine)
    assert NoteTag.fetch(identity).delete() is True

    assert engine.index.get("notetag", identity.value_uuid) is None
    assert len(_body_slots(engine)) == before, "正文槽那一格还在盘上"

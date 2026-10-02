# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""引擎的契约：身份由调用方给、往返一趟、二元落盘、内容去重、删除。

本文件钉六件事（每一条都是前几轮定下的口径）：

- **没 ID 就没有一切**：对象不递 ID 就没有表、不入库、不与数据库产生任何关系；
- **能力靠继承拿到**：`save` / `fetch` / `delete` 挂在 `Block` 上，上层不碰文件、hub、格；
- **声明在类体上**：`title: str = Attr("")` 让类型与落点同时成立，实例里存的是裸值；
- **一个块落两条记录**：内容记录（按内容寻址）与块记录（指针 + 属性）；
- **去重按内容**：同内容只存一份，另一块只多一条块记录；
- **删除要落盘**：载体是追加写，删除的落法是一条墓碑，只清内存里的位置等于没删。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core.exc import ObjectNotFoundError
from core.storage.db.id import ID
from core.storage.db.payload import decode_block, decode_index, decode_tombstone
from core.storage.engine import Block, Engine, bind
from core.storage.types import Attr, Body

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class NoteData(Block):
    """一篇笔记：身份由调用方给，落点声明在类体上。"""

    # 注：注解写字段的类型（str），右值是声明本身（Attr）；描述符在实例上交出 str。
    title: str = Attr("")  # type: ignore[assignment]
    slug: str = Attr("")  # type: ignore[assignment]
    scratch: str = ""
    lines: list[str] = Body([])  # type: ignore[assignment]

    def __init__(self, id: ID | None = None) -> None:
        """身份可省：省了就是块自己现签一个（`ID(self)`）。"""
        super().__init__(id)


class Plain(Block):
    """没有任何声明字段的块：只有身份。"""

    def __init__(self, id: ID | None = None) -> None:
        """身份可省。"""
        super().__init__(id)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """接上一个干净的引擎，并把这根线接通（用例结束解开并关掉连接）。"""
    instance = Engine(tmp_path / "vault", slot_bytes=512)
    bind(instance)
    yield instance
    bind(None)
    instance.close()


def _note() -> NoteData:
    """造一篇填好的笔记。"""
    note = NoteData(ID(NoteData))
    note.title = "第一篇"
    note.slug = "abc"
    note.scratch = "只落盘、不索引"
    note.lines = ["第一行", "第二行"]
    return note


def _is_content(payload: bytes) -> bool:
    """这条载荷是不是**内容记录**：既不是块记录，也不是索引条目，也不是墓碑。

    三类记录各有自己的保留键，判据要一起比——只比"不是块记录"会把索引条目也算进来。
    """
    return (
        decode_block(payload) is None
        and decode_index(payload) is None
        and decode_tombstone(payload) is None
    )


# ---- 身份由调用方给 ----


def test_a_block_signs_its_own_identity_when_none_is_given():
    """**零参构造是一个块**：不给身份就现签一个（`ID(self)`）——索引块就靠这条路被造出来。"""
    plain = Plain()

    assert plain.id.name == "plain"
    assert plain.id.value_uuid


def test_a_block_refuses_something_that_is_not_an_identity():
    """给的不是 ID 就当场报错，不放过。"""
    with pytest.raises(TypeError, match="必须拿到一个 ID"):
        Plain("not-an-id")  # type: ignore[arg-type]


def test_a_block_still_accepts_an_identity_signed_elsewhere():
    """调用方签好再递进来也认——两条路都通向同一个答案。"""
    identity = ID(NoteData)

    note = NoteData(identity)

    assert note.id is identity


def test_the_table_name_comes_from_the_class_name():
    """**表名只由类的名字算出来**：`class NoteData` → `notedata`，没有第二个口子。"""
    note = NoteData(ID(NoteData))

    assert note.id.name == "notedata"
    assert note.type_name == "notedata"


def test_the_declarations_live_on_the_class():
    """**声明在类体上**：故它与实例里那个值现在是什么无关。"""
    assert NoteData.declared_kinds() == {
        "title": "attr",
        "slug": "attr",
        "lines": "body",
    }
    assert Plain.declared_kinds() == {}


def test_the_identity_gets_its_digest_and_position_filled_in(engine: Engine):  # noqa: ARG001 — 夹具的副作用是接上引擎
    """**摘要与位置由内核回填**：调用方签发的身份只有分配形态与签发时刻。"""
    note = _note()
    assert not note.id.bound
    assert not note.id.located

    identity = note.save()

    assert identity is note.id, "交回来的就是递进去那一个"
    assert identity.value_hash
    assert identity.in_hub == "main"
    assert identity.in_hub_pack
    assert identity.in_pack_slot[1] >= identity.in_pack_slot[0]


def test_a_field_may_be_derived_from_the_identity(engine: Engine):
    """身份在构造时就定了，故派生字段可以照它的内部值算，落盘之后原样读回来。"""
    note = NoteData(ID(NoteData))
    note.slug = note.id.value_uuid[:8]

    identity = note.save()
    bind(None)
    bind(engine)

    assert NoteData.fetch(identity).slug == identity.value_uuid[:8]


# ---- 往返 ----


def test_a_block_round_trips_through_the_disk(engine: Engine):
    """存进去、读回来：每个字段一个不差，身份也一致。"""
    identity = _note().save()

    bind(None)
    bind(engine)
    restored = NoteData.fetch(identity)

    assert isinstance(restored, NoteData)
    assert restored.title == "第一篇"
    assert restored.slug == "abc"
    assert restored.scratch == "只落盘、不索引"
    assert restored.lines == ["第一行", "第二行"]
    assert restored.id.value_uuid == identity.value_uuid
    assert restored.id.value_hash == identity.value_hash
    assert restored.id.birth_time == identity.birth_time


def test_the_restored_fields_are_bare_values(engine: Engine):
    """取回来的字段就是**值本身**：属性是裸值，内容能被比较、迭代、就地增改。"""
    identity = _note().save()

    bind(None)
    bind(engine)
    restored = NoteData.fetch(identity)

    assert isinstance(restored.title, str)
    assert restored.title == "第一篇"
    restored.lines.append("第三行")
    assert restored.lines == ["第一行", "第二行", "第三行"], "内容能就地增改"


def test_a_bare_assignment_is_persisted_too(engine: Engine):
    """裸赋值照样落盘（忠实记录），只是拿不到索引加持。"""
    identity = _note().save()

    bind(None)
    bind(engine)

    assert NoteData.fetch(identity).scratch == "只落盘、不索引"


def test_fetching_an_unknown_identity_reports_it(engine: Engine):  # noqa: ARG001 — 夹具的副作用是接上引擎
    """盘上没有这个身份：报错，不返回一个空壳。"""
    with pytest.raises(ObjectNotFoundError, match="对象不在"):
        Plain.fetch(ID(Plain))


def test_find_returns_none_instead_of_raising(engine: Engine):  # noqa: ARG001 — 夹具的副作用是接上引擎
    """`find` 与 `fetch` 的分别只在要不要抛错。"""
    assert Plain.find(ID(Plain)) is None


def test_an_unknown_table_still_reads_back_degraded(engine: Engine):
    """**不认识的类型一律降级读回**：属性照旧齐全，只是没有那个类的行为方法。"""
    identity = _note().save()

    bind(None)
    bind(engine)
    restored = Block.fetch(identity)

    assert getattr(restored, "title") == "第一篇"  # noqa: B009 — 走基座的降级读回，字段不在基座的类型上


# ---- 一个块落两条记录 ----


def test_a_block_lands_as_two_records(engine: Engine):
    """一个块落成两条记录：**内容记录**与**块记录**，各有各的身份。

    两条判据互斥：带指针保留键的是块记录，其余（含索引条目）都不是。故要两拨都数到，
    就不能在块记录那一拨里找内容记录——那自相矛盾。
    """
    identity = _note().save()

    records = list(engine.scan())
    content = [record for record in records if _is_content(record.payload)]
    blocks = [
        record
        for record in records
        if not _is_content(record.payload) and record.identity.name == "notedata"
    ]

    assert len(content) == 1, "内容记录只有一条"
    assert len(blocks) == 1, "块记录只有一条"
    assert content[0].identity.value_uuid != blocks[0].identity.value_uuid
    assert blocks[0].identity.value_uuid == identity.value_uuid


def test_the_block_record_carries_a_pointer_and_the_attributes(engine: Engine):
    """块记录里是指向内容的指针加块自己的属性；**内容另有记录**。"""
    identity = _note().save()

    found = engine.find_block(identity)

    assert found is not None
    _hub, _pack, _span, payload = found
    assert _is_content(payload) is False, "带保留键的就是块记录"
    assert "第一篇".encode() in payload, "属性在块记录里"
    assert b"cairn.ref" in payload, "指针在块记录里"


def test_the_content_record_is_separate_from_the_block_record(engine: Engine):
    """内容记录装正文、块记录装属性：两条记录各归各。"""
    _note().save()
    content = next(record for record in engine.scan() if _is_content(record.payload))

    assert "第二行".encode() in content.payload
    assert "第一篇".encode() not in content.payload


def test_the_content_record_is_addressed_by_its_content(engine: Engine):
    """内容记录按内容地址去重：同内容只存一份。"""
    first = _note()
    first.title = "第一篇"
    first.save()

    bind(None)
    bind(engine)
    second = NoteData(ID(NoteData))
    second.title = "第二篇"
    second.lines = ["第一行", "第二行"]  # 内容与第一份相同
    second.save()

    records = list(engine.scan())
    content_records = [record for record in records if _is_content(record.payload)]
    block_records = [
        record
        for record in records
        if not _is_content(record.payload) and record.identity.name == "notedata"
    ]

    assert len(content_records) == 1, "同内容只存一份"
    assert len(block_records) == 2, "两个块记录"


def test_two_blocks_sharing_content_still_differ_in_identity(engine: Engine):
    """**块身份随载荷**：同一份内容配上不同属性就是两个块。"""
    first = _note()
    first.title = "第一篇"
    first_id = first.save()

    bind(None)
    bind(engine)
    second = NoteData(ID(NoteData))
    second.title = "第二篇"
    second.lines = ["第一行", "第二行"]
    second_id = second.save()

    assert first_id.value_uuid != second_id.value_uuid
    assert first_id.value_hash != second_id.value_hash


def test_saving_the_same_block_again_only_adds_one_block_record(engine: Engine):
    """同一个块再存一次：内容不重写（去重），只多一条块记录。"""
    note = _note()
    note.save()
    before = len(list(engine.block_records()))

    bind(None)
    bind(engine)
    note.save()
    after = len(list(engine.block_records()))

    assert after == before + 1, "只多了一条块记录"


def test_resaving_a_changed_block_moves_its_identity(engine: Engine):
    """**块身份随载荷**：改了字段再存，摘要跟着变（引擎有权改绑它自己算的那一项）。"""
    note = _note()
    identity = note.save()
    first_hash = identity.value_hash

    bind(None)
    bind(engine)
    note.title = "改过的标题"
    note.save()

    assert identity.value_hash != first_hash
    assert NoteData.fetch(identity).title == "改过的标题"


# ---- 删除 ----


def test_a_deleted_block_does_not_come_back_through_an_older_copy(engine: Engine):
    """删掉一个存过多次的块：**不许从旧副本里复活**。

    同一个身份可以有好几条块记录（每存一次追加一条）。删除标记的是**最后那条**的载荷摘要，
    故判死活只能判那一条——若改成"往回找第一条没被标记的"，删完就会从旧副本里冒出来，
    而且不报错。
    """
    note = _note()
    note.save()
    note.title = "二稿"
    note.save()
    identity = note.id

    assert NoteData.fetch(identity).title == "二稿", "最后写的才是它现在的样子"
    note.delete()

    assert engine.find_block(identity) is None
    assert NoteData.find(identity) is None


def test_deleting_a_block_removes_its_identity(engine: Engine):  # noqa: ARG001 — 夹具的副作用是接上引擎
    """删除摘掉身份：盘上那条记录留着（追加写删不掉），但不再认得它。"""
    identity = _note().save()
    note = NoteData.fetch(identity)

    assert note.delete() is True
    assert Plain.find(identity) is None


def test_deleting_twice_reports_the_second_as_a_no_op(engine: Engine):  # noqa: ARG001 — 夹具的副作用是接上引擎
    """删两次：第二次没东西可删，返回 False，不报错。"""
    identity = _note().save()
    note = NoteData.fetch(identity)
    note.delete()

    assert note.delete() is False


def test_a_tombstone_is_left_on_the_disk(engine: Engine):
    """**删除要落盘**：追加一条墓碑，而不是只清内存里的位置。"""
    identity = _note().save()
    before = len(list(engine.scan()))
    NoteData.fetch(identity).delete()

    assert len(list(engine.scan())) == before + 1, "只多了一条墓碑"
    assert engine.tombstones(), "墓碑里记着被删那一条的载荷摘要"


# ---- 那根线 ----


def test_an_unbound_engine_refuses_to_work():
    """还没接引擎就 `save()`：报错，不静默什么都不做。"""
    bind(None)

    with pytest.raises(RuntimeError, match="还没有接上引擎"):
        _note().save()


def test_two_engines_cannot_be_bound_at_once(tmp_path: Path):
    """一个进程只接一个引擎：不静默切库。"""
    bind(None)
    first = Engine(tmp_path / "a")
    second = Engine(tmp_path / "b")
    bind(first)

    with pytest.raises(RuntimeError, match="只接一个引擎"):
        bind(second)
    bind(None)

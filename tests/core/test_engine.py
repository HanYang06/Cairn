# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""引擎的契约：一个块占属性槽与正文槽、只写动过的域、按摘要去重、正文历史、删除。

本文件钉七件事（每一条都是 2026-10-02 裁定定下的口径）：

- **一个块占两类槽**：属性槽装全部属性、**可原地覆盖**；正文槽装正文分片、**只追加**；
- **只写它动过的域**：属性变了原地覆盖同一格，正文变了才追加新槽；
- **去重只针对正文**：按摘要查 `BodyIndex`，命中即引用同一份正文的段；
- **正文历史按槽**：改一段正文即新建槽，旧世代进库里那一列，保留世代数取配置；
- **删除 = 摘行**：载体上不留标记，删除之后按身份读回来显式报"对象不在"；
- **读路径没有顺扫回退**：库里没有那一行即报错；
- **不认识的类型降级读回**：属性照旧齐全，只是没有那个类的行为方法。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core.exc import ObjectNotFoundError
from core.storage.db.id import ID
from core.storage.engine import Block, Engine, bind, content_digest
from core.storage.pack import ATTR_SLOT, BODY_SLOT
from core.storage.types import Attr, Body

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

_SLOT = 512


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
    instance = Engine(tmp_path / "vault", slot_bytes=_SLOT)
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


def _kind_counts(engine: Engine) -> dict[int, int]:
    """盘上每种槽各有多少格。"""
    found: dict[int, int] = {}
    for _hub, _pack, _number, slot in engine.scan():
        found[slot.kind] = found.get(slot.kind, 0) + 1
    return found


def _block_slots(engine: Engine, identity: ID) -> list[tuple[int, bytes]]:
    """这个块自己那几格：（槽种类，内容），按位置段顺序。

    索引块的正表行也占属性槽，故数"这个块占了几格"必须按它自己的位置段来，
    不能拿全库的属性槽计数。
    """
    return [(slot.kind, slot.content) for slot in engine.scan_slots(identity)]


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


def test_a_field_may_be_derived_from_the_identity(engine: Engine):
    """身份在构造时就定了，故派生字段可以照它的内部值算，落盘之后原样读回来。"""
    note = NoteData(ID(NoteData))
    note.slug = note.id.value_uuid[:8]

    identity = note.save()

    bind(None)
    bind(engine)

    assert NoteData.fetch(identity).slug == identity.value_uuid[:8]


# ---- 一个块占两类槽 ----


def test_a_block_lands_as_one_attr_slot_and_one_body_slot(engine: Engine):
    """一个块落成两类槽：**属性槽一格，正文槽一格**，两者各有各的写法。

    位置段的次序是**正文槽在前、属性槽在后**：属性槽那一段另记一列（`attr_in_pack_slot`），
    故次序只影响读出来的先后，不影响切分。
    """
    identity = _note().save()

    held = _block_slots(engine, identity)

    assert [kind for kind, _content in held] == [BODY_SLOT, ATTR_SLOT]
    assert identity.attr_slots == 1, "全部属性装进一格"


def test_the_attr_slot_carries_the_attributes(engine: Engine):
    """属性槽里装着块的属性；**正文不在属性槽里**。"""
    identity = _note().save()

    _hub, _pack, _segments, attrs = engine.find_block(identity)

    assert "第一篇".encode() in attrs
    assert "第二行".encode() not in attrs


def test_the_body_slot_carries_the_body(engine: Engine):
    """正文槽里装着正文；**属性不在正文槽里**。"""
    identity = _note().save()

    body = [content for kind, content in _block_slots(engine, identity) if kind == BODY_SLOT]

    assert len(body) == 1
    assert "第二行".encode() in body[0]
    assert "第一篇".encode() not in body[0]


def test_the_position_covers_both_slots(engine: Engine):  # noqa: ARG001 — 夹具的副作用是接上引擎
    """位置段覆盖该块占用的**全部槽**（属性槽与正文槽），改一次写一次。

    **索引块那条正表行占的槽不在其中**：它属于索引块，写在索引块自己那张表里。
    """
    identity = _note().save()

    assert identity.in_hub == "main"
    assert identity.in_hub_pack
    assert identity.attr_slots == 1
    assert identity.attr_span, "属性槽要切得出来"
    assert identity.body_span, "正文槽要切得出来"
    assert len(identity.slots) == 2, "属性槽一格加正文槽一格"
    assert set(identity.slots) == set(_expand(identity.attr_span, identity.body_span))


def _expand(*groups: Iterable[int | tuple[int, int]]) -> list[int]:
    """把若干段列表展开成一串槽号（用例里的取证助手）。"""
    found: list[int] = []
    for group in groups:
        for item in group:
            if isinstance(item, int):
                found.append(item)
            else:
                found.extend(range(item[0], item[1] + 1))
    return found


def test_the_segments_cover_a_scattered_position(engine: Engine):  # noqa: ARG001 — 夹具的副作用是接上引擎
    """位置段是**段列表**：一段连续的格写一个区间，零散的单格逐个写。"""
    identity = ID(NoteData, value_uuid="u")
    identity.place(hub="main", pack="p", spans=[0, 5, 6, 9])

    assert identity.in_pack_slot == [0, (5, 6), 9]


# ---- 只写动过的域 ----


def test_changing_only_an_attribute_overwrites_the_same_slot(engine: Engine):
    """**属性槽原地覆盖**：改一个属性不产生新槽，正文槽一动不动。"""
    note = _note()
    note.save()
    before = _block_slots(engine, note.id)

    bind(None)
    bind(engine)
    note.title = "改过的标题"
    note.save()

    after = _block_slots(engine, note.id)
    assert [kind for kind, _content in after] == [BODY_SLOT, ATTR_SLOT]
    assert len(after) == len(before), "槽数不变：属性是原地覆盖的"
    assert "改过的标题".encode() in after[-1][1], "属性槽在末尾那一段"


def test_changing_the_body_appends_a_new_slot(engine: Engine):
    """**正文槽只追加**：改一段正文即新建槽，位置段指向新槽，旧世代留在载体上。"""
    note = _note()
    note.save()
    identity = note.id
    first = identity.body_span
    before = _kind_counts(engine)

    bind(None)
    bind(engine)
    note.lines = ["第一行", "改过的第二行"]
    note.save()

    assert identity.body_span != first, "新世代落在新槽上"
    assert _kind_counts(engine)[BODY_SLOT] == before[BODY_SLOT] + 1, "旧世代没被改写"
    bind(None)
    bind(engine)
    assert NoteData.fetch(identity).lines == ["第一行", "改过的第二行"]


def test_saving_an_unchanged_block_writes_nothing_new(engine: Engine):
    """同一份内容再存一次：正文按摘要命中，不重复写槽；属性原地覆盖同一格。"""
    note = _note()
    note.save()
    identity = note.id
    before_attr = identity.attr_span
    before_body = identity.body_span

    bind(None)
    bind(engine)
    note.save()

    assert identity.attr_span == before_attr, "属性槽原地覆盖，位置不变"
    assert identity.body_span == before_body, "正文按摘要命中，不写新槽"


def test_the_history_keeps_the_current_generation_by_default(engine: Engine):
    """保留世代数取配置（开箱 1）：只留当前世代，故正文历史是空的。"""
    note = _note()
    note.save()
    identity = note.id

    bind(None)
    bind(engine)
    note.lines = ["一"]
    note.save()

    assert identity.body_history == [], "深度为 1 时不留旧世代"
    assert NoteData.fetch(identity).lines == ["一"]


# ---- 去重只针对正文 ----


def test_the_same_body_is_written_once(engine: Engine):
    """同内容只写一份：两个块共用一份正文，盘上的正文槽仍是一格。"""
    first = _note()
    first.save()

    bind(None)
    bind(engine)
    second = NoteData(ID(NoteData))
    second.title = "第二篇"
    second.lines = ["第一行", "第二行"]  # 正文与第一份相同
    second.save()

    bodies = [slot for _hub, _pack, _number, slot in engine.scan() if slot.kind == BODY_SLOT]

    assert len(bodies) == 1, "同内容只写一份正文"
    assert second.id.body_span, "第二个块确实指着一格正文槽"
    bind(None)
    bind(engine)
    assert NoteData.fetch(second.id).lines == ["第一行", "第二行"]


def test_two_blocks_sharing_content_differ_in_identity(engine: Engine):
    """**身份与内容无关**：同一份正文配上不同属性就是两个身份。"""
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
    assert content_digest(first) == content_digest(second)


def test_a_bare_assignment_is_not_deduplicated(engine: Engine):
    """**裸赋值不去重**：两次写入各占一格，与正文的判据不是同一条。"""
    first = Plain(ID(Plain))
    first.note = "同一段文字"  # type: ignore[attr-defined]
    first.save()

    bind(None)
    bind(engine)
    second = Plain(ID(Plain))
    second.note = "同一段文字"  # type: ignore[attr-defined]
    second.save()

    assert first.id.slots != second.id.slots, "两次写入各占一格，不去重"


# ---- 读回 ----


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
    assert restored.id.birth_time == identity.birth_time


def test_the_restored_fields_are_bare_values(engine: Engine):
    """取回来的字段就是**值本身**：正文能被比较、迭代、就地增改。"""
    identity = _note().save()

    bind(None)
    bind(engine)
    restored = NoteData.fetch(identity)

    assert isinstance(restored.title, str)
    restored.lines.append("第三行")
    assert restored.lines == ["第一行", "第二行", "第三行"], "正文能就地增改"


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

    assert getattr(restored, "title") == "第一篇"  # noqa: B009 — 走基座的降级读回


def test_reading_a_block_without_an_index_row_is_refused(engine: Engine):
    """**读路径没有顺扫回退**：库里没有那一行即显式报错。"""
    identity = _note().save()
    engine.index.drop_row("notedata", identity.value_uuid)

    with pytest.raises(ObjectNotFoundError, match="对象不在"):
        engine.find_block(identity)


def test_a_missing_pack_is_reported_as_not_found(engine: Engine):
    """载体不见了也报"对象不在"：读路径不建东西，也不返回半截。"""
    identity = _note().save()
    for pack in (engine.root / "main" / "packs").iterdir():
        pack.unlink()

    with pytest.raises(ObjectNotFoundError, match="对象不在"):
        engine.load(identity)


def test_scan_slots_gives_the_raw_slot_contents(engine: Engine):
    """命令面要的原文：按位置段次序交出每一格的种类与内容。"""
    identity = _note().save()

    held = engine.scan_slots(identity)

    assert [slot.kind for slot in held] == [BODY_SLOT, ATTR_SLOT]


def test_scan_slots_refuses_an_unknown_identity(engine: Engine):
    """没有那一行即报错，不交出空列表。"""
    with pytest.raises(ObjectNotFoundError, match="对象不在"):
        engine.scan_slots(ID(Plain))


# ---- 删除 ----


def test_deleting_a_block_takes_the_row_away(engine: Engine):
    """删除 = **摘掉索引库那一行**：载体上不留任何标记。"""
    identity = _note().save()
    before = _kind_counts(engine)

    note = NoteData.fetch(identity)

    assert note.delete() is True
    assert engine.index.get("notedata", identity.value_uuid) is None
    assert _kind_counts(engine) == before, "载体上不追加任何东西"
    assert Plain.find(identity) is None


def test_deleting_twice_reports_the_second_as_a_no_op(engine: Engine):  # noqa: ARG001 — 夹具接上引擎
    """删两次：第二次没东西可删，返回 False，不报错。"""
    identity = _note().save()
    note = NoteData.fetch(identity)
    note.delete()

    assert note.delete() is False


def test_a_deleted_block_does_not_come_back(engine: Engine):  # noqa: ARG001 — 夹具的副作用是接上引擎
    """删掉之后按身份读回来显式报错：**没有旧副本复活这条路**。"""
    identity = _note().save()
    NoteData.fetch(identity).delete()

    with pytest.raises(ObjectNotFoundError, match="对象不在"):
        NoteData.fetch(identity)


def test_deleting_an_unknown_identity_reports_false(engine: Engine):  # noqa: ARG001 — 夹具的副作用是接上引擎
    """没这个身份即返回 False，不抛错。"""
    assert Plain(ID(Plain)).delete() is False


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


def test_an_engine_repr_names_its_root(engine: Engine):
    """诊断用：库根与默认 hub。"""
    assert "main" in repr(engine)
    assert "vault" in repr(engine)


def test_an_engine_opens_its_index_lazily(tmp_path: Path):
    """索引库**惰性开**：还没用过它，库文件就不该存在。"""
    instance = Engine(tmp_path / "vault", slot_bytes=_SLOT)

    assert not instance.catalog_path.is_file()
    assert instance.index.path.is_file()
    instance.close()

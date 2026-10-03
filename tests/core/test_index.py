# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""索引契约:两类正表,**由正表现算反表**,索引块本身也是块,缺位即退化.

本文件钉六件事:

- **用了声明就必然进**:`Attr` 进属性索引,`Body` 进正文索引,没有开关;
- **正表存,反表现算**:正表行落在载体的槽上,反表是读的时候翻出来的;
- **索引块本身是块**:它有身份,故它自己也有表(`attrindex` / `bodyindex`)——
  索引一多,光靠名字找不到它,必须进库;
- **值的类型参与判据**:`1`,`False`,`"0"` 不是同一个值;
- **正文索引能答引用数**:多少块在用这份正文;
- **缺位即退化,数据不丢**:拿掉索引行,块照样按身份读得回来.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core.storage.db.id import ID
from core.storage.engine import Block, Engine, bind, content_digest
from core.storage.index.attrindex import AttrIndex
from core.storage.index.bodyindex import BodyIndex
from core.storage.index.index import CONTENT_FIELD, owners, table_of
from core.storage.types import Attr, Body

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_SLOT = 512


class NoteData(Block):
    """一篇笔记:一个可索引属性,一段正文,一个裸赋值."""

    title: str = Attr("")  # type: ignore[assignment]
    lines: list[str] = Body([])  # type: ignore[assignment]
    scratch: str = ""

    def __init__(self, id: ID) -> None:
        """只收身份."""
        super().__init__(id)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """接上一个干净的引擎(用例结束解开并关连接)."""
    instance = Engine(tmp_path / "vault", slot_bytes=_SLOT)
    bind(instance)
    yield instance
    bind(None)
    instance.close()


def _note(title: str = "", lines: list[str] | None = None) -> NoteData:
    """造一篇笔记."""
    note = NoteData(ID(NoteData))
    note.title = title
    note.lines = [] if lines is None else lines
    return note


def _ids(rows: tuple[dict[str, object], ...]) -> set[object]:
    """把翻出来的行收成一组块身份."""
    return {row["value_uuid"] for row in rows}


# ---- 两类索引 ----


def test_an_attr_declaration_lands_in_the_attribute_index(engine: Engine):
    """写了 `Attr(...)` 就进属性索引——**用了就是"要按它查"**,没有开关."""
    identity = _note("标题").save()

    rows = engine.index_engine.search(AttrIndex, "title", "标题")

    assert _ids(rows) == {identity.value_uuid}


def test_a_bare_assignment_stays_out_of_the_index(engine: Engine):
    """裸赋值照样落盘,但**不进索引**:它不是"声明了却不索引",是根本没声明."""
    note = _note("标题")
    note.scratch = "不索引"
    note.save()

    assert engine.index_engine.search(AttrIndex, "scratch", "不索引") == ()
    restored = engine.load(note.id)
    assert restored.__dict__.get("scratch") == "不索引", "但它确实落盘了"


def test_a_body_declaration_lands_in_the_content_index(engine: Engine):
    """写了 `Body(...)` 就进正文索引:**正表行是"摘要 → 位置"**,不是"哪个块提过它"."""
    note = _note("标题", ["第一行"])
    identity = note.save()
    place = content_digest(note)
    assert place is not None

    rows = engine.index_engine.search(BodyIndex, CONTENT_FIELD, place)

    assert len(rows) == 1
    assert rows[0]["value"] == f"str:{place}", "正表行里那一列就是摘要"
    assert rows[0]["hub"] == identity.in_hub, "位置是跨 pack / hub 的坐标"
    assert rows[0]["pack"] == identity.in_hub_pack
    assert rows[0]["segments"]
    assert "value_uuid" not in rows[0], "位置不挂在某个块身上"


def test_the_content_index_answers_the_holders(engine: Engine):
    """**谁在用它由摘要链现算**:正文索引只答位置,故"几个块在引用"要扫各块的摘要链."""
    first_note = _note("甲", ["同一份"])
    second_note = _note("乙", ["同一份"])
    first_note.save()
    second_note.save()
    place = content_digest(first_note)
    assert place is not None

    holders = engine.index_engine.holders(place)

    assert {str(row["value_uuid"]) for row in holders} == {
        first_note.id.value_uuid,
        second_note.id.value_uuid,
    }


def test_the_content_index_holds_one_position_per_digest(engine: Engine):
    """同一份正文只落**一条**位置行:第二个块是引用型,它不必再写一行."""
    first_note = _note("甲", ["同一份"])
    second_note = _note("乙", ["同一份"])
    first_note.save()
    second_note.save()
    place = content_digest(first_note)
    assert place is not None

    assert len(engine.index_engine.search(BodyIndex, CONTENT_FIELD, place)) == 1
    assert len(engine.index_engine.holders(place)) == 2, "两个块都在要它"


def test_two_blocks_sharing_a_value_are_both_found(engine: Engine):
    """同一个值命中两条身份:索引是**一对多**,不是覆盖."""
    first = _note("同名").save()
    second = _note("同名").save()

    rows = engine.index_engine.search(AttrIndex, "title", "同名")

    assert _ids(rows) == {first.value_uuid, second.value_uuid}


def test_the_attr_index_still_counts_its_rows(engine: Engine):
    """属性索引那一列还是"一行一个块",故 `count` 照旧数行数."""
    first_note = _note("同名", [])
    second_note = _note("同名", [])
    first_note.save()
    second_note.save()

    assert engine.index_engine.count(AttrIndex, "title", "同名") == 2


# ---- 值的判据 ----


def test_the_type_of_a_value_is_part_of_the_judgement(engine: Engine):
    """`0`,`False`,`"0"` 不是同一个值——判据里带类型名,故不会串."""

    class Counted(Block):
        """一个整数属性."""

        count: int = Attr(0)  # type: ignore[assignment]

        def __init__(self, id: ID) -> None:
            """只收身份."""
            super().__init__(id)

    identity = Counted(ID(Counted)).save()

    assert _ids(engine.index_engine.search(AttrIndex, "count", 0)) == {identity.value_uuid}
    assert engine.index_engine.search(AttrIndex, "count", False) == ()
    assert engine.index_engine.search(AttrIndex, "count", "0") == ()


def test_a_falsy_value_is_still_indexed(engine: Engine):
    """假值也是值:空串照样进索引,不会因为"假"被跳过."""
    identity = _note("").save()

    assert _ids(engine.index_engine.search(AttrIndex, "title", "")) == {identity.value_uuid}


# ---- 索引块本身是块 ----


def test_the_index_blocks_have_their_own_tables(engine: Engine):
    """索引块**本身也是块**:用了 ID 就有表,与任何块同路."""
    _note("标题").save()

    tables = engine.index.tables()

    assert "attrindex" in tables
    assert "bodyindex" in tables
    assert "notedata" in tables


def test_the_index_blocks_are_registered_with_an_identity(engine: Engine):
    """索引块有身份,故它在库里也有行——**索引一多,靠这行才找得到它**."""
    _note("标题").save()

    rows = list(engine.index.rows("attrindex"))

    assert rows, "索引块在它自己的表里有行"
    assert rows[0]["value_uuid"]
    assert rows[0]["in_pack_slot"], "正表行落在载体的槽上，故它的位置段非空"


def test_the_link_from_a_row_back_to_its_block_works(engine: Engine):
    """行里有块身份,故能顺着它把块取回来——这是"按属性查块"那条完整路."""
    identity = _note("可查").save()

    rows = engine.index_engine.search(AttrIndex, "title", "可查")
    restored = NoteData.fetch(ID("notedata", value_uuid=str(rows[0]["value_uuid"])))

    assert restored.title == "可查"
    assert restored.id.value_uuid == identity.value_uuid


def test_the_index_field_names_are_visible(engine: Engine):
    """这类索引里有哪些列可查——界面拿它显示"能按什么查"."""
    _note("标题").save()

    assert "title" in engine.index_engine.field_names(AttrIndex)
    assert "lines" not in engine.index_engine.field_names(AttrIndex), "正文字段不问属性索引"


def test_the_owners_are_found_by_their_own_declaration():
    """索引类型的发现靠 `manages`,不靠继承:两条索引直接继承块,按继承找一个都找不到."""
    found = owners()

    assert AttrIndex in found
    assert BodyIndex in found
    assert table_of(AttrIndex) == "attrindex"
    assert AttrIndex.__dict__["manages"] == "attr"
    assert BodyIndex.__dict__["manages"] == "body"


def test_a_changed_value_leaves_the_old_row_searchable(engine: Engine):
    """块改过值之后,旧那一行仍在盘上,故**查旧值也查得到它**.

    载体只追加,索引块也只追加,故两行并存.反表按(列,值,块身份)去重:
    同一个块同一个值写过多次只算一条,而不同的值各算一条——所以两行都得算数.
    """
    note = _note("初稿")
    note.save()

    bind(None)
    bind(engine)
    note.title = "定稿"
    note.save()

    rows = engine.index_engine.search(AttrIndex, "title", "定稿")
    assert _ids(rows) == {note.id.value_uuid}, "新值命中它"
    assert len(engine.index_engine.search(AttrIndex, "title", "初稿")) == 1, "旧值那一行也还在"


# ---- 缺位即退化,数据不丢 ----


def test_without_the_index_rows_the_block_still_reads_back(engine: Engine):
    """**两个索引块是增强件**:拿掉正表行,按身份照样读得回块——只是按值查不到了."""
    note = _note("标题", ["第一行"])
    identity = note.save()
    engine.index.drop_row("attrindex", _only_row(engine, "attrindex"))
    engine.index.drop_row("bodyindex", _only_row(engine, "bodyindex"))

    assert engine.index_engine.search(AttrIndex, "title", "标题") == ()

    bind(None)
    bind(engine)
    restored = NoteData.fetch(identity)
    assert restored.title == "标题"
    assert restored.lines == ["第一行"]


def _only_row(engine: Engine, table: str) -> str:
    """某张索引表里那一行的凭证(用例里只写一块,故只有一行)."""
    rows = list(engine.index.rows(table))
    assert rows
    return str(rows[0]["value_uuid"])


def test_the_index_block_continues_when_it_is_full(engine: Engine, monkeypatch: pytest.MonkeyPatch):
    """一个索引块写满即续下一块:上限取配置,改它即改"隔多久续一块"."""
    monkeypatch.setattr("core.storage.conf.index_max_bytes", lambda: 1)
    first = _note("甲").save()
    second = _note("乙").save()

    tables = set(engine.index.tables())
    rows = list(engine.index.rows("attrindex"))

    assert "attrindex" in tables
    assert len(rows) >= 2, "两份索引块各占一行"
    assert _ids(engine.index_engine.search(AttrIndex, "title", "甲")) == {first.value_uuid}
    assert _ids(engine.index_engine.search(AttrIndex, "title", "乙")) == {second.value_uuid}

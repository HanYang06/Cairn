# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""笔记载体的契约：登记与建表、属性跟着块走、标签表与分组载荷的形状。

载体是**一写就登记、开库即建表**的那一类，故这里既钉声明（登记表里长什么样），
也钉结果（库里真有那几张表、属性真能往返一趟）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.init import Kernel
from core.storage.format.block import block_attrs
from core.storage.registry import REGISTRY
from core.storage.tablegen import kernel_declarations
from model.note.types import (
    Chunk,
    DiffStep,
    LineContent,
    NoteAsset,
    NoteAssetBody,
    NoteData,
    NoteDiffBody,
    NoteGroup,
    NoteGroupBody,
    NoteLine,
    NoteTag,
    NoteTagTable,
)

if TYPE_CHECKING:
    from pathlib import Path

_NOTE_TABLES = ("noteasset", "notedata", "notediff", "notegroup", "notetag")


# ---- 登记与建表 ----


def test_the_three_carriers_register_themselves_under_note_prefixed_tables():
    """继承即登记；表名带 note 前缀——领域专属的类型以域名开头，project 那边同名也不相干。"""
    tables = {decl.table for decl in REGISTRY.declarations()}
    assert set(_NOTE_TABLES) <= tables
    assert REGISTRY.table("notetag") is not None
    assert isinstance(NoteTag(), NoteTag)


def test_note_data_declares_exactly_its_own_attributes():
    """跟着块走的就是这几个：标题 / 副标题 / 标签 / 两个时间 / 待办，一个不多。"""
    decl = REGISTRY.get("NoteData")
    assert decl is not None
    assert [name for name, _ in decl.attrs] == [
        "title",
        "subtitle",
        "tags",
        "created",
        "updated",
        "todo",
    ]


def test_note_data_declares_nothing_indexed_because_tags_is_a_container():
    """`tags` 是容器，声明它进速查会在声明期被拦下，故这里一个速查属性都不声明。"""
    decl = REGISTRY.get("NoteData")
    assert decl is not None
    assert decl.indexed == ()


def test_a_note_table_carries_identity_columns_plus_the_body_pointer():
    """一张领域表 = 身份列（照搬 ID 的全部字段）+ 指向 body 的两列 + 类型标号。"""
    spec = next(table for table in kernel_declarations() if table.name == "notedata")
    columns = [column.sql_name for column in spec.columns]
    assert "value_uuid" in columns
    assert "kind" in columns
    assert "body_value_uuid" in columns
    assert "body_value_hash" in columns


def test_opening_a_vault_brings_the_note_tables_into_being(tmp_path: Path):
    """开库即建表：'表会自己诞生'这句在领域表上同样成立。"""
    with Kernel.create(tmp_path / "vault") as kernel:
        names = {
            row[0]
            for row in kernel.index.rows._connection.execute(
                "select name from sqlite_master where type = 'table'"
            )
        }
    assert set(_NOTE_TABLES) <= names


# ---- 属性跟着块走 ----


def test_block_attrs_takes_exactly_the_declared_fields():
    """'哪些字段算数'有确定答案：取的是登记里那几个，不靠 `__dict__` 猜。"""
    assert set(block_attrs(NoteData())) == {
        "title",
        "subtitle",
        "tags",
        "created",
        "updated",
        "todo",
    }


def test_attributes_ride_on_the_block_record_and_come_back_unchanged(tmp_path: Path):
    """存一条带属性的笔记，读回来一个不少，且值原样。"""
    note = NoteData(title="标题", subtitle="副题", tags=["#想法"], todo=True)
    with Kernel.create(tmp_path / "vault") as kernel:
        identity = kernel.store(b"body", kind="notedata", attrs=block_attrs(note))
        payload = kernel.storage.block_payload(identity.value_uuid)
    assert payload is not None
    assert payload.attrs["title"] == "标题"
    assert payload.attrs["subtitle"] == "副题"
    assert payload.attrs["tags"] == ["#想法"]
    assert payload.attrs["todo"] is True
    assert payload.attrs["created"] == note.created
    assert payload.attrs["updated"] == note.updated


# ---- 标签表 ----


def test_the_tag_table_sorts_entries_and_finds_members():
    """标签表按名排序（同一份逻辑内容编出的字节唯一），成员查得出来。

    排序是**码点序**：中文标签按码点排，不按拼音——这只需"唯一且稳定"，不需要"好看"。
    """
    table = NoteTagTable.of({"#b": ("n2",), "#a": ("n1", "n2")})
    assert table.names == ("#a", "#b")
    assert table.notes_of("#a") == ("n1", "n2")
    assert table.notes_of("#b") == ("n2",)
    assert table.notes_of("#c") == ()
    assert len(table) == 2


def test_an_empty_tag_table_is_falsy_and_a_memberless_tag_still_exists():
    """空表与'没人用的标签'是两件事：后者留着，回收由领域另判。"""
    assert not NoteTagTable()
    assert NoteTagTable.of(None) == NoteTagTable()
    table = NoteTagTable.of({"#空": ()})
    assert table.names == ("#空",)
    assert table.notes_of("#空") == ()


# ---- 分组 ----


def test_a_group_keeps_both_lists_in_order():
    """一个组一个块：成员与子组都以 ID 出现；顺序即用户摆的顺序，故不排序。"""
    body = NoteGroupBody(notes=("n2", "n1"), groups=("g2", "g1"))
    assert body.notes == ("n2", "n1")
    assert body.groups == ("g2", "g1")


def test_a_group_names_itself_through_a_title_not_a_name():
    """组的名字走 `title`：`name` 是 ID 的可绑字段，用它会被登记成身份列而不是属性。"""
    group = NoteGroup(title="待整理")
    assert group.title == "待整理"
    decl = REGISTRY.get("NoteGroup")
    assert decl is not None
    assert [name for name, _ in decl.attrs] == ["title", "collapsed"]


# ---- 资产 ----


def test_an_asset_declares_the_metadata_and_has_no_chunk_switch():
    """元数据跟着块走；**没有"是否分片"这个字段**——默认就是分片，必然分片。"""
    decl = REGISTRY.get("NoteAsset")
    assert decl is not None
    assert [name for name, _ in decl.attrs] == [
        "mime",
        "size",
        "width",
        "height",
        "duration",
        "timescale",
        "original",
    ]
    assert NoteAsset(mime="image/png").mime == "image/png"


def test_an_asset_body_is_a_chunk_manifest_and_its_size_is_summed():
    """本体是分片清单：字节总数由清单算出来，不另存一份。"""
    body = NoteAssetBody(chunks=(Chunk("c1", 10), Chunk("c2", 32)))
    assert len(body) == 2
    assert body.size == 42
    assert [chunk.id for chunk in body.chunks] == ["c1", "c2"]
    assert NoteAssetBody().size == 0


# ---- 变更链 ----


def test_a_diff_step_keeps_the_line_id_on_the_key_only():
    """行 id 只写在键上：值是 `LineContent`（内容），故同一条事实不写两处。"""
    content = LineContent(data="改过的一行")
    step = DiffStep(hash="h1", lines=(("line-1", content),))
    assert step.lines[0][0] == "line-1"
    assert step.lines[0][1] is content
    assert not hasattr(step.lines[0][1], "id")


def test_a_diff_chain_is_ordered_and_lookup_is_by_hash():
    """链是有序的若干步；按哈希取一步——哈希的用处就是这条连续性。"""
    first = DiffStep(hash="h1", lines=(("line-1", LineContent(data="一")),))
    second = DiffStep(
        hash="h2",
        lines=(("line-1", LineContent(data="二")), ("line-2", LineContent(data="新"))),
    )
    body = NoteDiffBody(steps=(first, second))
    assert len(body) == 2
    assert [step.hash for step in body.steps] == ["h1", "h2"]
    assert body.step("h2") is second
    assert body.step("没有这一步") is None
    assert NoteDiffBody().steps == ()


def test_a_diff_keeps_the_new_content_of_a_real_line():
    """一步里装的是**新内容**：拿一行真造一遍，内容对得上。"""
    line = NoteLine(data="原文")
    changed = NoteLine(id=line.id, data="改后")
    step = DiffStep(hash="h1", lines=((line.id, changed.content),))
    assert step.lines[0][1].data == "改后"

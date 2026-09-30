# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""笔记载体的契约：登记与建表、属性跟着块走、各载体载荷的形状。

载体是**一写就登记、开库即建表**的那一类，故这里既钉声明（登记表里长什么样），
也钉结果（库里真有那几几张表、属性真能往返一趟）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.init import Kernel
from core.storage.format.block import block_attrs
from core.storage.registry import REGISTRY
from core.storage.tablegen import kernel_declarations
from model.note.types import (
    CanvasLink,
    Chunk,
    Figure,
    NoteAsset,
    NoteAssetBody,
    NoteCanvas,
    NoteCanvasBody,
    NoteData,
    NoteGroup,
    NoteGroupBody,
    NoteTag,
    NoteTagTable,
    PlacedShape,
)

if TYPE_CHECKING:
    from pathlib import Path

_NOTE_TABLES = ("noteasset", "notecanvas", "notedata", "notegroup", "notetag")


# ---- 登记与建表 ----


def test_the_carriers_register_themselves_under_note_prefixed_tables():
    """继承即登记；表名带 note 前缀——领域专属的类型以域名开头，project 那边同名也不相干。"""
    tables = {decl.table for decl in REGISTRY.declarations()}
    assert set(_NOTE_TABLES) <= tables
    assert REGISTRY.table("notetag") is not None
    assert isinstance(NoteTag(), NoteTag)


def test_note_data_declares_exactly_its_own_attributes():
    """类体里列的只有它**自己新增**的属性：`id` 与 `body` 来自基类 `Block`。"""
    decl = REGISTRY.get("NoteData")
    assert decl is not None
    assert [name for name, _ in decl.attrs] == [
        "title",
        "subtitle",
        "style",
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
        "style",
        "tags",
        "created",
        "updated",
        "todo",
    }


def test_attributes_ride_on_the_block_record_and_come_back_unchanged(tmp_path: Path):
    """存一条带属性的笔记，读回来一个不少，且值原样。"""
    note = NoteData(
        title="标题",
        subtitle="副题",
        style={"background": "var(--color-bg)"},
        tags=["#想法"],
        todo=True,
    )
    with Kernel.create(tmp_path / "vault") as kernel:
        identity = kernel.store(b"body", kind="notedata", attrs=block_attrs(note))
        payload = kernel.storage.block_payload(identity.value_uuid)
    assert payload is not None
    assert payload.attrs["title"] == "标题"
    assert payload.attrs["subtitle"] == "副题"
    assert payload.attrs["style"] == {"background": "var(--color-bg)"}
    assert payload.attrs["tags"] == ["#想法"]
    assert payload.attrs["todo"] is True
    assert payload.attrs["created"] == note.created
    assert payload.attrs["updated"] == note.updated


# ---- 标签表 ----


def test_the_tag_table_maps_a_tag_to_its_notes_and_is_editable():
    """标签表：标签 → 笔记 ID 的列表，且增删就地做。"""
    table = NoteTagTable(entries={"#a": ["n1", "n2"]})
    table.entries["#b"] = ["n2"]
    assert table.notes_of("#a") == ["n1", "n2"]
    assert table.notes_of("#b") == ["n2"]
    assert table.notes_of("#c") == []
    assert sorted(table.names) == ["#a", "#b"]
    assert len(table) == 2


def test_an_empty_tag_table_is_falsy_and_a_memberless_tag_still_exists():
    """空表与'没人用的标签'是两件事：后者留着，回收由领域另判。"""
    assert len(NoteTagTable()) == 0
    table = NoteTagTable(entries={"#空": []})
    assert table.names == ["#空"]
    assert table.notes_of("#空") == []


# ---- 分组 ----


def test_a_group_keeps_both_lists_in_order():
    """一个组一个块：成员与子组都以 ID 出现；顺序即用户摆的顺序，故不排序。"""
    body = NoteGroupBody(notes=["n2", "n1"], groups=["g2", "g1"])
    body.notes.append("n3")
    assert body.notes == ["n2", "n1", "n3"]
    assert body.groups == ["g2", "g1"]


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
    """本体是分片清单（列表）：字节总数由清单算出来，不另存一份。"""
    body = NoteAssetBody(chunks=[Chunk("c1", 10), Chunk("c2", 32)])
    body.chunks.append(Chunk("c3", 8))
    assert len(body) == 3
    assert body.size == 50
    assert [chunk.id for chunk in body.chunks] == ["c1", "c2", "c3"]
    assert NoteAssetBody().size == 0


# ---- 画板 ----


def test_a_canvas_keeps_shapes_in_painting_order():
    """图编号 → 那一枚图；它是**列表**，因为画的先后是内容（映射的键序会被规范 CBOR 排掉）。"""
    body = NoteCanvasBody(
        shapes=[
            ("1", PlacedShape(figure=Figure(kind="rect", path=[("M", (0.0, 0.0))]))),
            ("2", PlacedShape(figure=Figure(kind="arrow"))),
        ]
    )
    body.shapes.append(("3", PlacedShape(figure=Figure(kind="ellipse"))))
    assert [key for key, _ in body.shapes] == ["1", "2", "3"]
    second = body.shape("2")
    assert second is not None
    assert second.figure.kind == "arrow"
    assert body.shape("9") is None


def test_a_canvas_link_is_semantic_only():
    """连线只记语义（连哪些图 / 怎么连 / 标签 / 线型）：几何归自动布局，故不存折点。"""
    link = CanvasLink(figures=["1", "2"], mode="折线", label="依赖", line="虚线")
    body = NoteCanvasBody(links={"L1": link})
    assert body.link("L1") is link
    assert body.link("L2") is None
    assert not hasattr(link, "points")


def test_a_placed_shape_carries_the_figure_and_its_placement():
    """一枚图 = 图 + 摆放：缩放 / 旋转 / 坐标 / 样式；**没有"关系"字段**（关系由连线表达）。"""
    placed = PlacedShape(
        figure=Figure(kind="bitmap", ref="asset-1"),
        scale=2.0,
        rotation=90.0,
        at=(10.0, 20.0),
        style={"stroke": "var(--color-text)"},
    )
    assert placed.figure.ref == "asset-1"
    assert placed.at == (10.0, 20.0)
    assert placed.style == {"stroke": "var(--color-text)"}
    assert not hasattr(placed, "relation")
    assert NoteCanvas().body.data is None

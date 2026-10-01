# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""笔记载体的契约：声明即形状、表自然诞生、属性跟着块走、载荷只装该装的。

载体是**声明了 ID 的那一类**：`__init__` 里给 `self.id = ID()`，故登记表里有它、开库即建表。
这里既钉声明（登记表里长什么样），也钉结果（库里真有那几张表、属性真能往返一趟）。
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
    NoteCanvas,
    NoteData,
    NoteGroup,
    NoteTag,
    PlacedShape,
)

if TYPE_CHECKING:
    from pathlib import Path

_NOTE_TABLES = ("noteasset", "notecanvas", "notedata", "notegroup", "notetag")

_NOTE_DATA_ATTRS = ["title", "subtitle", "style", "tags", "created", "updated", "todo"]


# ---- 声明与建表 ----


def test_the_carriers_are_declared_under_note_prefixed_tables():
    """表名默认取类名的小写写法：领域专属的类型以域名开头，project 那边同名也不相干。"""
    tables = {decl.table for decl in REGISTRY.declarations()}
    assert set(_NOTE_TABLES) <= tables
    assert REGISTRY.table("notetag") is not None
    assert isinstance(NoteTag(), NoteTag)


def test_a_carrier_reports_its_id_and_so_gets_a_table():
    """**表是 ID 换来的**：`__init__` 里给 `self.id = ID()`，登记表里就自然有了它。"""
    decl = REGISTRY.get("NoteData")
    assert decl is not None
    assert decl.table == "notedata"
    assert decl.owner == "note"
    assert "value_uuid" in decl.ids


def test_note_data_declares_exactly_its_own_attributes():
    """`attrs` 就是它声明过的属性，顺序即书写顺序；载荷字段不在里面。"""
    decl = REGISTRY.get("NoteData")
    assert decl is not None
    assert [name for name, _ in decl.attrs] == _NOTE_DATA_ATTRS
    assert decl.payload == ("lines",)


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
    """'哪些字段算数'有确定答案：取的是登记里那几个，不看 `__dict__`。"""
    assert set(block_attrs(NoteData())) == set(_NOTE_DATA_ATTRS)


def test_attributes_ride_on_the_block_record_and_come_back_unchanged(tmp_path: Path):
    """存一条带属性的笔记，读回来一个不少，且值原样；载荷字段不混进来。"""
    note = NoteData()
    note.title = "标题"
    note.subtitle = "副题"
    note.style = {"background": "var(--color-bg)"}
    note.tags = ["#想法"]
    note.todo = True
    attrs = block_attrs(note)
    with Kernel.create(tmp_path / "vault") as kernel:
        identity = kernel.store(b"body", kind="notedata", attrs=attrs)
        payload = kernel.storage.block_payload(identity.value_uuid)
    assert payload is not None
    assert payload.attrs["title"] == "标题"
    assert payload.attrs["subtitle"] == "副题"
    assert payload.attrs["style"] == {"background": "var(--color-bg)"}
    assert payload.attrs["tags"] == ["#想法"]
    assert payload.attrs["todo"] is True
    assert payload.attrs["created"] == note.created
    assert payload.attrs["updated"] == note.updated
    assert "lines" not in payload.attrs


# ---- 标签表 ----


def test_the_tag_table_maps_a_tag_to_its_notes_and_is_editable():
    """标签表：标签 → 笔记 ID 的列表，且增删就地做。"""
    tag = NoteTag()
    tag.entries["#a"] = ["n1", "n2"]
    tag.entries["#b"] = ["n2"]
    assert tag.notes_of("#a") == ["n1", "n2"]
    assert tag.notes_of("#b") == ["n2"]
    assert tag.notes_of("#c") == []
    assert sorted(tag.names) == ["#a", "#b"]
    assert len(tag) == 2


def test_an_empty_tag_table_is_falsy_and_a_memberless_tag_still_exists():
    """空表与'没人用的标签'是两件事：后者留着，回收由领域另判。"""
    assert len(NoteTag()) == 0
    tag = NoteTag()
    tag.entries["#空"] = []
    assert tag.names == ["#空"]
    assert tag.notes_of("#空") == []


# ---- 分组 ----


def test_a_group_keeps_both_lists_in_order():
    """一个组一个块：成员与子组都以 ID 出现；顺序即用户摆的顺序，故不排序。"""
    group = NoteGroup()
    group.notes.extend(["n2", "n1"])
    group.groups.extend(["g2", "g1"])
    group.notes.append("n3")
    assert group.notes == ["n2", "n1", "n3"]
    assert group.groups == ["g2", "g1"]


def test_a_group_names_itself_through_a_title_not_a_name():
    """组的名字走 `title`：`ID` 自己已经有 `name` 字段（可读名称），再用 `name` 就是同名两义。"""
    group = NoteGroup()
    group.title = "待整理"
    assert group.title == "待整理"
    decl = REGISTRY.get("NoteGroup")
    assert decl is not None
    attrs = [name for name, _ in decl.attrs]
    assert attrs == ["title", "collapsed"]
    assert decl.payload == ("notes", "groups")


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
    assert decl.payload == ("chunks",)
    assert NoteAsset().mime == ""


def test_an_asset_manifest_is_a_list_and_its_size_is_summed():
    """本体是分片清单（列表）：字节总数由清单算出来，`size` 那份只是缓存。"""
    asset = NoteAsset()
    asset.chunks.extend([Chunk("c1", 10), Chunk("c2", 32)])
    asset.chunks.append(Chunk("c3", 8))
    assert len(asset.chunks) == 3
    assert asset.total_bytes() == 50
    assert [chunk.id for chunk in asset.chunks] == ["c1", "c2", "c3"]
    assert NoteAsset().total_bytes() == 0


# ---- 画板 ----


def test_a_canvas_keeps_shapes_in_painting_order():
    """图编号 → 那一枚图；它是**列表**，因为画的先后是内容（映射的键序会被规范 CBOR 排掉）。"""
    canvas = NoteCanvas()
    canvas.shapes.extend(
        [
            ("1", PlacedShape(figure=Figure(kind="rect", path=[("M", (0.0, 0.0))]))),
            ("2", PlacedShape(figure=Figure(kind="arrow"))),
        ]
    )
    canvas.shapes.append(("3", PlacedShape(figure=Figure(kind="ellipse"))))
    assert [key for key, _ in canvas.shapes] == ["1", "2", "3"]
    second = canvas.shape("2")
    assert second is not None
    assert second.figure.kind == "arrow"
    assert canvas.shape("9") is None
    assert NoteCanvas().shapes == []


def test_a_canvas_link_is_semantic_only():
    """连线只记语义（连哪些图 / 怎么连 / 标签 / 线型）：几何归自动布局，故不存折点。"""
    link = CanvasLink(figures=["1", "2"], mode="折线", label="依赖", line="虚线")
    canvas = NoteCanvas()
    canvas.links["L1"] = link
    assert canvas.link("L1") is link
    assert canvas.link("L2") is None
    assert not hasattr(link, "points")
    assert NoteCanvas().links == {}


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

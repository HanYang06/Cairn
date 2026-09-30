# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""行层契约：块行与内容行的写入与改写、hub 登记只认第一次、关系边身份幂等。"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from core.storage.carrier import SlotRange
from core.storage.format.id import ID_FIELDS
from core.storage.index import Index
from core.storage.rows import BlockRow, BodyRow, EdgeRow, Rows
from core.storage.tables import ColumnSource, Declaration, kernel_tables

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def rows(tmp_path: Path) -> Iterator[Rows]:
    """一个开好并对齐的索引库的行层。"""
    with Index.open(tmp_path / "catalog.db", Declaration(kernel_tables()), create=True) as index:
        yield index.rows


def _block(value_uuid: str, *, value_hash: str = "h1", pack: str = "p1") -> BlockRow:
    """造一条块行：ID 的字段 ＋ 指针两列 ＋ 类型标号。"""
    return BlockRow(
        name="",
        value_uuid=value_uuid,
        value_hash=value_hash,
        birth_time=11,
        in_hub="main",
        in_hub_pack=pack,
        in_pack_slot=(3, 5),
        body_value_uuid="bu1",
        body_value_hash="bh1",
        kind="notedata",
    )


def _body(value_uuid: str, *, value_hash: str = "bh1", pack: str = "p1") -> BodyRow:
    """造一条内容行。"""
    return BodyRow(
        name="",
        value_uuid=value_uuid,
        value_hash=value_hash,
        birth_time=11,
        in_hub="main",
        in_hub_pack=pack,
        in_pack_slot=(3, 5),
    )


# ---- 块行 ----


def test_block_roundtrip(rows: Rows):
    """写进去什么，读出来就是什么（含格区间与指针两列）。"""
    row = _block("u1")

    rows.put_block(row)

    assert rows.block("u1") == row
    assert rows.count_blocks() == 1
    assert rows.count_bodies() == 0
    assert rows.count_locations() == 1


def test_the_identity_columns_are_exactly_the_id_fields():
    """表是 ID 的镜像：身份列就是 `ID` 的全部字段，一个不多、一个不少。"""
    block = Declaration(kernel_tables()).table("block")
    body = Declaration(kernel_tables()).table("body")

    assert block is not None
    assert body is not None
    assert (
        tuple(column.name for column in block.columns if column.source is ColumnSource.IDENTITY)
        == ID_FIELDS
    )
    assert (
        tuple(column.name for column in body.columns if column.source is ColumnSource.IDENTITY)
        == ID_FIELDS
    )


def test_every_id_field_survives_the_roundtrip(rows: Rows):
    """ID 的每个字段都能进库、也能原样读回：名字、签发时刻与整段位置。"""
    row = replace(
        _body("b1"),
        name="有名字的体",
        birth_time=7,
        in_hub="far",
        in_hub_pack="p7",
        in_pack_slot=(12, 45),
    )

    rows.put_body(row)

    assert rows.body("b1") == row


def test_put_block_rewrites_position_but_keeps_the_issuing_time(rows: Rows):
    """同身份改写：名字、摘要与位置段跟着变；`birth_time` 保持第一次签发的值。"""
    first = _block("u1")
    rows.put_block(first)

    moved = replace(
        first,
        name="改过名",
        value_hash="h2",
        in_hub="other",
        in_hub_pack="p9",
        in_pack_slot=(8, 9),
        birth_time=99,
    )
    rows.put_block(moved)
    stored = rows.block("u1")

    assert stored is not None
    assert (stored.name, stored.in_hub, stored.in_hub_pack) == ("改过名", "other", "p9")
    assert stored.span == SlotRange(first=8, last=9)
    assert stored.value_hash == "h2"
    assert stored.birth_time == first.birth_time
    assert rows.count_blocks() == 1


def test_unknown_identity_has_no_row(rows: Rows):
    """没写过的身份取不到行。"""
    assert rows.block("nope") is None
    assert rows.body("nope") is None


def test_blocks_by_body_finds_every_referrer(rows: Rows):
    """按内容地址反查块行：同一份内容被哪些块引用（指针落成两列才查得到）。"""
    rows.put_block(_block("u1", value_hash="h1"))
    rows.put_block(
        BlockRow(
            name="",
            value_uuid="u2",
            value_hash="h2",
            birth_time=0,
            in_hub="main",
            in_hub_pack="p2",
            in_pack_slot=(8, 8),
            body_value_uuid="bu9",
            body_value_hash="shared",
        )
    )
    rows.put_body(_body("b1", value_hash="shared"))

    assert [row.value_uuid for row in rows.blocks_by_body("shared")] == ["u2"]
    assert rows.blocks_by_body("missing") == ()


def test_bodies_by_hash_finds_every_identity(rows: Rows):
    """按摘要反查内容行：去重与"按地址读内容"共用这一处。"""
    rows.put_body(_body("b2", value_hash="shared", pack="p1"))
    rows.put_body(_body("b1", value_hash="shared", pack="p2"))
    rows.put_body(_body("b3", value_hash="other"))

    assert [row.value_uuid for row in rows.bodies_by_hash("shared")] == ["b1", "b2"]
    assert rows.bodies_by_hash("missing") == ()
    assert rows.count_bodies() == 3


def test_drop_block_reports_whether_a_row_was_removed(rows: Rows):
    """摘行要能分辨"摘掉了"与"本来就没有"。"""
    rows.put_block(_block("u1"))

    assert rows.drop_block("u1") is True
    assert rows.drop_block("u1") is False
    assert rows.count_blocks() == 0


def test_move_block_changes_only_the_coordinates(rows: Rows):
    """只改坐标：名字、摘要、指针、类型标号与 `birth_time` 都不动。"""
    row = _block("u1")
    rows.put_block(row)

    moved = rows.move_block(
        BlockRow(
            name="被无视的名字",
            value_uuid="u1",
            value_hash="被无视的摘要",
            birth_time=999,
            in_hub="other",
            in_hub_pack="p9",
            in_pack_slot=(40, 41),
            body_value_uuid="被无视的指针",
            body_value_hash="被无视的指针",
            kind="被无视的类型",
        )
    )
    stored = rows.block("u1")

    assert moved is True
    assert stored is not None
    assert (stored.in_hub, stored.in_hub_pack) == ("other", "p9")
    assert stored.span == SlotRange(first=40, last=41)
    assert stored.name == row.name
    assert stored.value_hash == row.value_hash
    assert stored.body_value_hash == row.body_value_hash
    assert stored.kind == row.kind, "类型标号由程序给，挪行不许冲掉它"
    assert stored.birth_time == row.birth_time


def test_move_body_changes_only_the_coordinates(rows: Rows):
    """内容行挪位置同理：身份与摘要都不动。"""
    row = _body("b1")
    rows.put_body(row)

    away = replace(row, in_hub="other", in_hub_pack="p9", in_pack_slot=(40, 41))

    assert rows.move_body(away) is True
    assert rows.body("b1") == away


def test_rows_lists_both_tables_in_position_order(rows: Rows):
    """两张表都能整表列出（巡检与诊断要它）。"""
    rows.put_block(_block("u2", pack="p2"))
    rows.put_block(_block("u1", pack="p1"))
    rows.put_body(_body("b1", pack="p1"))

    assert [row.value_uuid for row in rows.blocks()] == ["u1", "u2"]
    assert [row.value_uuid for row in rows.bodies()] == ["b1"]


# ---- hub 登记 ----


def test_register_hub_is_idempotent(rows: Rows):
    """登记是"这个 hub 存在过"的索引：重复登记是空操作。"""
    assert rows.register_hub("main") is True
    assert rows.register_hub("main") is False

    stored = rows.hub("main")
    assert stored is not None
    assert stored.name == "main"


def test_hubs_are_listed_in_name_order(rows: Rows):
    """登记表按名列出。"""
    rows.register_hub("zeta")
    rows.register_hub("alpha")

    assert [item.name for item in rows.hubs()] == ["alpha", "zeta"]
    assert rows.hub("nope") is None


# ---- 关系边 ----


def test_put_edge_is_idempotent(rows: Rows):
    """边身份即主键：同一关系重复写不产生第二行。"""
    edge = EdgeRow(id="e1", src="a", dst="b", kind="links", domain="note", created=7)

    assert rows.put_edge(edge) is True
    assert rows.put_edge(edge) is False
    assert rows.edges_from("a", "links") == (edge,)


def test_edges_are_queried_by_direction_and_kind(rows: Rows):
    """出边与入边各查各的，且按种类过滤。"""
    rows.put_edge(EdgeRow(id="e1", src="a", dst="b", kind="links", created=1))
    rows.put_edge(EdgeRow(id="e2", src="a", dst="c", kind="tags", created=2))
    rows.put_edge(EdgeRow(id="e3", src="d", dst="b", kind="links", created=3))

    assert [item.id for item in rows.edges_from("a", "links")] == ["e1"]
    assert [item.id for item in rows.edges_from("a", "tags")] == ["e2"]
    assert [item.id for item in rows.edges_to("b", "links")] == ["e1", "e3"]
    assert rows.edges_from("a", "missing") == ()

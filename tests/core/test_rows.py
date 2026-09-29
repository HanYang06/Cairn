# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""行层契约：定位行的写入与改写、hub 登记只认第一次、关系边身份幂等。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core.storage.carrier import SlotRange
from core.storage.index import Index
from core.storage.rows import EdgeRow, Location, Rows
from core.storage.tables import KERNEL_TABLES, Declaration

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def rows(tmp_path: Path) -> Iterator[Rows]:
    """一个开好并对齐的索引库的行层。"""
    with Index.open(tmp_path / "catalog.db", Declaration(KERNEL_TABLES), create=True) as index:
        yield index.rows


def _location(value_uuid: str, *, value_hash: str = "h1", pack: str = "p1") -> Location:
    """造一条定位行。"""
    return Location(
        value_uuid=value_uuid,
        value_hash=value_hash,
        hub="main",
        pack=pack,
        span=SlotRange(first=3, last=5),
        size=512,
        kind="notedata",
        birth_time=11,
        created=22,
        updated=33,
    )


# ---- 定位行 ----


def test_location_roundtrip(rows: Rows):
    """写进去什么，读出来就是什么（含格区间）。"""
    location = _location("u1")

    rows.put_location(location)

    assert rows.location("u1") == location
    assert rows.count_locations() == 1


def test_put_location_rewrites_position_but_keeps_first_write(rows: Rows):
    """同身份改写：位置与摘要跟着变，签发时刻与落下时刻保持第一次的值。"""
    first = _location("u1")
    rows.put_location(first)

    moved = Location(
        value_uuid="u1",
        value_hash="h2",
        hub="main",
        pack="p9",
        span=SlotRange(first=8, last=9),
        size=1024,
        kind="notedata",
        birth_time=99,
        created=999,
        updated=1000,
    )
    rows.put_location(moved)
    stored = rows.location("u1")

    assert stored is not None
    assert stored.pack == "p9"
    assert stored.span == SlotRange(first=8, last=9)
    assert stored.value_hash == "h2"
    assert stored.updated == 1000
    assert stored.created == first.created
    assert stored.birth_time == first.birth_time
    assert rows.count_locations() == 1


def test_unknown_identity_has_no_row(rows: Rows):
    """没写过的身份取不到行。"""
    assert rows.location("nope") is None


def test_locations_by_hash_finds_every_identity(rows: Rows):
    """按摘要反查：同一份内容被哪些身份引用（去重与反查同一处）。"""
    rows.put_location(_location("u2", value_hash="shared", pack="p1"))
    rows.put_location(_location("u1", value_hash="shared", pack="p2"))
    rows.put_location(_location("u3", value_hash="other"))

    found = rows.locations_by_hash("shared")

    assert [item.value_uuid for item in found] == ["u1", "u2"]
    assert rows.locations_by_hash("missing") == ()


def test_drop_location_reports_whether_a_row_was_removed(rows: Rows):
    """摘行要能分辨"摘掉了"与"本来就没有"。"""
    rows.put_location(_location("u1"))

    assert rows.drop_location("u1") is True
    assert rows.drop_location("u1") is False
    assert rows.count_locations() == 0


# ---- hub 登记 ----


def test_register_hub_keeps_the_first_sight(rows: Rows):
    """登记记的是"第一次见到它"：重复登记不改写角色、状态与时刻。"""
    assert rows.register_hub("main", created=1) is True
    assert rows.register_hub("main", role="transient", state="merged", created=2) is False

    stored = rows.hub("main")
    assert stored is not None
    assert (stored.role, stored.state, stored.created) == ("main", "active", 1)


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

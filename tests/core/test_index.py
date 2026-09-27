# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""索引库用例：表声明 → 编译 → 对比分类 → 处置，以及入口四件事。

设计依据：`docs/architecture/storage-design.md` §8。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core.storage.index import Difference, Index, RebuildPlan
from core.storage.tables import (
    Column,
    ColumnType,
    Owned,
    RebuildTier,
    Table,
    core_tables,
    declared_tables,
    parse_tables,
)
from core.types.errors import CairnError, IndexSchemaError

if TYPE_CHECKING:
    from pathlib import Path

_HASH = "ab" * 32


def _index(tmp_path: Path) -> Index:
    return Index.open(tmp_path / "catalog.db")


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "value_uuid": "01AAAAAAAAAAAAAAAAAAAAAAAA",
        "value_hash": _HASH,
        "kind": "notedata",
        "bucket": "main",
        "pack": "p1",
        "slot_start": 0,
        "slot_head": 0,
        "slot_count": 1,
        "size": 128,
        "issued": 1,
        "created": 1,
        "updated": 1,
    }
    row.update(overrides)
    return row


# ---- 表声明 ----


def test_core_tables_come_from_config_declaration() -> None:
    """内核表来自**配置声明**（配置是本体，代码只解析）。"""
    declared = declared_tables()
    assert [table.name for table in declared] == ["bucket", "record", "edge"]
    for table in core_tables():
        assert table.owner is Owned.CORE
        assert table.tier is RebuildTier.TIER1
        assert table.rebuild_from  # 档一必须写得出重建来源
    assert all(table.owner is Owned.CORE for table in declared)  # 出厂声明目前全是内核表


def test_parse_rejects_unknown_column_key() -> None:
    with pytest.raises(CairnError, match="未知项"):
        parse_tables(
            [
                {
                    "name": "t",
                    "tier": "tier1",
                    "rebuild_from": "x",
                    "columns": [{"name": "a", "type": "text", "primary_key": True, "oops": 1}],
                }
            ]
        )


def test_parse_rejects_unknown_type() -> None:
    with pytest.raises(CairnError, match="类型非法"):
        parse_tables(
            [
                {
                    "name": "t",
                    "tier": "tier1",
                    "rebuild_from": "x",
                    "columns": [{"name": "a", "type": "money", "primary_key": True}],
                }
            ]
        )


def test_parse_rejects_duplicate_table_names() -> None:
    one = {
        "name": "t",
        "tier": "tier1",
        "rebuild_from": "x",
        "columns": [{"name": "a", "type": "text", "primary_key": True}],
    }
    with pytest.raises(CairnError, match="表声明重复"):
        parse_tables([one, dict(one)])


def test_parse_rejects_missing_required_item() -> None:
    with pytest.raises(CairnError, match="缺少必填项"):
        parse_tables([{"name": "t", "columns": []}])


def test_table_requires_exactly_one_primary_key() -> None:
    with pytest.raises(CairnError, match="恰好一个主键"):
        Table(
            name="t",
            tier=RebuildTier.TIER1,
            rebuild_from="x",
            columns=(Column("a", ColumnType.TEXT),),
        )


def test_table_rejects_duplicate_columns() -> None:
    with pytest.raises(CairnError, match="列名重复"):
        Table(
            name="t",
            tier=RebuildTier.TIER1,
            rebuild_from="x",
            columns=(
                Column("a", ColumnType.TEXT, primary_key=True),
                Column("a", ColumnType.INTEGER),
            ),
        )


def test_table_rejects_index_on_unknown_column() -> None:
    from core.storage.tables import Index as TableIndex  # noqa: PLC0415 — 与 sqlite 索引区分

    with pytest.raises(CairnError, match="索引列不存在"):
        Table(
            name="t",
            tier=RebuildTier.TIER1,
            rebuild_from="x",
            columns=(Column("a", ColumnType.TEXT, primary_key=True),),
            indexes=(TableIndex(("b",)),),
        )


def test_tier3_must_not_declare_rebuild_source() -> None:
    with pytest.raises(CairnError, match="不该写重建来源"):
        Table(
            name="t",
            tier=RebuildTier.TIER3,
            rebuild_from="载体",
            columns=(Column("a", ColumnType.TEXT, primary_key=True),),
        )


def test_tier1_must_declare_rebuild_source() -> None:
    with pytest.raises(CairnError, match="重建来源必填"):
        Table(
            name="t",
            tier=RebuildTier.TIER1,
            columns=(Column("a", ColumnType.TEXT, primary_key=True),),
        )


def test_column_rejects_non_scalar_default() -> None:
    with pytest.raises(CairnError, match="默认值只允许标量"):
        Column("a", ColumnType.TEXT, default=["x"])  # type: ignore[arg-type]


def test_column_rejects_bad_identifier() -> None:
    with pytest.raises(CairnError, match="非法列名"):
        Column("bad name", ColumnType.TEXT)


def test_primary_key_implies_not_null() -> None:
    assert Column("a", ColumnType.TEXT, primary_key=True).not_null


def test_ddl_is_compiled_from_declaration() -> None:
    """建表语句由声明**编译**出来：类型词汇中立，方言只出现在编译器里。"""
    record = next(table for table in declared_tables() if table.name == "record")
    statements = record.ddl()
    assert statements[0].startswith('CREATE TABLE IF NOT EXISTS "record"')
    assert any('CREATE INDEX IF NOT EXISTS "idx_value_hash"' in sql for sql in statements)
    compiled = " ".join(statements)
    assert '"value_uuid" TEXT PRIMARY KEY NOT NULL' in compiled
    assert '"slot_count" INTEGER NOT NULL DEFAULT 1' in compiled


def test_declaration_round_trips_through_config_shape() -> None:
    """声明 → 配置形状 → 声明：**往返一致**（故配置那份就是本体，不是影子）。"""
    for table in declared_tables():
        again = parse_tables([table.to_config()])[0]
        assert again.signature() == table.signature()


# ---- 对比与分类 ----


def test_differences_report_missing_tables_before_align(tmp_path: Path) -> None:
    index = _index(tmp_path)
    kinds = {(item.table, item.kind) for item in index.differences()}
    assert kinds == {
        ("record", "missing_table"),
        ("bucket", "missing_table"),
        ("edge", "missing_table"),
    }
    index.close()


def test_align_creates_everything_and_leaves_no_difference(tmp_path: Path) -> None:
    index = _index(tmp_path)
    assert index.align() == []
    assert index.differences() == []
    index.close()


def test_align_is_idempotent(tmp_path: Path) -> None:
    index = _index(tmp_path)
    index.align()
    assert index.align() == []
    index.close()


def test_plan_classifies_fixable_versus_rebuild(tmp_path: Path) -> None:
    index = _index(tmp_path)
    plan = index.repair_plan()
    assert plan["fixable"] == ["bucket", "edge", "record"]
    assert plan["rebuild"] == []
    index.close()


def test_extra_column_is_reported_but_not_destructive(tmp_path: Path) -> None:
    index = _index(tmp_path)
    index.align()
    index.conn.execute('ALTER TABLE "bucket" ADD COLUMN "note" TEXT')
    differ = [item for item in index.differences() if item.kind == "extra_column"]
    assert len(differ) == 1
    assert differ[0].fixable
    assert not differ[0].destructive
    assert index.align() == differ  # 多出的列不拦、也不删：如实报给调用方
    index.close()


def test_missing_index_is_fixable(tmp_path: Path) -> None:
    index = _index(tmp_path)
    index.align()
    index.conn.execute('DROP INDEX "idx_value_hash"')
    differ = [item for item in index.differences() if item.kind == "missing_index"]
    assert differ
    assert differ[0].fixable
    assert index.align() == []
    index.close()


def test_column_type_change_needs_rebuild_authorization(tmp_path: Path) -> None:
    """列的型变了：SQLite 改不了，无授权即**拒绝**（默认不重建，防静默丢数据）。"""
    index = _index(tmp_path)
    index.align()
    index.conn.execute('ALTER TABLE "bucket" RENAME TO "bucket_old"')
    index.conn.execute('CREATE TABLE "bucket" ("name" INTEGER PRIMARY KEY, "role" TEXT NOT NULL)')
    mismatched = [item for item in index.differences() if item.destructive]
    assert mismatched, "应当报出列型不符"
    with pytest.raises(IndexSchemaError, match="需重建并搬运"):
        index.align()
    index.close()


def test_rebuild_authorization_must_cover_every_table(tmp_path: Path) -> None:
    index = _index(tmp_path)
    index.align()
    index.conn.execute('DROP TABLE "bucket"')
    index.conn.execute('DROP TABLE "edge"')
    index.conn.execute('CREATE TABLE "bucket" ("name" INTEGER PRIMARY KEY, "role" TEXT NOT NULL)')
    index.conn.execute(
        'CREATE TABLE "edge" ("id" INTEGER PRIMARY KEY, "src" TEXT NOT NULL,'
        ' "dst" TEXT NOT NULL, "kind" TEXT NOT NULL, "domain" TEXT NOT NULL,'
        ' "created" INTEGER NOT NULL)'
    )
    with pytest.raises(IndexSchemaError, match="重建授权未覆盖"):
        index.align(rebuild=RebuildPlan(tables=("bucket",), reason="测试"))
    index.close()


def test_rebuild_with_full_authorization_aligns(tmp_path: Path) -> None:
    index = _index(tmp_path)
    index.align()
    index.conn.execute('DROP TABLE "bucket"')
    index.conn.execute('CREATE TABLE "bucket" ("name" INTEGER PRIMARY KEY)')
    left = index.align(rebuild=RebuildPlan(tables=("bucket",), reason="列型变更"))
    assert left == []
    index.close()


def test_extra_undeclared_table_is_reported_not_dropped(tmp_path: Path) -> None:
    index = _index(tmp_path)
    index.align()
    index.conn.execute('CREATE TABLE "search" (oid TEXT PRIMARY KEY, body TEXT)')
    differ = [item for item in index.differences() if item.kind == "extra_table"]
    assert differ
    assert differ[0].fixable
    index.align()
    names = index.actual_tables()
    assert "search" in names  # 未声明的表不被静默删除
    index.close()


# ---- 声明投影校验 ----


def test_verify_declarations_passes_right_after_align(tmp_path: Path) -> None:
    index = _index(tmp_path)
    index.align()
    index.verify_declarations()
    assert index.recorded_declarations() == {
        table.name: table.signature() for table in declared_tables()
    }
    index.close()


def test_verify_declarations_detects_tampering(tmp_path: Path) -> None:
    index = _index(tmp_path)
    index.align()
    index.conn.execute("UPDATE meta SET value = ? WHERE key = 'schema.declared'", ("{}",))
    with pytest.raises(IndexSchemaError, match="不一致"):
        index.verify_declarations()
    index.close()


def test_verify_declarations_is_noop_when_unrecorded(tmp_path: Path) -> None:
    index = _index(tmp_path)
    index.verify_declarations()  # 还没对齐过：无记录即不拦（由 align 负责建立）
    index.close()


# ---- 入口四件事 ----


def test_upsert_record_and_read_back(tmp_path: Path) -> None:
    index = _index(tmp_path)
    index.align()
    index.upsert_record(_row())
    row = index.record_row("01AAAAAAAAAAAAAAAAAAAAAAAA")
    assert row is not None
    assert row["kind"] == "notedata"
    assert row["pack"] == "p1"
    index.close()


def test_upsert_record_updates_in_place(tmp_path: Path) -> None:
    index = _index(tmp_path)
    index.align()
    index.upsert_record(_row(slot_start=0))
    index.upsert_record(_row(slot_start=9, slot_head=3))
    rows = index.find_by_hash(_HASH)
    assert len(rows) == 1
    assert rows[0]["slot_start"] == 9
    assert rows[0]["slot_head"] == 3
    index.close()


def test_find_by_hash_returns_every_record_sharing_content(tmp_path: Path) -> None:
    index = _index(tmp_path)
    index.align()
    index.upsert_record(_row(value_uuid="01BBBBBBBBBBBBBBBBBBBBBBBB"))
    index.upsert_record(_row(value_uuid="01CCCCCCCCCCCCCCCCCCCCCCCC"))
    assert len(index.find_by_hash(_HASH)) == 2
    index.close()


def test_count_filters_by_kind(tmp_path: Path) -> None:
    index = _index(tmp_path)
    index.align()
    index.upsert_record(_row(value_uuid="01DDDDDDDDDDDDDDDDDDDDDDDD"))
    index.upsert_record(
        _row(value_uuid="01EEEEEEEEEEEEEEEEEEEEEEEE", kind="canvas", value_hash="cd" * 32)
    )
    assert index.count() == 2
    assert index.count(kind="canvas") == 1
    assert index.count(kind="notedata") == 1
    index.close()


def test_put_edge_is_idempotent(tmp_path: Path) -> None:
    index = _index(tmp_path)
    index.align()
    first = index.put_edge(src="A", dst="B", kind="references", domain="note")
    second = index.put_edge(src="A", dst="B", kind="references", domain="note")
    assert first == second
    assert len(index.edges(src="A")) == 1
    index.close()


def test_edges_query_by_direction(tmp_path: Path) -> None:
    index = _index(tmp_path)
    index.align()
    index.put_edge(src="A", dst="B", kind="contains")
    index.put_edge(src="C", dst="B", kind="references")
    assert len(index.edges(src="A")) == 1
    assert len(index.edges(dst="B")) == 2
    assert len(index.edges(dst="B", kind="contains")) == 1
    index.close()


def test_difference_classification_flags() -> None:
    assert Difference("t", "missing_table").fixable
    assert not Difference("t", "column_mismatch").fixable
    assert Difference("t", "column_mismatch").destructive

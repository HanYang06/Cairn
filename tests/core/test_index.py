# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""索引库用例：表声明 → 编译 → 对比分类 → 处置，以及入口四件事。

设计依据：`docs/architecture/storage-design.md` §8。
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from core.storage.index import Difference, Index, RebuildPlan
from core.storage.tables import (
    Column,
    ColumnType,
    Owned,
    RebuildTier,
    TableSpec,
    core_tables,
    declared_tables,
    load_tables,
    parse_tables,
)
from core.storage.tables import (
    Index as TableIndex,
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
        TableSpec(
            name="t",
            tier=RebuildTier.TIER1,
            rebuild_from="x",
            columns=(Column("a", ColumnType.TEXT),),
        )


def test_table_rejects_duplicate_columns() -> None:
    with pytest.raises(CairnError, match="列名重复"):
        TableSpec(
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
        TableSpec(
            name="t",
            tier=RebuildTier.TIER1,
            rebuild_from="x",
            columns=(Column("a", ColumnType.TEXT, primary_key=True),),
            indexes=(TableIndex(("b",)),),
        )


def test_tier3_must_not_declare_rebuild_source() -> None:
    with pytest.raises(CairnError, match="不该写重建来源"):
        TableSpec(
            name="t",
            tier=RebuildTier.TIER3,
            rebuild_from="载体",
            columns=(Column("a", ColumnType.TEXT, primary_key=True),),
        )


def test_tier1_must_declare_rebuild_source() -> None:
    with pytest.raises(CairnError, match="重建来源必填"):
        TableSpec(
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


def test_shipped_tables_file_loads() -> None:
    """出货的那份表声明文件必须能读进来（语法错、结构错都在这里拦下）。"""
    loaded = load_tables()
    assert loaded
    assert {table.name for table in loaded} >= {"bucket", "record", "edge"}


def test_shipped_tables_file_declares_core_owner() -> None:
    for table in load_tables():
        assert table.owner is Owned.CORE
        assert table.tier is RebuildTier.TIER1


def test_missing_tables_file_fails_loudly(tmp_path: Path) -> None:
    """文件不在就报错，不静默退回出厂初值（否则"表丢了"会被伪装成正常启动）。"""
    with pytest.raises(CairnError, match="不存在"):
        load_tables(tmp_path / "nope.yaml")


def test_broken_tables_file_fails_loudly(tmp_path: Path) -> None:
    broken = tmp_path / "tables.yaml"
    broken.write_text("- name: t\n  tier: [未闭合\n", encoding="utf-8")
    with pytest.raises(CairnError, match="解析失败"):
        load_tables(broken)


def test_empty_tables_file_fails_loudly(tmp_path: Path) -> None:
    empty = tmp_path / "tables.yaml"
    empty.write_text("# 只有注释\n", encoding="utf-8")
    with pytest.raises(CairnError, match="空的"):
        load_tables(empty)


def test_tables_file_must_be_a_list(tmp_path: Path) -> None:
    mapping = tmp_path / "tables.yaml"
    mapping.write_text("name: t\n", encoding="utf-8")
    with pytest.raises(CairnError, match="必须是列表"):
        load_tables(mapping)


# ---- 对比与分类 ----

# ---- 开库的接管口径 ----


def test_open_refuses_an_older_format_catalog(tmp_path: Path) -> None:
    """旧格式的目录：表都在，却**一张都不是我们声明的** → 拒开。

    不这么判的话，老库会被"接进来并补上我们的表"，而它的块在旧结构里，
    于是用户看到的是一间**空库**——静默无视数据比报错坏得多。
    """
    path = tmp_path / "catalog.db"
    old = sqlite3.connect(str(path))
    old.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    old.execute("CREATE TABLE packs(id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    old.execute("CREATE TABLE blocks(oid TEXT PRIMARY KEY, checksum TEXT, data BLOB)")
    old.commit()
    old.close()

    with pytest.raises(IndexSchemaError, match="不接管"):
        Index.open(path)


def test_open_adopts_a_library_that_only_has_meta(tmp_path: Path) -> None:
    """只建过 `meta` 的库不算"别人的"：那是刚开过、还没对齐的样子。"""
    index = _index(tmp_path)
    index.close()

    reopened = _index(tmp_path)
    assert reopened.differences() != []  # 还没对齐，但库是我们的
    assert reopened.align() == []
    reopened.close()


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


def test_align_adds_a_missing_column(tmp_path: Path) -> None:
    """已存在的表缺一列 → `align()` 必须真把它补上（`CREATE TABLE IF NOT EXISTS` 补不了）。

    漏了这条，"声明里加一列"就会变成"库打不开"：对齐说补了、实际没补，
    再比一次仍报缺列。
    """
    index = _index(tmp_path)
    index.align()
    index.conn.execute('ALTER TABLE "record" DROP COLUMN "size"')  # 非索引列，可原地补

    differ = [item for item in index.differences() if item.kind == "missing_column"]
    assert [item.detail for item in differ] == ["size"]
    assert differ[0].fixable

    assert index.align() == []  # 补齐之后没有差异
    assert "size" in index.actual_tables()["record"]
    index.close()


def test_a_column_that_cannot_be_added_requires_rebuild(tmp_path: Path) -> None:
    """补不上的列（NOT NULL 无默认值 / 主键 / UNIQUE）**按破坏性差异报**，要显式授权。

    否则它会落在"可原位补齐"里，对齐时补不上、却又不许重建——卡死在"仍有差异"。
    """
    index = _index(tmp_path)
    index.align()
    index.conn.execute('DROP INDEX "idx_value_hash"')
    index.conn.execute('ALTER TABLE "record" DROP COLUMN "value_hash"')  # not_null 且无默认值

    differ = [item for item in index.differences() if item.table == "record"]
    assert "column_mismatch" in [item.kind for item in differ]
    destructive = next(item for item in differ if item.kind == "column_mismatch")
    assert destructive.destructive
    assert "须重建" in destructive.detail

    with pytest.raises(IndexSchemaError, match="RebuildPlan"):
        index.align()

    assert index.align(rebuild=RebuildPlan(tables=("record",), reason="测试：补不上的列")) == []
    index.close()


def test_align_adds_a_column_before_building_its_index(tmp_path: Path) -> None:
    """ "新增一列 + 给它建索引"要一次对齐成功：**补列必须在建索引之前**。

    `ddl()` 把建表与建索引混在一串里；若整段先跑，`CREATE INDEX … ("新列")` 会先执行，
    SQLite 报 `no such column`，库随即打不开（这是上一轮整改自己碰出来的坑）。
    """
    index = _index(tmp_path)
    index.align()
    index.conn.execute('ALTER TABLE "record" DROP COLUMN "size"')
    index.declarations = tuple(
        replace(
            table,
            indexes=(*table.indexes, TableIndex(columns=("size",), doc="测试：给新列建索引")),
        )
        if table.name == "record"  # 只有 record 有 size 这一列
        else table
        for table in declared_tables()
    )

    kinds = [item.kind for item in index.differences()]
    assert "missing_column" in kinds
    assert "missing_index" in kinds

    assert index.align() == []  # 先补列、再建索引：一次成功
    assert "size" in index.actual_tables()["record"]
    index.close()


def test_index_uniqueness_change_is_fixable(tmp_path: Path) -> None:
    """索引名只由列推出，故**唯一性变化**是"同名不同定义"——要拆掉重建，不是干等。

    `CREATE INDEX IF NOT EXISTS` 见到同名会跳过，光靠它永远改不过来：
    差异会卡在"对齐后仍有"，而这差异既不在破坏性分类里、也拿不到重建授权。
    """
    index = _index(tmp_path)
    index.align()
    index.declarations = tuple(
        replace(
            table,
            indexes=tuple(
                replace(found, unique=True) if found.columns == ("kind",) else found
                for found in table.indexes
            ),
        )
        for table in declared_tables()
    )

    differ = [item for item in index.differences() if item.kind == "index_mismatch"]
    assert [item.detail.split(":")[0] for item in differ] == ["idx_kind"]
    assert differ[0].fixable

    assert index.align() == []
    assert (("kind",), True) in index.actual_indexes("record")  # 唯一索引真建上了
    index.close()


def test_open_closes_the_connection_when_the_file_is_not_a_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """文件不是数据库时：认表那一步就抛，**抛之前要把连接关掉**（反复失败不能一次漏一个）。"""
    path = tmp_path / "catalog.db"
    path.write_bytes(b"not a database at all" * 8)

    made: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def spy(*args: object, **kwargs: object) -> sqlite3.Connection:
        conn = real_connect(*args, **kwargs)  # type: ignore[arg-type]
        made.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", spy)

    with pytest.raises(sqlite3.DatabaseError):
        Index.open(path)

    assert len(made) == 1
    with pytest.raises(sqlite3.ProgrammingError):
        made[0].execute("SELECT 1")  # 已关闭：再用就当头报错


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

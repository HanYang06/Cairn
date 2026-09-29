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


def test_parse_rejects_scalars_in_the_column_and_index_levels() -> None:
    """列与索引也各有自己的元素：写成标量要报 `CairnError`，不是 `TypeError`。

    表那一级早就挡住了（`parse_tables` 先整体查一遍形状）；列与索引是同一类写法错误，
    漏掉就会在 ``key not in mapping`` 上抛 `TypeError`，调用方按 `CairnError` 捕获就漏了。
    """
    base = {
        "name": "t",
        "tier": "tier1",
        "rebuild_from": "x",
        "columns": [{"name": "a", "type": "text", "primary_key": True}],
    }
    with pytest.raises(CairnError, match="非映射"):
        parse_tables([{**base, "columns": [5]}])
    with pytest.raises(CairnError, match="非映射"):
        parse_tables([{**base, "indexes": [5]}])


def test_parse_rejects_a_non_string_index_column() -> None:
    """索引列写成数字：当场报类型不对，而不是被静默转成名字再报非法列名。"""
    with pytest.raises(CairnError, match="必须是字符串"):
        parse_tables(
            [
                {
                    "name": "t",
                    "tier": "tier1",
                    "rebuild_from": "x",
                    "columns": [{"name": "a", "type": "text", "primary_key": True}],
                    "indexes": [{"columns": [1]}],
                }
            ]
        )


def test_parse_rejects_two_indexes_with_the_same_columns() -> None:
    """同一列组合声明两次 → 索引同名 → 声明的唯一性会静默落空，故解析口就拒。

    索引名由列组合推出，故两条同列组合的声明共用一个名字：`ddl()` 里第二条
    `CREATE [UNIQUE] INDEX IF NOT EXISTS` 会被 SQLite 跳过，UNIQUE 约束实际缺失。
    """
    with pytest.raises(CairnError, match="索引重名"):
        parse_tables(
            [
                {
                    "name": "t",
                    "tier": "tier1",
                    "rebuild_from": "x",
                    "columns": [{"name": "a", "type": "text", "primary_key": True}],
                    "indexes": [{"columns": ["a"]}, {"columns": ["a"], "unique": True}],
                }
            ]
        )


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
    assert any('CREATE INDEX IF NOT EXISTS "idx_record_value_hash"' in sql for sql in statements)
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
    index.conn.execute('DROP INDEX "idx_record_value_hash"')
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
    index.conn.execute('DROP INDEX "idx_record_value_hash"')
    index.conn.execute('ALTER TABLE "record" DROP COLUMN "value_hash"')  # not_null 且无默认值

    differ = [item for item in index.differences() if item.table == "record"]
    assert "column_mismatch" in [item.kind for item in differ]
    destructive = next(item for item in differ if item.kind == "column_mismatch")
    assert destructive.destructive
    assert "须重建" in destructive.detail

    with pytest.raises(IndexSchemaError, match="RebuildPlan"):
        index.align()

    left = index.align(rebuild=RebuildPlan(tables=("record",), reason="测试：补不上的列"))
    # 旧表改名隔离故只剩一条"多出的表"告警：不删数据、也不拦开库
    assert [item.kind for item in left] == ["extra_table"]
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
    """索引名由表名与列组合推出，故**唯一性变化**是"同名不同定义"——要拆掉重建，不是干等。

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
    assert [item.subject for item in differ] == ["idx_record_kind"]
    assert differ[0].fixable

    assert index.align() == []
    assert (("kind",), True) in index.actual_indexes("record")  # 唯一索引真建上了
    index.close()


def test_index_name_carries_the_table() -> None:
    """索引名带表名：SQLite 的索引名**整库唯一**，只由列组合推出会跨表撞名。"""
    record = next(table for table in declared_tables() if table.name == "record")
    assert any('"idx_record_kind"' in sql for sql in record.ddl())


def test_cross_table_index_collision_is_rejected() -> None:
    """跨表索引名重复在**解析口**就拦下（撞名的第二张表会被 SQLite 静默跳过）。

    表名与列名同用 ``_`` 分隔，故表 ``a`` 的列 ``b, c`` 与表 ``a_b`` 的列 ``c``
    会推出同一个索引名。单表内的重名校验看不见它，这一条由 `parse_tables` 统一查。
    """

    def _decl(name: str, columns: list[str]) -> dict[str, object]:
        extra = [{"name": item, "type": "text"} for item in columns]
        return {
            "name": name,
            "tier": "tier1",
            "rebuild_from": "测试",
            "columns": [{"name": "id", "type": "text", "primary_key": True}, *extra],
            "indexes": [{"columns": columns}],
        }

    parse_tables([_decl("a", ["b", "c"])])  # 单独一张表：不撞
    with pytest.raises(CairnError, match="索引名跨表重复"):
        parse_tables([_decl("a", ["b", "c"]), _decl("a_b", ["c"])])


def test_empty_rebuild_from_is_missing_not_a_ghost() -> None:
    """YAML 里写空的 ``rebuild_from:`` 归为空串，由必填校验正当地拦下。

    原先 ``str(raw.get(...))`` 会把它变成字符串 ``"None"``——一个真值的幽灵来源，
    于是"档一 / 档二必须写重建来源"这条被静默通过。
    """
    raw = {
        "name": "t",
        "tier": "tier1",
        "rebuild_from": None,
        "columns": [{"name": "id", "type": "text", "primary_key": True}],
    }
    with pytest.raises(CairnError, match="重建来源必填"):
        parse_tables([raw])


def test_rebuild_quarantines_the_old_table_instead_of_dropping_it(tmp_path: Path) -> None:
    """授权重建**不丢数据**：旧表改名成 ``<表>__dropped_<时刻>`` 留在库里。

    ``DROP TABLE`` 会让整张表的行当场消失，而"数据由调用方搬运"在实现里没有落点；
    档三（真源在库内、只能靠备份）的表更等同不可恢复的丢失。隔离表按
    "库里有、声明没有"处置，即**只告警不删**。
    """
    index = _index(tmp_path)
    index.align()
    index.conn.execute(
        "INSERT INTO bucket(name, role, state, created) VALUES(?, ?, ?, ?)",
        ("main", "main", "mounted", 1),
    )
    index.declarations = tuple(
        replace(
            table,
            columns=tuple(
                replace(column, default=None) if column.name == "role" else column
                for column in table.columns
            ),
        )
        if table.name == "bucket"
        else table
        for table in declared_tables()
    )

    assert any(item.table == "bucket" and item.destructive for item in index.differences())

    remaining = index.align(rebuild=RebuildPlan(tables=("bucket",), reason="测试"))
    assert {item.kind for item in remaining} == {"extra_table"}  # 隔离表只告警

    leftover = [
        str(row["name"])
        for row in index.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'bucket__dropped_%'"
        )
    ]
    assert len(leftover) == 1
    kept = index.conn.execute(
        f'SELECT COUNT(*) AS n FROM "{leftover[0]}"'  # noqa: S608 — 名字取自 sqlite_master，由本程序生成
    ).fetchone()
    assert int(kept["n"]) == 1  # 旧行一行没丢
    index.close()


def test_open_parses_declarations_before_connecting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """声明解析在**建立连接之前**：解析失败时根本没有连接可漏。

    原先声明的读取藏在 `Index` 的 dataclass 默认值里，构造时才执行，于是它抛错
    （表声明文件缺失 / YAML 非法 / 校验失败）时刚 connect 出来的连接没人关。
    """
    made: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def spy(*args: object, **kwargs: object) -> sqlite3.Connection:
        conn = real_connect(*args, **kwargs)  # type: ignore[arg-type]
        made.append(conn)
        return conn

    def boom() -> tuple[TableSpec, ...]:
        raise CairnError("表声明读不出来")

    monkeypatch.setattr(sqlite3, "connect", spy)
    monkeypatch.setattr("core.storage.index.declared_tables", boom)

    with pytest.raises(CairnError, match="表声明读不出来"):
        Index.open(tmp_path / "catalog.db")

    assert made == []  # 连接从未建立：也就没有连接可漏


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


def test_constraint_drift_is_detected(tmp_path: Path) -> None:
    """已存在列上的**约束漂移**（非空 / 默认值 / 主键）同样要报出来。

    只比类型会让"声明给某列加了 not_null、或改了默认值"静默放过：
    开库一路绿灯，而库里的结构与声明已经不一致。
    """
    index = _index(tmp_path)
    index.align()
    index.conn.execute('ALTER TABLE "bucket" RENAME TO "bucket_old"')
    index.conn.execute(
        'CREATE TABLE "bucket" ("name" TEXT PRIMARY KEY NOT NULL, "role" TEXT,'
        ' "state" TEXT NOT NULL, "created" INTEGER NOT NULL DEFAULT 7)'
    )

    drift = [
        item
        for item in index.differences()
        if item.table == "bucket" and item.kind == "column_mismatch"
    ]
    details = " | ".join(item.detail for item in drift)
    assert "非空" in details  # role 丢了 NOT NULL
    assert "默认值" in details  # created 的默认值从 0 变成 7
    assert all(item.destructive for item in drift)

    with pytest.raises(IndexSchemaError, match="RebuildPlan"):
        index.align()
    index.close()


def test_load_tables_rejects_a_non_mapping_item(tmp_path: Path) -> None:
    """声明里混进标量（手写 YAML 很容易写成 `- foo`）要报 `CairnError`，不是 `TypeError`。"""
    path = tmp_path / "tables.yaml"
    path.write_text(
        "- name: ok\n  tier: tier1\n  rebuild_from: 测试\n  columns: []\n- foo\n",
        encoding="utf-8",
    )

    with pytest.raises(CairnError, match="非映射"):
        load_tables(path)


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
    assert [item.kind for item in left] == ["extra_table"]  # 旧表隔离保留，只告警
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

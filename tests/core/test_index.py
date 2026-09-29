# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""索引库契约：开库对齐（建表 / 补列 / 建或重建索引）、破坏性差异须授权且不丢数据。

这里的用例一律走真实文件：对齐的结果只能从库里读回来才算数。
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from core.exc import IndexNotFoundError, IndexSchemaError
from core.storage.index import DROPPED_SUFFIX, DiffKind, Index, RebuildPlan
from core.storage.tables import KERNEL_TABLES, Declaration, TableSpec

if TYPE_CHECKING:
    from pathlib import Path

_BASE_COLUMNS: list[dict[str, object]] = [
    {"name": "id", "from": "prog", "type": "text", "not_null": True},
    {"name": "tag", "from": "prog", "type": "text"},
]
_BASE_KEY: list[str] = ["id"]
"""这些夹具表的主键：新声明把主键写在表级（复合主键挂不在列上）。"""


def _decl(
    *,
    columns: list[dict[str, object]] | None = None,
    indexes: list[dict[str, object]] | None = None,
    doc: str = "说明",
) -> Declaration:
    """一份只有一张表的最小声明，可按需换掉列或索引。"""
    spec = TableSpec.from_mapping(
        {
            "name": "thing",
            "tier": "derived",
            "rebuild_from": "载体",
            "doc": doc,
            "columns": _BASE_COLUMNS if columns is None else columns,
            "indexes": [{"columns": ["tag"]}] if indexes is None else indexes,
            "primary_key": _BASE_KEY,
        }
    )
    return Declaration((spec,))


def _kinds(index: Index) -> list[DiffKind]:
    """本次开库差异的种类清单。"""
    return [item.kind for item in index.alignment.differences]


def _raw(path: Path, *statements: str) -> None:
    """绕过 Index 直接改库，用来造"库与声明脱节"的局面。"""
    connection = sqlite3.connect(path)
    try:
        for statement in statements:
            connection.execute(statement)
        connection.commit()
    finally:
        connection.close()


def _query(path: Path, statement: str) -> list[tuple[object, ...]]:
    """开一次库、查一次、关掉（测试里不放过任何连接）。"""
    connection = sqlite3.connect(path)
    try:
        return [tuple(row) for row in connection.execute(statement).fetchall()]
    finally:
        connection.close()


def _columns_of(path: Path, table: str) -> list[str]:
    """读一张表的列名（诊断用）。"""
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    finally:
        connection.close()
    return [str(row[1]) for row in rows]


# ---- 建立与幂等 ----


def test_create_builds_every_declared_table(tmp_path: Path):
    """新库：声明里的表与索引都建出来，并登记声明签名。"""
    path = tmp_path / "catalog.db"
    declaration = Declaration(KERNEL_TABLES)
    with Index.open(path, declaration, create=True) as index:
        assert index.declaration is declaration
        assert index.tables() == ("edge", "hub", "meta", "record")
        kinds = _kinds(index)
        assert kinds.count(DiffKind.MISSING_TABLE) == 4
        assert any(entry.startswith("登记声明") for entry in index.alignment.applied)


def test_second_open_has_nothing_to_do(tmp_path: Path):
    """对齐一次之后，再开不带任何差异：开库是幂等的。"""
    path = tmp_path / "catalog.db"
    Index.open(path, Declaration(KERNEL_TABLES), create=True).close()

    with Index.open(path, Declaration(KERNEL_TABLES)) as index:
        assert index.alignment.clean
        assert index.alignment.applied == ()
        assert not index.alignment.declaration_changed


def test_read_path_does_not_create_the_file(tmp_path: Path):
    """**读路径不建库**：文件不在就报错，且不留空文件。"""
    path = tmp_path / "missing.db"

    with pytest.raises(IndexNotFoundError):
        Index.open(path, _decl())

    assert not path.exists()


def test_foreign_sqlite_file_is_refused(tmp_path: Path):
    """不是本程序的索引库（没有 meta，也没有声明过的表）一律拒开。"""
    path = tmp_path / "someone.db"
    _raw(path, "CREATE TABLE someone_else (id TEXT PRIMARY KEY)")

    with pytest.raises(IndexSchemaError, match="不是本程序的索引库"):
        Index.open(path, _decl())


def test_context_manager_closes_the_connection(tmp_path: Path):
    """退出 with 即关闭连接。"""
    path = tmp_path / "catalog.db"
    with Index.open(path, _decl(), create=True) as index:
        pass

    with pytest.raises(sqlite3.ProgrammingError):
        index.tables()


# ---- 缺失即建 ----


def test_missing_table_is_created(tmp_path: Path):
    """表没了即建回来（档一重建的轻量版本：只补结构）。"""
    path = tmp_path / "catalog.db"
    Index.open(path, _decl(), create=True).close()
    _raw(path, "DROP TABLE thing")

    with Index.open(path, _decl()) as index:
        assert _kinds(index) == [DiffKind.MISSING_TABLE]
        assert "thing" in index.tables()


def test_missing_column_is_added(tmp_path: Path):
    """缺列即补：可补的列用 ALTER TABLE 加上，不动其余数据。"""
    path = tmp_path / "catalog.db"
    Index.open(path, _decl(), create=True).close()
    _raw(path, "INSERT INTO thing (id, tag) VALUES ('a', 'x')")

    grown = _decl(
        columns=[*_BASE_COLUMNS, {"name": "size", "from": "prog", "type": "integer", "default": 0}]
    )
    with Index.open(path, grown) as index:
        assert DiffKind.MISSING_COLUMN in _kinds(index)
        assert _columns_of(path, "thing") == ["id", "tag", "size"]

    connection = sqlite3.connect(path)
    try:
        row = connection.execute("SELECT size FROM thing WHERE id = 'a'").fetchone()
    finally:
        connection.close()
    assert row is not None
    assert row[0] == 0


def test_missing_index_is_created(tmp_path: Path):
    """索引缺了即建。"""
    path = tmp_path / "catalog.db"
    Index.open(path, _decl(), create=True).close()
    _raw(path, 'DROP INDEX "idx_thing_tag"')

    with Index.open(path, _decl()) as index:
        assert _kinds(index) == [DiffKind.MISSING_INDEX]
        assert 'CREATE INDEX IF NOT EXISTS "idx_thing_tag"' in index.alignment.applied[0]


def test_changed_index_is_dropped_and_recreated(tmp_path: Path):
    """同名索引的唯一性变了：拆掉重建（索引名里没有唯一性，故靠比对发现）。"""
    path = tmp_path / "catalog.db"
    Index.open(path, _decl(), create=True).close()

    unique = _decl(indexes=[{"columns": ["tag"], "unique": True}])
    with Index.open(path, unique) as index:
        kinds = _kinds(index)
        assert DiffKind.CHANGED_INDEX in kinds
        # 唯一性参与签名，故改索引也算"声明变了"
        assert DiffKind.DECLARATION_DRIFT in kinds
        assert any(entry.startswith("DROP INDEX") for entry in index.alignment.applied)

    connection = sqlite3.connect(path)
    try:
        rows = connection.execute('PRAGMA index_list("thing")').fetchall()
    finally:
        connection.close()
    assert [bool(row[2]) for row in rows if row[1] == "idx_thing_tag"] == [True]


# ---- 多余的东西只告警 ----


def test_extra_table_and_column_are_only_reported(tmp_path: Path):
    """未声明的表与列只告警，绝不静默删除。"""
    path = tmp_path / "catalog.db"
    Index.open(path, _decl(), create=True).close()
    _raw(
        path,
        "CREATE TABLE spare (id TEXT PRIMARY KEY)",
        "ALTER TABLE thing ADD COLUMN junk TEXT",
    )

    with Index.open(path, _decl()) as index:
        kinds = _kinds(index)
        assert DiffKind.EXTRA_TABLE in kinds
        assert DiffKind.EXTRA_COLUMN in kinds
        assert any("多出的表: spare" in warning for warning in index.alignment.warnings)
        assert not any("DROP" in entry for entry in index.alignment.applied)

    assert _query(
        path, "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'spare'"
    ) == [("spare",)]
    assert "junk" in _columns_of(path, "thing")


# ---- 破坏性差异 ----


def test_changed_column_type_needs_authorization(tmp_path: Path):
    """列型漂移属容器级不兼容：默认拒绝，并列出待重建的表。"""
    path = tmp_path / "catalog.db"
    Index.open(path, _decl(), create=True).close()

    changed = _decl(columns=[_BASE_COLUMNS[0], {"name": "tag", "from": "prog", "type": "integer"}])
    with pytest.raises(IndexSchemaError, match="须显式授权重建: thing"):
        Index.open(path, changed)


def test_unaddable_column_needs_authorization(tmp_path: Path):
    """非空且无默认值的列补不上，按破坏性处置。"""
    path = tmp_path / "catalog.db"
    Index.open(path, _decl(), create=True).close()

    grown = _decl(
        columns=[
            *_BASE_COLUMNS,
            {"name": "size", "from": "prog", "type": "integer", "not_null": True},
        ]
    )
    with pytest.raises(IndexSchemaError, match="须显式授权重建"):
        Index.open(path, grown)


@pytest.mark.parametrize(
    "columns",
    [
        # 非空约束变了
        [
            {"name": "id", "from": "prog", "type": "text", "not_null": True},
            {"name": "tag", "from": "prog", "type": "text", "not_null": True},
        ],
        # 主键换了列
        [
            {"name": "id", "from": "prog", "type": "text"},
            {"name": "tag", "from": "prog", "type": "text", "not_null": True},
        ],
        # 默认值变了
        [
            {"name": "id", "from": "prog", "type": "text", "not_null": True},
            {"name": "tag", "from": "prog", "type": "text", "default": "x"},
        ],
    ],
)
def test_other_container_drifts_are_destructive(tmp_path: Path, columns: list[dict[str, object]]):
    """非空、主键、默认值任一项漂移都算容器级不兼容，与列型漂移同等处置。"""
    path = tmp_path / "catalog.db"
    Index.open(path, _decl(), create=True).close()

    with pytest.raises(IndexSchemaError, match="须显式授权重建"):
        Index.open(path, _decl(columns=columns))


def test_column_level_unique_drift_needs_authorization(tmp_path: Path):
    """列级唯一在库里由唯一索引承载：没有它即漂移，且补不上。"""
    path = tmp_path / "catalog.db"
    Index.open(path, _decl(), create=True).close()

    unique = _decl(
        columns=[_BASE_COLUMNS[0], {"name": "tag", "from": "prog", "type": "text", "unique": True}],
        indexes=[],
    )
    with pytest.raises(IndexSchemaError, match="须显式授权重建"):
        Index.open(path, unique)


def test_rebuild_isolates_the_old_table_and_keeps_its_rows(tmp_path: Path):
    """重建不丢数据：旧表改名隔离（不删），数据还在里面；新表按声明建好。"""
    path = tmp_path / "catalog.db"
    Index.open(path, _decl(), create=True).close()
    _raw(path, "INSERT INTO thing (id, tag) VALUES ('a', '1')")

    changed = _decl(columns=[_BASE_COLUMNS[0], {"name": "tag", "from": "prog", "type": "integer"}])
    plan = RebuildPlan(tables=("thing",), reason="测试：改列型")
    with Index.open(path, changed, rebuild=plan) as index:
        assert index.alignment.rebuilt == ("thing",)
        assert any(entry.startswith("ALTER TABLE") for entry in index.alignment.applied)
        assert any("隔离表" in warning for warning in index.alignment.warnings)

    connection = sqlite3.connect(path)
    try:
        isolated = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE ?",
            (f"thing{DROPPED_SUFFIX}%",),
        ).fetchall()
        # 隔离表名取自上面这次查询的结果，不是外部输入；表名又无法参数化，故直接拼
        kept = connection.execute(
            f'SELECT tag FROM "{isolated[0][0]}"'  # noqa: S608
        ).fetchall()
        fresh = connection.execute('PRAGMA table_info("thing")').fetchall()
    finally:
        connection.close()

    assert len(isolated) == 1
    assert kept == [("1",)]
    assert [row[1] for row in fresh] == ["id", "tag"]
    assert [str(row[2]) for row in fresh] == ["TEXT", "INTEGER"]


def test_rebuild_authorization_must_cover_every_table(tmp_path: Path):
    """授权未覆盖到的表同样拒绝。"""
    path = tmp_path / "catalog.db"
    Index.open(path, _decl(), create=True).close()

    changed = _decl(columns=[_BASE_COLUMNS[0], {"name": "tag", "from": "prog", "type": "integer"}])
    plan = RebuildPlan(tables=("other",), reason="测试：漏了一张")

    with pytest.raises(IndexSchemaError, match="授权未覆盖"):
        Index.open(path, changed, rebuild=plan)


# ---- 声明签名 ----


def test_declaration_drift_is_reported_and_updated(tmp_path: Path):
    """声明变了（加了一张领域表）：登记随之更新，并报告漂移。"""
    path = tmp_path / "catalog.db"
    Index.open(path, _decl(), create=True).close()

    extra = TableSpec.from_mapping(
        {
            "name": "note",
            "tier": "source",
            "owner": "note",
            "columns": [{"name": "id", "from": "prog", "type": "text"}],
            "primary_key": ["id"],
        }
    )
    grown = Declaration((*_decl().tables, extra))
    with Index.open(path, grown) as index:
        assert index.alignment.declaration_changed
        assert DiffKind.DECLARATION_DRIFT in _kinds(index)
        assert DiffKind.MISSING_TABLE in _kinds(index)

    with Index.open(path, grown) as index:
        assert not index.alignment.declaration_changed
        assert index.alignment.clean


def test_dropping_a_unique_column_constraint_is_not_a_container_drift(tmp_path: Path):
    """库内的唯一约束比声明更严：那是库里多出来的隐式索引，只按声明一侧比，不拆也不重建。"""
    path = tmp_path / "catalog.db"
    strict = _decl(
        columns=[_BASE_COLUMNS[0], {"name": "tag", "from": "prog", "type": "text", "unique": True}]
    )
    Index.open(path, strict, create=True).close()

    with Index.open(path, _decl()) as index:
        kinds = _kinds(index)
        assert DiffKind.CHANGED_COLUMN not in kinds
        assert DiffKind.DECLARATION_DRIFT in kinds


def test_doc_is_not_part_of_the_signature(tmp_path: Path):
    """改说明文字不该让库"脱节"：签名里没有 doc。"""
    path = tmp_path / "catalog.db"
    Index.open(path, _decl(doc="旧说明"), create=True).close()

    with Index.open(path, _decl(doc="新说明")) as index:
        assert not index.alignment.declaration_changed
        assert index.alignment.clean

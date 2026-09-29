# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""索引库：一处 `catalog.db`，开库时把声明与实际结构对齐。

设计篇 §8 的规矩落在这里：

- **入口不是中枢**（§8.1）：库内只放"能被快速筛出来"的东西，正文与资产一律不进库；
- **结构由声明编译**（§8.4）：建表与建索引语句都来自 `tables.py`，本模块只做**看、比、处置**，
  一句建表 SQL 都不写；
- **比对不只看列型**：主键 / 非空 / 默认值同样比，漂移即"容器级不兼容"；
- **破坏性动作必须显式授权**：重建默认拒绝并列出待重建的表，调用方给出 :class:`RebuildPlan`
  才执行；且**重建不丢数据**——旧表改名隔离为 `<表>__dropped_<时刻>`，隔离表随后按"多出的表"
  只告警、不删除；
- **多出的东西只告警**：未声明的表 / 列 / 索引一概不静默删除。

处置分三类：缺失即建、缺列即补（补不上的按破坏性处置）、索引不符即建或拆掉重建。
开库流程是幂等的：对齐一次之后，再开不会产生新的差异。
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Self

from core.exc import IndexNotFoundError, IndexSchemaError

from .rows import Rows
from .tables import (
    META_TABLE_SPEC,
    Column,
    Declaration,
    TableSpec,
    quote_identifier,
    sql_type,
)

if TYPE_CHECKING:
    from types import TracebackType

META_TABLE = META_TABLE_SPEC.name
"""库级登记表的名字：索引库自用，由开库流程保证存在（建表语句仍由声明编译）。"""

DECLARATION_KEY = "declaration"
"""登记项：声明的规范化描述。"""

DROPPED_SUFFIX = "__dropped_"
"""隔离表的后缀：重建时旧表改名到这个名字下，不删除。"""

_Plan = tuple[list["Difference"], list[str], list[str]]
"""一份比对结果：差异、待执行语句、只告警事项。"""

_Rebuild = tuple[list[str], list[str], list[str]]
"""一次重建的结果：被重建的表、待执行语句、只告警事项。"""


class DiffKind(Enum):
    """一处差异的种类：既是报告，也是处置依据。"""

    MISSING_TABLE = "missing_table"
    MISSING_COLUMN = "missing_column"
    CHANGED_COLUMN = "changed_column"
    MISSING_UNIQUE = "missing_unique"
    MISSING_INDEX = "missing_index"
    CHANGED_INDEX = "changed_index"
    EXTRA_TABLE = "extra_table"
    EXTRA_COLUMN = "extra_column"
    EXTRA_INDEX = "extra_index"
    DECLARATION_DRIFT = "declaration_drift"


@dataclass(frozen=True, slots=True)
class Difference:
    """声明与实际的一处差异。

    ``table`` 与 ``subject`` 都是结构化的：处置不去 ``detail`` 的散文里反解对象名。

    Attributes:
        kind: 差异种类。
        table: 涉及的表。
        subject: 涉及的对象名（列名 / 索引名 / 表名）。
        detail: 人读的说明。
        destructive: 是否属于"改不动、须重建"的容器级差异。
    """

    kind: DiffKind
    table: str
    subject: str
    detail: str
    destructive: bool = False


@dataclass(frozen=True, slots=True)
class RebuildPlan:
    """重建授权：明确列出允许重建的表与理由。

    Attributes:
        tables: 允许重建的表名；未覆盖到的表一律拒绝。
        reason: 为什么重建——授权是要签字的东西，不是开关。
    """

    tables: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class Alignment:
    """一次开库对齐的结果。

    Attributes:
        differences: 全部差异（含只告警的那些）。
        applied: 实际执行的语句。
        warnings: 只告警不处置的事项。
        rebuilt: 被重建（改名隔离后重建）的表。
        declaration_changed: 库内登记的声明与当前声明不同。
    """

    differences: tuple[Difference, ...] = ()
    applied: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    rebuilt: tuple[str, ...] = ()
    declaration_changed: bool = False

    @property
    def clean(self) -> bool:
        """没有任何差异（开库即对齐，什么都不用做）。"""
        return not self.differences


@dataclass(slots=True)
class _ActualColumn:
    """从库里读到的列的样子。"""

    type: str
    not_null: bool
    primary_key: bool
    default: str | None


@dataclass(slots=True)
class _ActualIndex:
    """从库里读到的索引的样子。"""

    unique: bool
    origin: str
    columns: tuple[str, ...]


@dataclass(slots=True)
class _ActualTable:
    """从库里读到的一张表：列与索引。"""

    columns: dict[str, _ActualColumn] = field(default_factory=dict)
    indexes: dict[str, _ActualIndex] = field(default_factory=dict)


class Index:
    """一个索引库连接：开库即对齐声明，附带可检视的对齐报告。

    本层不做行读写（那是存储引擎与巡检的事）；它只负责"库里长什么样"与"该改成什么样"。
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        declaration: Declaration,
        alignment: Alignment,
    ) -> None:
        """由 :meth:`open` 使用；不留公开构造。"""
        self._connection = connection
        self._declaration = declaration
        self._alignment = alignment

    @classmethod
    def open(
        cls,
        path: str | Path,
        declaration: Declaration,
        *,
        create: bool = False,
        rebuild: RebuildPlan | None = None,
    ) -> Index:
        """打开（或显式建立）索引库，并把结构与声明对齐。

        Args:
            path: 索引库文件（`vault/catalog.db`）。
            declaration: 当前声明集。
            create: 文件不存在时是否建立。**读路径不建库**，故默认 ``False``。
            rebuild: 破坏性差异的授权；不给则遇到容器级漂移即拒绝。

        Raises:
            IndexNotFoundError: 文件不存在且未要求建立。
            IndexSchemaError: 这不是本程序的索引库，或存在未授权的破坏性差异。
        """
        database = Path(path)
        existed = database.is_file()
        if not existed and not create:
            raise IndexNotFoundError(f"索引库不存在: {database}")
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        try:
            alignment = _align(connection, declaration, existed=existed, rebuild=rebuild)
        except BaseException:
            connection.close()
            raise
        return cls(connection, declaration, alignment)

    @property
    def declaration(self) -> Declaration:
        """当前声明集。"""
        return self._declaration

    @property
    def alignment(self) -> Alignment:
        """本次开库的对齐报告。"""
        return self._alignment

    @property
    def rows(self) -> Rows:
        """本库的行层：定位行 / hub 登记 / 关系边的读写（共用这条连接）。"""
        return Rows(self._connection)

    def tables(self) -> tuple[str, ...]:
        """库内实际的表名（按名排序）。"""
        return tuple(sorted(_introspect(self._connection)))

    def close(self) -> None:
        """关闭连接。"""
        self._connection.close()

    def __enter__(self) -> Self:
        """进入 ``with``：库可用。"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """退出 ``with``：无论是否异常都关闭连接。"""
        self.close()


def _align(
    connection: sqlite3.Connection,
    declaration: Declaration,
    *,
    existed: bool,
    rebuild: RebuildPlan | None,
) -> Alignment:
    """比对声明与实际，按差异分类处置，最后更新库内登记的声明。"""
    actual = _introspect(connection)
    declared = {table.name for table in declaration.tables}
    if existed and not _looks_like_ours(actual, declared):
        raise IndexSchemaError(
            f"这个 sqlite 文件不是本程序的索引库：既没有 {META_TABLE}，也没有任何声明过的表"
        )

    differences, statements, warnings = _plan(declaration, actual, declared)
    if META_TABLE not in actual:
        # meta 是索引库自用表：不在任何声明集里，但建表语句同样由声明编译
        statements.extend(META_TABLE_SPEC.ddl())
        differences.append(
            Difference(DiffKind.MISSING_TABLE, META_TABLE, META_TABLE, "库级登记表未建")
        )
    rebuilt, rebuild_statements, rebuild_warnings = _plan_rebuild(declaration, differences, rebuild)
    statements.extend(rebuild_statements)
    warnings.extend(rebuild_warnings)

    stored = _stored_signature(connection) if META_TABLE in actual else None
    signature = declaration.signature()
    declaration_changed = stored is not None and stored != signature
    if declaration_changed:
        differences.append(
            Difference(
                DiffKind.DECLARATION_DRIFT,
                META_TABLE,
                META_TABLE,
                "库内登记的声明与当前声明不同",
            )
        )

    applied: list[str] = []
    for statement in statements:
        connection.execute(statement)
        applied.append(statement)
    if stored != signature:
        _write_signature(connection, signature)
        applied.append(f"登记声明: {DECLARATION_KEY}")
    connection.commit()

    return Alignment(
        differences=tuple(differences),
        applied=tuple(applied),
        warnings=tuple(warnings),
        rebuilt=tuple(rebuilt),
        declaration_changed=declaration_changed,
    )


def _plan(
    declaration: Declaration,
    actual: dict[str, _ActualTable],
    declared: set[str],
) -> _Plan:
    """逐表比对，并把"多出来的表"记成告警。"""
    differences: list[Difference] = []
    statements: list[str] = []
    warnings: list[str] = []

    for spec in declaration.tables:
        found = actual.get(spec.name)
        if found is None:
            differences.append(
                Difference(DiffKind.MISSING_TABLE, spec.name, spec.name, "库内缺这张表")
            )
            statements.extend(spec.ddl())
            continue
        table_diffs, table_statements, table_warnings = _compare_table(spec, found)
        differences.extend(table_diffs)
        statements.extend(table_statements)
        warnings.extend(table_warnings)

    for name in sorted(actual):
        if name == META_TABLE or name in declared:
            continue
        differences.append(Difference(DiffKind.EXTRA_TABLE, name, name, "库里有、声明里没有"))
        warnings.append(f"多出的表: {name}")

    return differences, statements, warnings


def _plan_rebuild(
    declaration: Declaration,
    differences: list[Difference],
    rebuild: RebuildPlan | None,
) -> _Rebuild:
    """破坏性差异的处置：**授权后**才改名隔离并重建。"""
    targets = tuple(dict.fromkeys(item.table for item in differences if item.destructive))
    if not targets:
        return [], [], []
    _authorize(rebuild, targets)

    statements: list[str] = []
    warnings: list[str] = []
    stamp = int(time.time() * 1000)
    for name in targets:
        spec = declaration.table(name)
        if spec is None:  # 破坏性差异只可能来自声明过的表
            raise IndexSchemaError(f"待重建的表不在声明里: {name}")
        isolated = f"{name}{DROPPED_SUFFIX}{stamp}"
        statements.append(
            f"ALTER TABLE {quote_identifier(name)} RENAME TO {quote_identifier(isolated)}"
        )
        statements.extend(spec.ddl())
        warnings.append(f"隔离表: {isolated}（只告警，不删）")
    return list(targets), statements, warnings


def _compare_table(spec: TableSpec, found: _ActualTable) -> _Plan:
    """比一张表：列（含列级唯一）与索引。"""
    column_diffs, column_statements, column_warnings = _compare_columns(spec, found)
    index_diffs, index_statements, index_warnings = _compare_indexes(spec, found)
    return (
        [*column_diffs, *index_diffs],
        [*column_statements, *index_statements],
        [*column_warnings, *index_warnings],
    )


def _compare_columns(spec: TableSpec, found: _ActualTable) -> _Plan:
    """比列：缺失即建或补、漂移即破坏性、多出的只告警；列级唯一另算。"""
    differences: list[Difference] = []
    statements: list[str] = []
    warnings: list[str] = []

    for column in spec.columns:
        actual_column = found.columns.get(column.name)
        if actual_column is None:
            differences.append(_missing_column(spec, column, statements))
            continue
        drift = _column_drift(column, actual_column)
        if drift is not None:
            differences.append(
                Difference(DiffKind.CHANGED_COLUMN, spec.name, column.name, drift, destructive=True)
            )

    declared_columns = {column.name for column in spec.columns}
    for name in sorted(found.columns):
        if name not in declared_columns:
            differences.append(
                Difference(DiffKind.EXTRA_COLUMN, spec.name, name, "库里有、声明里没有")
            )
            warnings.append(f"多出的列: {spec.name}.{name}")

    differences.extend(
        Difference(
            DiffKind.MISSING_UNIQUE,
            spec.name,
            column.name,
            "声明为唯一，库内没有对应的唯一索引",
            destructive=True,
        )
        for column in spec.columns
        if column.unique and not _has_unique_on(found, column.name)
    )

    return differences, statements, warnings


def _missing_column(spec: TableSpec, column: Column, statements: list[str]) -> Difference:
    """缺一列：补得上就补，补不上按破坏性处置（改列型不是补列）。"""
    if column.can_be_added():
        statements.append(spec.add_column_ddl(column.name))
        return Difference(DiffKind.MISSING_COLUMN, spec.name, column.name, "库内缺这一列")
    return Difference(
        DiffKind.MISSING_COLUMN,
        spec.name,
        column.name,
        "缺列且补不上（主键 / 唯一 / 非空无默认值）",
        destructive=True,
    )


def _compare_indexes(spec: TableSpec, found: _ActualTable) -> _Plan:
    """比索引：缺失即建、同名不同定义即拆掉重建、多出的只告警。"""
    differences: list[Difference] = []
    statements: list[str] = []
    warnings: list[str] = []

    declared_indexes = {spec.index_name(index): index for index in spec.indexes}
    for name, index in declared_indexes.items():
        actual_index = found.indexes.get(name)
        if actual_index is None:
            differences.append(
                Difference(DiffKind.MISSING_INDEX, spec.name, name, "库内缺这个索引")
            )
            statements.append(spec.index_ddl(index))
            continue
        if actual_index.unique != index.unique or actual_index.columns != index.columns:
            differences.append(
                Difference(
                    DiffKind.CHANGED_INDEX,
                    spec.name,
                    name,
                    "同名索引的定义变了（唯一性或列组合）",
                )
            )
            statements.append(f"DROP INDEX {quote_identifier(name)}")
            statements.append(spec.index_ddl(index))

    for name, actual_index in sorted(found.indexes.items()):
        if name in declared_indexes or actual_index.origin != "c":
            continue
        differences.append(Difference(DiffKind.EXTRA_INDEX, spec.name, name, "库里有、声明里没有"))
        warnings.append(f"多出的索引: {name}")

    return differences, statements, warnings


def _column_drift(column: Column, found: _ActualColumn) -> str | None:
    """列级漂移：类型、非空、主键、默认值任一项不同即算容器级不兼容。"""
    problems: list[str] = []
    expected_type = sql_type(column.type)
    if found.type.upper() != expected_type.upper():
        problems.append(f"类型 {found.type or '（空）'} → {expected_type}")
    if found.not_null != column.not_null:
        problems.append("非空约束变了")
    if found.primary_key != column.primary_key:
        problems.append("主键变了")
    if found.default != column.default_sql():
        problems.append(f"默认值 {found.default!r} → {column.default_sql()!r}")
    return "；".join(problems) or None


def _has_unique_on(table: _ActualTable, column: str) -> bool:
    """列级唯一在库里由唯一索引承载（SQLite 给 UNIQUE 列建 origin='u' 的隐式索引）。"""
    return any(
        index.origin == "u" and index.columns == (column,) for index in table.indexes.values()
    )


def _authorize(rebuild: RebuildPlan | None, targets: tuple[str, ...]) -> None:
    """破坏性动作必须显式授权，且授权要覆盖到每一张待重建的表。"""
    if rebuild is None:
        raise IndexSchemaError(
            "结构漂移须显式授权重建: " + ", ".join(targets) + "（开库时给出 RebuildPlan 才执行）"
        )
    missing = [name for name in targets if name not in rebuild.tables]
    if missing:
        raise IndexSchemaError("授权未覆盖这些表: " + ", ".join(missing))


def _looks_like_ours(actual: dict[str, _ActualTable], declared: set[str]) -> bool:
    """是不是本程序的索引库：有 meta，或至少有一张声明过的表。"""
    if META_TABLE in actual:
        return True
    return bool(declared & set(actual))


def _introspect(connection: sqlite3.Connection) -> dict[str, _ActualTable]:
    """读一遍库里的表、列与索引。"""
    tables: dict[str, _ActualTable] = {}
    for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
        name = str(row["name"])
        if name.startswith("sqlite_"):
            continue
        tables[name] = _read_table(connection, name)
    return tables


def _read_table(connection: sqlite3.Connection, name: str) -> _ActualTable:
    """读一张表的列与索引。"""
    table = _ActualTable()
    columns = connection.execute(f"PRAGMA table_info({quote_identifier(name)})").fetchall()
    for row in columns:
        default = row["dflt_value"]
        table.columns[str(row["name"])] = _ActualColumn(
            type=str(row["type"]),
            not_null=bool(row["notnull"]),
            primary_key=bool(row["pk"]),
            default=None if default is None else str(default),
        )
    indexes = connection.execute(f"PRAGMA index_list({quote_identifier(name)})").fetchall()
    for row in indexes:
        index_name = str(row["name"])
        table.indexes[index_name] = _ActualIndex(
            unique=bool(row["unique"]),
            origin=str(row["origin"]),
            columns=_index_columns(connection, index_name),
        )
    return table


def _index_columns(connection: sqlite3.Connection, name: str) -> tuple[str, ...]:
    """读一个索引的列，顺序即索引定义里的顺序。"""
    rows = connection.execute(f"PRAGMA index_info({quote_identifier(name)})").fetchall()
    return tuple(str(row["name"]) for row in rows)


def _stored_signature(connection: sqlite3.Connection) -> str | None:
    """读库内登记的声明签名；没登记过（或表不在）即 ``None``。"""
    try:
        row = connection.execute(
            # 表名是本模块的常量，且经 quote_identifier 加引号；值全部参数化
            f"SELECT value FROM {quote_identifier(META_TABLE)} WHERE name = ?",
            (DECLARATION_KEY,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return None if row is None else str(row["value"])


def _write_signature(connection: sqlite3.Connection, signature: str) -> None:
    """把当前声明的签名登记进 `meta`（开库对齐后即更新，供下次比对）。"""
    connection.execute(
        f"INSERT INTO {quote_identifier(META_TABLE)} (name, value) VALUES (?, ?) "
        f"ON CONFLICT(name) DO UPDATE SET value = excluded.value",
        (DECLARATION_KEY, signature),
    )


__all__ = [
    "DECLARATION_KEY",
    "DROPPED_SUFFIX",
    "META_TABLE",
    "Alignment",
    "DiffKind",
    "Difference",
    "Index",
    "RebuildPlan",
]

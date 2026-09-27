# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""表声明：**配置是本体**，本模块负责读、校验、编译。

设计见 `docs/architecture/storage-design.md` §8.4、§8.6。分工：

- **配置文件**（`config/settings/core/storage/conf.json` 的 ``storage.db.tables``）是**声明本体**：
  人写得出来、改得动、评审时一眼读完，不必读 Python；
- **本模块**只做三件事：把配置描述解析成 :class:`Table`（**顺带校验，非法即抛**）、
  编译成建表与建索引语句（:meth:`Table.ddl`）、供索引库做对比与处置；
- **源码内不出现建表 SQL**：方言只出现在编译器一处。

``_DEFAULT_TABLES`` 是出厂声明（三张内核表的初值）：配置里丢了这项时由它补齐；
它在配置里是**可改的**，改完由 `tools/gen_conf.py` 写回值文件，人直接在值文件里编辑即可。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from core.types.errors import CairnError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

_IDENT_ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


class ColumnType(Enum):
    """中立列类型：**只认这几种**，方言词由编译器映射（"不写 SQL"的落点）。"""

    TEXT = "text"
    """文本。"""

    INTEGER = "integer"
    """整数（含 unix 毫秒时间）。"""

    REAL = "real"
    """浮点。"""

    BLOB = "blob"
    """二进制。"""

    BOOLEAN = "boolean"
    """布尔。"""


class RebuildTier(Enum):
    """重建档：声明必须回答"这张表能不能由载体重建"（§8.5）。"""

    TIER1 = "tier1"
    """内核纯净态：可由载体扫描重建。"""

    TIER2 = "tier2"
    """领域态但来源在载体：可由载体重算（需领域逻辑）。"""

    TIER3 = "tier3"
    """真源在库内：**不可重建**，只能靠备份。"""


class Owned(Enum):
    """归属：内核表还是领域表（决定建表在什么时机被发现）。"""

    CORE = "core"
    """内核自有：开库即对齐。"""

    DOMAIN = "domain"
    """领域增量：挂载该域时才对齐。"""


def _check_ident(value: str, *, what: str) -> str:
    """标识符校验：小写字母 / 数字 / 下划线，且不以数字开头。

    表名与列名会进 SQL（哪怕是从配置编译来的），故在**解析口**就卡死。
    """
    if not value or value[0].isdigit() or not set(value) <= _IDENT_ALLOWED:
        raise CairnError(f"非法{what}: {value!r}（只允许小写字母 / 数字 / 下划线，且不以数字开头）")
    return value


@dataclass(frozen=True, slots=True)
class Column:
    """一列：名字、类型、约束。"""

    name: str
    type: ColumnType
    primary_key: bool = False
    not_null: bool = False
    unique: bool = False
    default: object = None
    """默认值（``None`` = 不写默认）。只收标量：复杂结构属于数据，该进块。"""
    doc: str = ""

    def __post_init__(self) -> None:
        """校验：标识符合法；主键必然非空；默认值只收标量。"""
        _check_ident(self.name, what="列名")
        if self.primary_key and not self.not_null:
            object.__setattr__(self, "not_null", True)  # 主键非空：由声明推出，不必手写
        if self.default is not None and not isinstance(self.default, (str, int, float, bool)):
            raise CairnError(
                f"列 {self.name} 的默认值只允许标量，得到 {type(self.default).__name__}"
                "（复杂结构属于数据，应进块）"
            )

    def clause(self) -> str:
        """编译成列定义片段（方言只在这里出现）。"""
        parts = [f'"{self.name}"', _SQL_TYPE_NAMES[self.type]]
        if self.primary_key:
            parts.append("PRIMARY KEY")
        if self.not_null:
            parts.append("NOT NULL")
        if self.unique:
            parts.append("UNIQUE")
        if self.default is not None:
            parts.append(f"DEFAULT {_literal(self.default)}")
        return " ".join(parts)

    def to_config(self) -> dict[str, Any]:
        """写成配置形状（只写非默认项，**保持文件干净**；往返必须无损）。"""
        item: dict[str, Any] = {"name": self.name, "type": self.type.value}
        if self.primary_key:
            item["primary_key"] = True
        if self.unique:
            item["unique"] = True
        if self.not_null and not self.primary_key:
            item["not_null"] = True  # 主键的非空是推出的，不重复写
        if self.default is not None:
            item["default"] = self.default
        if self.doc:
            item["doc"] = self.doc
        return item

    def signature(self) -> dict[str, object]:
        """规范化描述（比对与巡检用；**键序固定**，故可读也可算摘要）。"""
        return {
            "name": self.name,
            "type": self.type.value,
            "primary_key": self.primary_key,
            "not_null": self.not_null,
            "unique": self.unique,
            "default": self.default,
        }


@dataclass(frozen=True, slots=True)
class Index:
    """一个索引：列组合 + 是否唯一。"""

    columns: tuple[str, ...]
    unique: bool = False
    doc: str = ""

    def __post_init__(self) -> None:
        """校验：至少一列、列名合法、组合内不重复。"""
        if not self.columns:
            raise CairnError("索引至少要有一列")
        for name in self.columns:
            _check_ident(name, what="索引列名")
        if len(set(self.columns)) != len(self.columns):
            raise CairnError(f"索引列重复: {self.columns!r}")

    @property
    def name(self) -> str:
        """索引名由列组合推出（不手写，免漂移）。"""
        return f"idx_{'_'.join(self.columns)}"

    def clause(self) -> str:
        """编译成建索引语句（``{table}`` 由调用方填表名）。"""
        unique = "UNIQUE " if self.unique else ""
        columns = ", ".join(f'"{name}"' for name in self.columns)
        return f'CREATE {unique}INDEX IF NOT EXISTS "{self.name}" ON "{{table}}" ({columns})'

    def to_config(self) -> dict[str, Any]:
        """写成配置形状。"""
        item: dict[str, Any] = {"columns": list(self.columns)}
        if self.unique:
            item["unique"] = True
        if self.doc:
            item["doc"] = self.doc
        return item

    def signature(self) -> dict[str, object]:
        """规范化描述。"""
        return {"columns": list(self.columns), "unique": self.unique}


@dataclass(frozen=True, slots=True)
class Table:
    """一张表：名字、列、索引、重建档、归属、说明。"""

    name: str
    columns: tuple[Column, ...]
    tier: RebuildTier
    rebuild_from: str = ""
    """重建来源（档一 / 档二必填；档三留空且表示"只能靠备份"）。"""
    owner: Owned = Owned.CORE
    indexes: tuple[Index, ...] = ()
    doc: str = ""

    def __post_init__(self) -> None:
        """校验：标识符合法、至少一列、列名不重复、恰好一个主键、索引列必须存在。

        档三**不得**写重建来源、档一 / 档二**必须**写：含糊的重建档等于没有档。
        """
        _check_ident(self.name, what="表名")
        if not self.columns:
            raise CairnError(f"表 {self.name} 至少要有一列")
        names = [column.name for column in self.columns]
        duplicated = {name for name in names if names.count(name) > 1}
        if duplicated:
            raise CairnError(f"表 {self.name} 列名重复: {sorted(duplicated)}")
        keys = [column.name for column in self.columns if column.primary_key]
        if len(keys) != 1:
            raise CairnError(f"表 {self.name} 必须恰好一个主键，得到 {keys!r}")
        missing = [
            name for index in self.indexes for name in index.columns if name not in names
        ]
        if missing:
            raise CairnError(f"表 {self.name} 的索引列不存在: {sorted(set(missing))}")
        if self.tier is RebuildTier.TIER3 and self.rebuild_from:
            raise CairnError(f"表 {self.name} 属档三（不可重建），不该写重建来源")
        if self.tier is not RebuildTier.TIER3 and not self.rebuild_from:
            raise CairnError(f"表 {self.name} 的重建来源必填（档一 / 档二须说明从哪重建）")

    @property
    def key(self) -> str:
        """配置键：每张表在 ``storage.db.tables`` 里占一项，键即表名。"""
        return self.name

    def ddl(self) -> tuple[str, ...]:
        """编译成建表语句与建索引语句（第一条是建表）。"""
        columns = ", ".join(column.clause() for column in self.columns)
        statements = [f'CREATE TABLE IF NOT EXISTS "{self.name}" ({columns})']
        statements.extend(index.clause().format(table=self.name) for index in self.indexes)
        return tuple(statements)

    def to_config(self) -> dict[str, Any]:
        """写成配置形状（人读的那一份；顺序即书写顺序）。"""
        item: dict[str, Any] = {
            "name": self.name,
            "doc": self.doc,
            "tier": self.tier.value,
            "owner": self.owner.value,
        }
        if self.rebuild_from:
            item["rebuild_from"] = self.rebuild_from
        item["columns"] = [column.to_config() for column in self.columns]
        if self.indexes:
            item["indexes"] = [index.to_config() for index in self.indexes]
        return item

    def signature(self) -> dict[str, object]:
        """规范化描述：列与索引**按名排序**（书写顺序不该让比对结果变来变去）。"""
        return {
            "name": self.name,
            "tier": self.tier.value,
            "owner": self.owner.value,
            "rebuild_from": self.rebuild_from,
            "doc": self.doc,
            "columns": [
                column.signature() for column in sorted(self.columns, key=lambda item: item.name)
            ],
            "indexes": [
                index.signature() for index in sorted(self.indexes, key=lambda item: item.name)
            ],
        }


_SQL_TYPE_NAMES: dict[ColumnType, str] = {
    ColumnType.TEXT: "TEXT",
    ColumnType.INTEGER: "INTEGER",
    ColumnType.REAL: "REAL",
    ColumnType.BLOB: "BLOB",
    ColumnType.BOOLEAN: "INTEGER",
}
"""中立类型 → 方言类型（**编译器唯一的方言映射处**）。"""


def sql_type_name(kind: ColumnType) -> str:
    """中立类型对应的方言类型名（比对实际结构时用**同一个口径**）。"""
    return _SQL_TYPE_NAMES[kind]


def _literal(value: object) -> str:
    """把默认值编成 SQL 字面量（只收标量，故不必担心注入）。"""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


# ---- 解析：配置描述 → 声明 ----


def _require(mapping: Mapping[str, Any], key: str, *, where: str) -> Any:
    """取必填键；缺失即抛（静默补默认会把"写错了"伪装成"本来就没有"）。"""
    if key not in mapping:
        raise CairnError(f"{where} 缺少必填项 {key!r}")
    return mapping[key]


def parse_column(raw: Mapping[str, Any], *, table: str) -> Column:
    """解析一列；未知键一律报错（防拼错后静默失效）。"""
    where = f"表 {table} 的列"
    name = str(_require(raw, "name", where=where))
    type_text = str(_require(raw, "type", where=where))
    try:
        kind = ColumnType(type_text)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in ColumnType)
        raise CairnError(f"{where} {name} 的类型非法: {type_text!r}（可用：{allowed}）") from exc
    known = {"name", "type", "primary_key", "not_null", "unique", "default", "doc"}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise CairnError(f"{where} {name} 有未知项: {unknown}")
    return Column(
        name=name,
        type=kind,
        primary_key=bool(raw.get("primary_key", False)),
        not_null=bool(raw.get("not_null", False)),
        unique=bool(raw.get("unique", False)),
        default=raw.get("default"),
        doc=str(raw.get("doc", "")),
    )


def parse_index(raw: Mapping[str, Any], *, table: str) -> Index:
    """解析一个索引。"""
    where = f"表 {table} 的索引"
    columns = _require(raw, "columns", where=where)
    if not isinstance(columns, (list, tuple)):
        raise CairnError(f"{where} 的 columns 必须是列表")
    known = {"columns", "unique", "doc"}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise CairnError(f"{where} 有未知项: {unknown}")
    return Index(
        columns=tuple(str(name) for name in columns),
        unique=bool(raw.get("unique", False)),
        doc=str(raw.get("doc", "")),
    )


def parse_table(raw: Mapping[str, Any]) -> Table:
    """解析一张表；项名写错即抛（表 / 列 / 索引三级都查未知项）。"""
    where = "表声明"
    name = str(_require(raw, "name", where=where))
    where = f"表 {name}"
    tier_text = str(_require(raw, "tier", where=where))
    try:
        tier = RebuildTier(tier_text)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in RebuildTier)
        raise CairnError(f"{where} 的重建档非法: {tier_text!r}（可用：{allowed}）") from exc
    try:
        owner = Owned(str(raw.get("owner", Owned.CORE.value)))
    except ValueError as exc:
        allowed = ", ".join(item.value for item in Owned)
        raise CairnError(f"{where} 的归属非法: {raw.get('owner')!r}（可用：{allowed}）") from exc
    known = {"name", "doc", "tier", "owner", "rebuild_from", "columns", "indexes"}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise CairnError(f"{where} 有未知项: {unknown}")
    raw_columns = _require(raw, "columns", where=where)
    if not isinstance(raw_columns, list):
        raise CairnError(f"{where} 的 columns 必须是列表")
    raw_indexes = raw.get("indexes", [])
    if not isinstance(raw_indexes, list):
        raise CairnError(f"{where} 的 indexes 必须是列表")
    return Table(
        name=name,
        columns=tuple(parse_column(item, table=name) for item in raw_columns),
        tier=tier,
        rebuild_from=str(raw.get("rebuild_from", "")),
        owner=owner,
        indexes=tuple(parse_index(item, table=name) for item in raw_indexes),
        doc=str(raw.get("doc", "")),
    )


def parse_tables(raw: Iterable[Mapping[str, Any]]) -> tuple[Table, ...]:
    """解析整组声明；表名重复即抛。"""
    parsed = tuple(parse_table(item) for item in raw)
    names = [table.name for table in parsed]
    duplicated = {name for name in names if names.count(name) > 1}
    if duplicated:
        raise CairnError(f"表声明重复: {sorted(duplicated)}")
    return parsed


def declared_tables() -> tuple[Table, ...]:
    """读配置里的表声明（**运行时的唯一入口**）：配置是本体，这里只解析与校验。"""
    from .conf import conf  # noqa: PLC0415 — 与声明模块同包，运行时取

    raw: list[dict[str, Any]] = conf.db_tables
    return parse_tables(raw)


def core_tables() -> tuple[Table, ...]:
    """内核表（归属为 core 的那些），开库时对齐。"""
    return tuple(table for table in declared_tables() if table.owner is Owned.CORE)


def domain_tables() -> tuple[Table, ...]:
    """领域表（挂载该域时才对齐）。"""
    return tuple(table for table in declared_tables() if table.owner is Owned.DOMAIN)


def table(name: str) -> Table | None:
    """按表名取声明；没声明返回 ``None``。"""
    for found in declared_tables():
        if found.name == name:
            return found
    return None


__all__ = [
    "Column",
    "ColumnType",
    "Index",
    "Owned",
    "RebuildTier",
    "Table",
    "core_tables",
    "declared_tables",
    "domain_tables",
    "parse_table",
    "parse_tables",
    "sql_type_name",
    "table",
]

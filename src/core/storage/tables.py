# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""索引库的**表声明**：表长什么样写在声明里，**源码内不出现建表 SQL**。

设计见 `docs/architecture/storage-design.md` §8.4、§8.6。三条规矩：

1. **声明即事实**：表名、列、类型、约束、索引、重建档都写在声明里；建表语句由声明**编译**出来
   （:meth:`Table.ddl`），故方言只出现在编译器一处；
2. **类型词汇中立**：只认 :class:`ColumnType` 里那几种，不写 ``TEXT`` / ``INTEGER`` 这类方言词。
   加新类型要过这一层，于是"能不能落盘"是设计问题，不是随手写一句 SQL；
3. **每条表声明带重建档**（:class:`RebuildTier`）：域介入后索引库不再整体可重建，
   **写不出重建来源的表就是不可重建表**，必须纳入备份（§8.5）。

内核三张表在文件末尾声明：``record``（身份到位置）、``bucket``（桶登记）、``edge``（关系边）。
领域表由各域在自己的声明模块里增量声明，走同一套机制。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.types.errors import CairnError

_IDENT_ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


class ColumnType(Enum):
    """中立列类型：**只认这几种**，方言词由编译器映射（不写 SQL 的落点）。"""

    TEXT = "text"
    """文本。"""

    INTEGER = "integer"
    """整数（含 unix 毫秒时间；整数与布尔分开写）。"""

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


def _check_ident(value: str, *, what: str) -> str:
    """标识符校验：小写字母 / 数字 / 下划线，且不以数字开头。

    表名与列名会进 SQL（哪怕是从声明编译来的），故在**入声明口**就卡死，
    而不是等编译时拼接字符串。
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
    """默认值（``None`` = 不写默认）。只允许标量与 ``bool``：复杂结构该进块，不进表。"""
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
        parts = [f'"{self.name}"', _SQL_TYPES[self.type]]
        if self.primary_key:
            parts.append("PRIMARY KEY")
        if self.not_null:
            parts.append("NOT NULL")
        if self.unique:
            parts.append("UNIQUE")
        if self.default is not None:
            parts.append(f"DEFAULT {_literal(self.default)}")
        return " ".join(parts)

    def signature(self) -> tuple[str, str, bool, bool, bool, str]:
        """规范化签名：序对（列名 / 类型 / 约束 / 默认值）——比对与摘要都用它。"""
        return (
            self.name,
            self.type.value,
            self.primary_key,
            self.not_null,
            self.unique,
            "" if self.default is None else repr(self.default),
        )


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
        """编译成建索引语句。"""
        unique = "UNIQUE " if self.unique else ""
        columns = ", ".join(f'"{name}"' for name in self.columns)
        return f'CREATE {unique}INDEX IF NOT EXISTS "{self.name}" ON "{{table}}" ({columns})'

    def signature(self) -> tuple[tuple[str, ...], bool]:
        """规范化签名。"""
        return (self.columns, self.unique)


@dataclass(frozen=True, slots=True)
class Table:
    """一张表：名字、列、索引、重建档、说明。"""

    name: str
    columns: tuple[Column, ...]
    tier: RebuildTier
    rebuild_from: str = ""
    """重建来源（档一 / 档二必填；档三留空且表示"只能靠备份"）。"""
    indexes: tuple[Index, ...] = ()
    doc: str = ""

    def __post_init__(self) -> None:
        """校验：标识符合法、至少一列、列名不重复、恰好一个主键、索引列必须存在。

        档三**不得**写重建来源、档一 / 档二**必须**写：含糊其辞的重建档等于没有档。
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
        for index in self.indexes:
            missing = [name for name in index.columns if name not in names]
            if missing:
                raise CairnError(f"表 {self.name} 的索引列不存在: {missing}")
        if self.tier is RebuildTier.TIER3 and self.rebuild_from:
            raise CairnError(f"表 {self.name} 属档三（不可重建），不该写重建来源")
        if self.tier is not RebuildTier.TIER3 and not self.rebuild_from:
            raise CairnError(f"表 {self.name} 的重建来源必填（档一 / 档二须说明从哪重建）")

    @property
    def key(self) -> str:
        """配置键：声明也走配置引擎投影，故每张表有一个键。"""
        return f"storage.table.{self.name}"

    def ddl(self) -> tuple[str, ...]:
        """编译成建表语句与建索引语句（第一条是建表）。"""
        columns = ", ".join(column.clause() for column in self.columns)
        statements = [f'CREATE TABLE IF NOT EXISTS "{self.name}" ({columns})']
        statements.extend(index.clause().format(table=self.name) for index in self.indexes)
        return tuple(statements)

    def signature(self) -> dict[str, object]:
        """规范化描述：**确定性**（列与索引按名排序），故可算摘要、可投影进配置。

        排序是刻意的：声明的书写顺序不该让摘要变来变去。
        """
        return {
            "name": self.name,
            "tier": self.tier.value,
            "rebuild_from": self.rebuild_from,
            "columns": [
                list(column.signature()) for column in sorted(self.columns, key=lambda c: c.name)
            ],
            "indexes": [
                [list(index.signature()[0]), index.signature()[1]]
                for index in sorted(self.indexes, key=lambda i: i.name)
            ],
            "doc": self.doc,
        }


_SQL_TYPES: dict[ColumnType, str] = {
    ColumnType.TEXT: "TEXT",
    ColumnType.INTEGER: "INTEGER",
    ColumnType.REAL: "REAL",
    ColumnType.BLOB: "BLOB",
    ColumnType.BOOLEAN: "INTEGER",
}
"""中立类型 → 方言类型（**编译器唯一的方言映射处**）。"""

_SQL_TYPE_NAMES: dict[ColumnType, str] = {kind: name.upper() for kind, name in _SQL_TYPES.items()}


def sql_type_name(kind: ColumnType) -> str:
    """中立类型对应的方言类型名（比对实际结构时用**同一个口径**，不另写一份映射）。"""
    return _SQL_TYPE_NAMES[kind]


def _literal(value: object) -> str:
    """把默认值编成 SQL 字面量（只收标量，故不必担心注入）。"""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


_REGISTRY: dict[str, Table] = {}


def register(table: Table) -> Table:
    """登记一条表声明；同名重复登记且内容不一致即报错（不静默覆盖）。"""
    found = _REGISTRY.get(table.name)
    if found is not None and found != table:
        raise CairnError(f"表声明重复且不一致: {table.name!r}")
    _REGISTRY[table.name] = table
    return table


def tables() -> list[Table]:
    """全部表声明（按表名排序）。"""
    return [_REGISTRY[name] for name in sorted(_REGISTRY)]


def table(name: str) -> Table | None:
    """按表名取声明；没登记返回 ``None``。"""
    return _REGISTRY.get(name)


def clear() -> None:
    """清空登记表（**给测试隔离用**；产品代码不该调）。"""
    _REGISTRY.clear()


class CoreTable(Enum):
    """内核自有表的声明：类体里绑上即登记（与 ``Cfg`` / ``Attr`` 同族的写法）。

    成员名即表名，故 ``CoreTable.RECORD.value`` 就是内核的定位表声明。
    """

    RECORD = Table(
        name="record",
        tier=RebuildTier.TIER1,
        rebuild_from="载体：顺扫全部记录，读记录头重建",
        doc="身份到位置：一行一条记录（含块记录与内容记录）",
        columns=(
            Column("value_uuid", ColumnType.TEXT, primary_key=True, doc="分配形态凭证"),
            Column("value_hash", ColumnType.TEXT, not_null=True, doc="摘要形态凭证（指向内容）"),
            Column("kind", ColumnType.TEXT, not_null=True, default="", doc="类型名（由程序给出）"),
            Column("bucket", ColumnType.TEXT, not_null=True, default="", doc="所在桶"),
            Column("pack", ColumnType.TEXT, not_null=True, default="", doc="所在载体名"),
            Column("slot_start", ColumnType.INTEGER, not_null=True, default=0, doc="起始槽"),
            Column("slot_head", ColumnType.INTEGER, not_null=True, default=0, doc="槽内偏移"),
            Column("slot_count", ColumnType.INTEGER, not_null=True, default=1, doc="跨槽数"),
            Column(
                "body_addr", ColumnType.TEXT, not_null=True, default="", doc="内容凭证（块记录用）"
            ),
            Column("size", ColumnType.INTEGER, not_null=True, default=0, doc="记录字节数"),
            Column("issued", ColumnType.INTEGER, not_null=True, default=0, doc="ID 签发时刻"),
            Column("created", ColumnType.INTEGER, not_null=True, default=0, doc="落盘时刻"),
            Column("updated", ColumnType.INTEGER, not_null=True, default=0, doc="最近写入时刻"),
        ),
        indexes=(
            Index(("value_hash",), doc="地址反查（去重命中时问“这份内容在哪”）"),
            Index(("kind",), doc="按类型筛选"),
            Index(("bucket", "pack"), doc="按载体归拢"),
            Index(("updated",), doc="按时间排序"),
        ),
    )
    BUCKET = Table(
        name="bucket",
        tier=RebuildTier.TIER1,
        rebuild_from="桶目录：扫 vault 下的桶目录",
        doc="桶登记：桶目录是存在证明，本表是登记",
        columns=(
            Column(
                "name", ColumnType.TEXT, primary_key=True, doc="桶名（即目录名，进 ID 的 scope）"
            ),
            Column(
                "role", ColumnType.TEXT, not_null=True, default="main", doc="形态：主 / 归档 / 临时"
            ),
            Column("state", ColumnType.TEXT, not_null=True, default="mounted", doc="挂载状态"),
            Column("created", ColumnType.INTEGER, not_null=True, default=0, doc="建立时刻"),
        ),
    )
    EDGE = Table(
        name="edge",
        tier=RebuildTier.TIER1,
        rebuild_from="块记录：关系数据落在块内时由其派生",
        doc="关系边：一等行，src --kind--> dst",
        columns=(
            Column("id", ColumnType.TEXT, primary_key=True, doc="边身份"),
            Column("src", ColumnType.TEXT, not_null=True, doc="源身份"),
            Column("dst", ColumnType.TEXT, not_null=True, doc="目标身份"),
            Column("kind", ColumnType.TEXT, not_null=True, default="", doc="关系种类"),
            Column("domain", ColumnType.TEXT, not_null=True, default="", doc="归属域"),
            Column("created", ColumnType.INTEGER, not_null=True, default=0, doc="建立时刻"),
        ),
        indexes=(
            Index(("src", "kind"), doc="出边（正向遍历）"),
            Index(("dst", "kind"), doc="入边（反查 / backlinks）"),
        ),
    )


def core_tables() -> tuple[Table, ...]:
    """内核三张表的声明（顺序固定：定位、桶、边）。"""
    return tuple(member.value for member in CoreTable)


def canonical_tables() -> dict[str, dict[str, object]]:
    """全部表声明的规范化描述：**投影进配置的东西**（每表一条，键即 :attr:`Table.key`）。"""
    return {table_.key: table_.signature() for table_ in tables()}


def register_core() -> None:
    """把内核表登记进登记表（幂等；模块导入时调用一次）。"""
    for declared in core_tables():
        register(declared)


register_core()  # 导入即登记：内核三张表是该模块的声明本体


__all__ = [
    "Column",
    "ColumnType",
    "CoreTable",
    "Index",
    "RebuildTier",
    "Table",
    "canonical_tables",
    "clear",
    "core_tables",
    "register",
    "register_core",
    "sql_type_name",
    "table",
    "tables",
]

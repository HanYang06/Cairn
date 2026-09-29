# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""表声明：中立类型、约束、索引与重建档；建表语句由声明编译出来。

设计篇 §8.4 / §8.6 的规矩都落在这一处：

- **源码内不得出现建表 SQL**：声明是数据，DDL 是它编译出来的产物，方言只出现在编译器里；
- **类型词汇中立**：只认文本 / 整数 / 实数 / 二进制 / 布尔五种。加一种类型要过这一层，
  于是"能不能落盘"是设计问题，而不是写一句 SQL 就能决定的事；
- **解析口严格**：未知项、非法类型、重复表名或列名、缺必填项、重建档与重建来源不匹配，
  一律报错、不静默忽略——声明写坏了必须当场看得见；
- **索引名由表名与列组合推出**（`idx_<表>_<列>`），不手写；并在声明集这一层查**跨表重名**：
  SQLite 的索引名整库唯一，撞名会让后一条 `CREATE INDEX IF NOT EXISTS` 静默跳过；
- **`doc` 不进签名**：`signature` 是开库比对的依据，注释文本参与比对会把"改一句注释"
  变成"库打不开"。签名里列与索引按名排序，故书写顺序不影响它。

重建档只有两项，判据是"写不写得出重建来源"：`DERIVED`（可由真源重算）与 `SOURCE`
（真源就在库里，只能靠备份）。设计篇 §8.5 的"档二"描述的是**领域介入后的整库性质**，
不是第三档表；每张领域表都得落进这两项之一，含糊的声明在这里就被拦下。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path  # noqa: TC003 — `tables_path()` 在运行期真的用 Path 拼路径
from typing import TYPE_CHECKING, cast

import yaml

from core.exc import TableDeclarationError

from .registry import BINDABLE_FIELDS, POINTER_FIELDS, TABLES_FILENAME

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ColumnType(Enum):
    """中立类型：只认这五种，加类型要过声明层（§8.6）。"""

    TEXT = "text"
    INTEGER = "integer"
    REAL = "real"
    BLOB = "blob"
    BOOLEAN = "boolean"


class Tier(Enum):
    """重建档：判据是"写不写得出重建来源"（§8.5）。"""

    DERIVED = "derived"
    """档一：由真源（载体、目录）派生，可重建。**必须**写明重建来源。"""

    SOURCE = "source"
    """档三：真源就在库里，重建不成立，只能靠备份。**禁止**写重建来源。"""


class ColumnSource(Enum):
    """一列的值从哪儿来（设计篇 §8，"去数据库化"的落点）。

    库里只放**ID 的面**；一列要么是 ID 的字段，要么必须写明它的来路，没有匿名列。
    """

    IDENTITY = "identity"
    """绑定列：**列名就是 ID 的字段名**（`value_uuid` / `value_hash` / `birth_time` / `name`）。

    类型不标在声明里——它从 `ID` 的字段定义推出来，这里再写一份只会与 ID 漂移。
    """

    STORED = "store"
    """观测列：存储层顺扫载体时看见的东西（hub / pack / 格区间 / 大小）。"""

    PROGRAM = "prog"
    """程序给的列：写的时候由程序给出，记录头里没有（如 `kind`）。"""

    REFERENCE = "ref"
    """引用列：值是**另一个 ID**（关系表的端点），不是本行主语的字段。"""

    DIGEST = "digest"
    """派生列：由本表其它列算出的摘要（如边身份 `edge.id`）。"""


#: 能从载荷指针里取到的字段：指针只承载两套凭证（设计篇 §3.2.1）
#: 能绑成列的 ID 字段与「能依赖默认为空」的判据都在登记层（`registry.py`）；
#: 它们对全部表一视同仁——**不再有身份表那种特例**（名字是表的坐标，不是行里的判别列）。

#: 绑定列的类型由 `ID` 的字段推出（设计篇 §3.2），声明里不写
_COLUMN_TYPE_OF_ID: dict[str, ColumnType] = {
    "name": ColumnType.TEXT,
    "value_uuid": ColumnType.TEXT,
    "value_hash": ColumnType.TEXT,
    "birth_time": ColumnType.INTEGER,
}

#: 绑定到别处的指针时，只能带两套凭证中那两种列名里的字段
_POINTER_FIELDS = POINTER_FIELDS

#: 允许留空的绑定字段：摘要未绑定内容时为空串，签发时刻重扫读不回来
_MAY_BE_EMPTY: frozenset[str] = frozenset({"value_hash", "birth_time", "name"})

_SQL_TYPES: dict[ColumnType, str] = {
    ColumnType.TEXT: "TEXT",
    ColumnType.INTEGER: "INTEGER",
    ColumnType.REAL: "REAL",
    ColumnType.BLOB: "BLOB",
    ColumnType.BOOLEAN: "INTEGER",
}
"""中立类型到 SQLite 类型的映射：方言只出现在这张表里。"""

DefaultValue = str | int | float | bytes | bool


@dataclass(frozen=True, slots=True)
class Column:
    """一列：名字、来源（或绑定的 ID 字段）、中立类型与四个约束开关。

    Attributes:
        name: 列名（ASCII 标识符）；绑定列时它同时就是 `ID` 的字段名。
        type: 中立类型；绑定列由校验器按 `ID` 的字段核对。
        primary_key: 是否主键（单列写法；复合主键写在 :attr:`TableSpec.primary_key`）。
        unique: 是否唯一。列级唯一由 SQLite 的列约束表达，索引唯一性由索引声明表达。
        not_null: 是否非空。
        default: 默认值；``None`` 表示不设默认值（SQLite 里与默认 NULL 等价）。
        doc: 说明文本；**不进签名**。
        qualifier: 限定词；绑定**别处的 ID** 时写它的位置名（如 `body`），空串表示本行主语。
        source: 值从哪儿来；``IDENTITY`` 时 :attr:`name` 必须是 `ID` 的字段名。
        identity: 这一列是不是"被绑定的 ID 身份字段"（词表 `name` 判它、主键必须是它）。
    """

    name: str
    type: ColumnType
    primary_key: bool = False
    unique: bool = False
    not_null: bool = False
    default: DefaultValue | None = None
    doc: str = ""
    qualifier: str = ""
    source: ColumnSource = ColumnSource.PROGRAM
    identity: bool = False

    @property
    def bound(self) -> bool:
        """是不是绑定列（值来自本行主语那个 ID 的字段）。"""
        return self.source is ColumnSource.IDENTITY

    @property
    def queryable(self) -> bool:
        """是不是"天然可当查询词"的列：绑定列与引用列都算（关系表靠它按端点查）。"""
        return self.source in {ColumnSource.IDENTITY, ColumnSource.REFERENCE}

    @property
    def reference(self) -> str:
        """在签名与报错里用的完整写法：`限定词.列名` 或裸列名。"""
        return f"{self.qualifier}.{self.name}" if self.qualifier else self.name

    @property
    def sql_name(self) -> str:
        """库里的列名。

        带限定词的列加前缀（`id(body).value_hash` → `body_value_hash`），免得同一张表里
        两个 ID 的同名字段撞名；不带限定词的（本行主语那些字段）就是裸字段名。
        """
        if not self.qualifier:
            return self.name
        return f"{self.qualifier}_{self.name}"

    def bound_field(self) -> str:
        """绑定列取的 ID 字段名；不是绑定列即报错。"""
        if not self.bound:
            raise TableDeclarationError(f"列 {self.reference} 不是绑定列，取不到 ID 字段")
        return self.name

    def ddl(self) -> str:
        """编译成建表语句里的一段，形如 ``"列名" TYPE NOT NULL DEFAULT …``。

        主键由 :meth:`TableSpec.create_table_ddl` 以表级约束写出（复合主键没法写在列上）。
        """
        parts = [quote_identifier(self.sql_name), sql_type(self.type)]
        if self.not_null:
            parts.append("NOT NULL")
        if self.unique:
            parts.append("UNIQUE")
        default = self.default_sql()
        if default is not None:
            parts.append(f"DEFAULT {default}")
        return " ".join(parts)

    def default_sql(self) -> str | None:
        """默认值的 SQL 字面量；没设默认值即 ``None``（SQLite 里与默认 NULL 等价）。"""
        return None if self.default is None else _literal(self.default, self.type)

    def can_be_added(self) -> bool:
        """能不能用 ``ALTER TABLE … ADD COLUMN`` 补上这一列。

        SQLite 补不了主键列与唯一列，非空列则必须带一个非空默认值——补不上的列只能按
        破坏性差异处置（改名隔离后重建），不能假装补上了。
        """
        if self.primary_key or self.unique:
            return False
        return not (self.not_null and self.default is None)

    def signature(self) -> str:
        """列在开库比对里的规范化描述（不含 ``doc``；含来源与身份位，它们是结构）。"""
        default = "-" if self.default is None else _literal(self.default, self.type)
        flags = "".join(
            flag
            for flag, on in (
                ("p", self.primary_key),
                ("u", self.unique),
                ("n", self.not_null),
                ("i", self.identity),
            )
            if on
        )
        return f"{self.reference}:{self.source.value}:{self.type.value}:{flags or '-'}:{default}"


@dataclass(frozen=True, slots=True)
class IndexSpec:
    """一个索引声明：列组合加唯一性开关。

    Attributes:
        columns: 参与索引的列，顺序即索引顺序（不影响索引名，名字按排序后的列推出）。
        unique: 是否唯一索引。
        doc: 说明文本；**不进签名**（签名只认列与唯一性）。
    """

    columns: tuple[str, ...]
    unique: bool = False
    doc: str = ""


@dataclass(frozen=True, slots=True)
class TableSpec:
    """一张表的声明：表名、重建档、列、索引、归属与说明。

    Attributes:
        name: 表名。
        tier: 重建档。
        columns: 列，顺序即书写顺序（签名的排序是另一回事）。
        indexes: 显式索引声明；绑定列的索引另有 :meth:`resolved_indexes` 兜底。
        owner: 归属（`core` / 领域名）；领域表的归属由声明给出。
        rebuild_from: 重建来源；重建档为 ``SOURCE`` 时必须为空。
        doc: 说明文本；**不进签名**。
        primary_key: 主键列名（有序，复合主键就是多个）；不给则取唯一的身份列。
    """

    name: str
    tier: Tier
    columns: tuple[Column, ...]
    indexes: tuple[IndexSpec, ...] = ()
    owner: str = "core"
    rebuild_from: str = ""
    doc: str = ""
    primary_key: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> TableSpec:
        """按解析口规矩从一份映射（未来即 YAML 的一项）读出一张表声明。

        Raises:
            TableDeclarationError: 未知项、缺必填项、非法标识符、非法类型、档与来源不匹配。
        """
        _reject_unknown(raw, _TABLE_KEYS, "表声明")
        name = _identifier(raw.get("name"), "表名")
        tier = _tier(raw.get("tier"))
        rebuild_from = _text(raw.get("rebuild_from", ""), "重建来源")
        if tier is Tier.DERIVED and not rebuild_from:
            raise TableDeclarationError(f"表 {name} 声明为可重建（derived），必须写明重建来源")
        if tier is Tier.SOURCE and rebuild_from:
            raise TableDeclarationError(
                f"表 {name} 声明为真源（source），不得写重建来源——两者不可兼得"
            )
        columns = _columns(raw.get("columns"))
        indexes = _indexes(raw.get("indexes", ()), columns)
        return cls(
            name=name,
            tier=tier,
            columns=columns,
            indexes=indexes,
            owner=_text(raw.get("owner", "core"), "归属"),
            rebuild_from=rebuild_from,
            doc=_text(raw.get("doc", ""), "说明"),
            primary_key=_key_columns(raw.get("primary_key")),
        )

    def __post_init__(self) -> None:
        """把声明立起来：先查主键写的列在不在，再核类型，最后定主键并核对绑定列。"""
        missing = [column for column in self.primary_key if self.column(column) is None]
        if missing:
            raise TableDeclarationError(f"表 {self.name} 的主键列不存在: {missing}")
        for column in self.columns:
            if column.type not in _SQL_TYPES:
                raise TableDeclarationError(
                    f"列 {self.name}.{column.reference} 的类型 {column.type!r} 不在词表里"
                )
        if self.primary_key:
            primary_key = self.primary_key
        elif len(self.identity_columns) == 1:
            primary_key = (self.identity_columns[0].name,)
        elif len(self.identity_columns) > 1:
            names = [column.name for column in self.identity_columns]
            raise TableDeclarationError(
                f"表 {self.name} 有多个身份列（{names}）：主键必须显式写明哪几列"
            )
        else:
            raise TableDeclarationError(
                f"表 {self.name} 必须有主键：绑一列 ID 字段，或显式写明 primary_key"
            )
        object.__setattr__(self, "primary_key", primary_key)
        self._check_binding()

    @property
    def identity_columns(self) -> tuple[Column, ...]:
        """本行的身份列：绑定到本行主语那个 ID 的字段（不带限定词）。

        **一张表一个身份列**：名字是表的坐标（谁用了 ID，表就叫什么），故主键总能在
        没写 `primary_key` 时由它推出来——不再有"多身份列必须明写"的情形。
        """
        return tuple(column for column in self.columns if column.source is ColumnSource.IDENTITY)

    def scopes(self) -> tuple[str, ...]:
        """这张表引用到的**作用域名**（限定词），按出现顺序去重。

        限定词就是"另一个 ID 的位置名"——它同时是一个表名（`id(name).字段` 的两个含义）。
        """
        return tuple(dict.fromkeys(column.qualifier for column in self.columns if column.qualifier))

    def resolved_indexes(self) -> tuple[IndexSpec, ...]:
        """实际要建的索引 = 显式声明 + **绑定列的兜底索引**。

        兜底的理由：绑定列就是"能拿它当查询词的那些列"，不该再要求第二处声明；
        主键开头那一列已经有序，跳过；已有某个索引以它打头，也跳过。
        """
        resolved = list(self.indexes)
        covered = {index.columns[0] for index in resolved}
        covered.update(self.primary_key[:1])
        for column in self.columns:
            if column.queryable and column.sql_name not in covered:
                resolved.append(IndexSpec(columns=(column.sql_name,)))
                covered.add(column.sql_name)
        return tuple(resolved)

    def column_names(self) -> tuple[str, ...]:
        """全部列名，书写顺序。"""
        return tuple(column.sql_name for column in self.columns)

    def column(self, name: str) -> Column | None:
        """按名取列；不存在返回 ``None``。"""
        for column in self.columns:
            if column.name == name:
                return column
        return None

    def key_columns(self) -> tuple[Column, ...]:
        """主键列，按声明顺序；缺列已在构造时拦下。"""
        columns = [self.column(name) for name in self.primary_key]
        return tuple(column for column in columns if column is not None)

    def _check_binding(self) -> None:
        """核对每一列的来源；列与列的规矩都在 :meth:`_check_column` 里。"""
        for column in self.columns:
            self._check_column(column)

    def _check_column(self, column: Column) -> None:
        """核对一列的来源：绑定的字段必须在落盘子集里，指针只带两套凭证。

        没有"身份表特例"：名字是表的坐标（谁用的 ID，表就叫什么），行里不再有判别列，
        故这两条对全部表一视同仁。
        """
        if not column.identity:
            return
        if column.name not in BINDABLE_FIELDS:
            raise TableDeclarationError(
                f"列 {self.name}.{column.reference} 绑不到 ID 的字段 {column.name}："
                f"可绑的是 {sorted(BINDABLE_FIELDS)}（落盘子集，见设计篇 §3.5）"
            )
        if column.source is ColumnSource.REFERENCE and column.name not in _POINTER_FIELDS:
            raise TableDeclarationError(
                f"列 {self.name}.{column.reference} 取不到：载荷里的指针只带两套凭证 "
                f"{sorted(_POINTER_FIELDS)}"
            )
        if (
            column.source is ColumnSource.IDENTITY
            and column.name == "value_uuid"
            and (not column.not_null)
        ):
            raise TableDeclarationError(
                f"绑定列 {self.name}.{column.reference} 必须非空：主键缺了值就没有身份"
            )
        expected = _COLUMN_TYPE_OF_ID[column.name]
        if column.type is not expected:
            raise TableDeclarationError(
                f"绑定列 {self.name}.{column.reference} 的类型写成了 {column.type.value}，"
                f"ID 的字段 {column.name} 是 {expected.value}——绑定列的类型由 ID 推出，不必写"
            )

    def index_name(self, index: IndexSpec) -> str:
        """索引名：``idx_<表>_<列...>``，列按名字排序，故声明里的书写顺序不影响它。"""
        return "_".join(("idx", self.name, *sorted(index.columns)))

    def index_names(self) -> tuple[str, ...]:
        """全部索引名（含绑定列兜底的那些），按名排序。"""
        return tuple(sorted(self.index_name(index) for index in self.resolved_indexes()))

    def create_table_ddl(self) -> str:
        """编译出建表语句；主键写成表级约束（复合主键没法挂在列上）。"""
        parts = [column.ddl() for column in self.columns]
        if self.primary_key:
            keys = ", ".join(quote_identifier(name) for name in self.primary_key)
            parts.append(f"PRIMARY KEY ({keys})")
        return f"CREATE TABLE IF NOT EXISTS {quote_identifier(self.name)} ({', '.join(parts)})"

    def index_ddl(self, index: IndexSpec) -> str:
        """把单个索引声明编译成建索引语句。"""
        return "CREATE {unique}INDEX IF NOT EXISTS {name} ON {table} ({columns})".format(
            unique="UNIQUE " if index.unique else "",
            name=quote_identifier(self.index_name(index)),
            table=quote_identifier(self.name),
            columns=", ".join(quote_identifier(column) for column in index.columns),
        )

    def create_index_ddl(self) -> tuple[str, ...]:
        """编译出建索引语句，按索引名排序使执行顺序确定。"""
        ordered = sorted(self.resolved_indexes(), key=self.index_name)
        return tuple(self.index_ddl(index) for index in ordered)

    def add_column_ddl(self, name: str) -> str:
        """把一列编译成 ``ALTER TABLE … ADD COLUMN``。

        Raises:
            TableDeclarationError: 该列不存在，或它补不上（主键 / 唯一 / 非空且无默认值）。
        """
        column = self.column(name)
        if column is None:
            raise TableDeclarationError(f"表 {self.name} 没有列 {name}")
        if not column.can_be_added():
            raise TableDeclarationError(f"列 {self.name}.{name} 补不上，须按重建处置")
        return f"ALTER TABLE {quote_identifier(self.name)} ADD COLUMN {column.ddl()}"

    def ddl(self) -> tuple[str, ...]:
        """建这张表所需的全部语句：先建表，再建索引。"""
        return (self.create_table_ddl(), *self.create_index_ddl())

    def signature(self) -> str:
        """开库比对用的规范化描述：列与索引都按名排序，且不含 ``doc``。"""
        columns = ";".join(sorted(column.signature() for column in self.columns))
        indexes = ";".join(
            f"{self.index_name(index)}={'u' if index.unique else 'n'}"
            for index in sorted(self.resolved_indexes(), key=self.index_name)
        )
        key = ",".join(self.primary_key)
        return (
            f"table={self.name}|tier={self.tier.value}|owner={self.owner}"
            f"|rebuild_from={self.rebuild_from}|pk=[{key}]|columns=[{columns}]|indexes=[{indexes}]"
        )


class Declaration:
    """一组表声明：查重（同名表、跨表撞索引名）后即可交给开库比对。

    Attributes:
        tables: 声明集里的表，顺序即书写顺序。
    """

    def __init__(self, tables: Sequence[TableSpec]) -> None:
        """登记一份声明集。

        Raises:
            TableDeclarationError: 表名为空、同名表重复、占用索引库自用表名，或跨表出现同名索引。
        """
        if not tables:
            raise TableDeclarationError("表声明集为空")
        seen: dict[str, TableSpec] = {}
        index_owner: dict[str, str] = {}
        for table in tables:
            if table.name == META_TABLE_SPEC.name:
                raise TableDeclarationError(f"{table.name} 是索引库自用表名，声明里不得占用")
            if table.name in seen:
                raise TableDeclarationError(f"表声明重复: {table.name}")
            seen[table.name] = table
            for index_name in table.index_names():
                owner = index_owner.get(index_name)
                if owner is not None and owner != table.name:
                    raise TableDeclarationError(
                        f"索引名跨表撞名: {index_name}（{owner} 与 {table.name}）"
                    )
                index_owner[index_name] = table.name
        self._tables = tuple(tables)

    @property
    def tables(self) -> tuple[TableSpec, ...]:
        """声明集里的表。"""
        return self._tables

    def extra_tables(self) -> tuple[TableSpec, ...]:
        """按内核默认声明筛一遍，只留**多出来的**那些（声明文件与库都以默认那几张为底）。"""
        default = {table.name for table in kernel_tables()}
        return tuple(table for table in self._tables if table.name not in default)

    def table(self, name: str) -> TableSpec | None:
        """按名取表声明；不存在返回 ``None``。"""
        for table in self._tables:
            if table.name == name:
                return table
        return None

    def signature(self) -> str:
        """整份声明的规范化描述（表按名排序），开库时与库内 meta 比对。"""
        return "\n".join(sorted(table.signature() for table in self._tables))

    def ddl(self) -> tuple[str, ...]:
        """建全部表所需的语句，按表名排序使执行顺序确定。"""
        return tuple(
            statement
            for table in sorted(self._tables, key=lambda item: item.name)
            for statement in table.ddl()
        )


_TABLE_KEYS = frozenset(
    {"name", "tier", "columns", "indexes", "owner", "rebuild_from", "doc", "primary_key"}
)
_COLUMN_KEYS = frozenset(
    {"name", "type", "from", "qualifier", "unique", "not_null", "default", "doc"}
)
_INDEX_KEYS = frozenset({"columns", "unique", "doc"})

_SOURCE_NAMES: dict[str, ColumnSource] = {
    "id": ColumnSource.IDENTITY,
    "ref": ColumnSource.REFERENCE,
    "store": ColumnSource.STORED,
    "prog": ColumnSource.PROGRAM,
    "digest": ColumnSource.DIGEST,
}


def _reject_unknown(raw: Mapping[str, object], allowed: frozenset[str], what: str) -> None:
    """解析口的第一道：未知项直接报错，不静默忽略（写错了要看得见）。"""
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise TableDeclarationError(f"{what}出现未知项: {', '.join(unknown)}")


def _identifier(value: object, what: str) -> str:
    """名字必须是 ASCII 标识符：限死形状后，编译器只需防保留字。"""
    if not isinstance(value, str) or not _IDENTIFIER.match(value):
        raise TableDeclarationError(f"{what}不是合法标识符: {value!r}")
    return value


def _text(value: object, what: str) -> str:
    """取一段文本；非字符串即报错（数字与空值都不算写对了）。"""
    if not isinstance(value, str):
        raise TableDeclarationError(f"{what}必须是字符串: {value!r}")
    return value


def _tier(value: object) -> Tier:
    """解析重建档；认不出的档当场报错，不含糊过去。"""
    if not isinstance(value, str):
        raise TableDeclarationError(f"重建档必须是字符串: {value!r}")
    try:
        return Tier(value)
    except ValueError as error:
        allowed = " / ".join(member.value for member in Tier)
        raise TableDeclarationError(f"未知重建档 {value!r}（只认 {allowed}）") from error


def _column_type(value: object) -> ColumnType:
    """解析中立类型；不在词表内即报错。"""
    if not isinstance(value, str):
        raise TableDeclarationError(f"列类型必须是字符串: {value!r}")
    try:
        return ColumnType(value)
    except ValueError as error:
        allowed = " / ".join(member.value for member in ColumnType)
        raise TableDeclarationError(f"未知列类型 {value!r}（只认 {allowed}）") from error


def parse_id_ref(text: str) -> tuple[str, str]:
    """解析 `id(名字).字段`：返回（名字，字段）；纯字符匹配，不用正则。

    这是**绑定列的写法**，也是全篇最省的一行：

    - `id(block).value_uuid` —— 取 block 这个 ID 的 value_uuid（本行主语就是 block）；
    - `id(body).value_uuid` —— 载荷里指向的那个 ID（限定词 body）；
    - 名字不写（`id().value_uuid`）＝ 本行主语那个 ID。

    提到一个名字就**建立一条指向它的引用**，取它的字段就是**从那张表取值**——
    关系因此不需要第二种语法（设计篇 §8.1.3）。

    Raises:
        TableDeclarationError: 形状不是 `id(…).字段`。
    """
    head, dot, field = text.partition(".")
    if not dot or not (head.startswith("id(") and head.endswith(")")):
        raise TableDeclarationError(f"绑定列要写成 `id(名字).字段`：{text!r}")
    _identifier(field, "列名")
    name = head[len("id(") : -1].strip()
    if name:
        _identifier(name, "ID 名字")
    return name, field


def _columns(raw: object) -> tuple[Column, ...]:
    """解析列清单：绑定列写字面式 `id(名字).字段`，非绑定列写映射并标 `from:`。

    绑定列**类型与说明都不在声明里**：它们随 `ID` 的字段走，抄一份就是第二份事实。
    非绑定列（观测 / 程序 / 派生）必须写明 `type` 与 `from`，因为那种值没有出处可推。
    """
    if not isinstance(raw, (list, tuple)) or not raw:
        raise TableDeclarationError(f"表声明必须给出非空的列清单: {raw!r}")
    columns: list[Column] = []
    for entry in raw:
        if isinstance(entry, str):
            qualifier, field = parse_id_ref(entry)
            columns.append(_bound_column(qualifier, field, _source_of(qualifier)))
            continue
        if not isinstance(entry, dict):
            raise TableDeclarationError(f"列声明必须是映射或 `id(名字).字段` 字符串: {entry!r}")
        _reject_unknown(entry, _COLUMN_KEYS, "列声明")
        columns.append(_plain_column(entry))
    names = [_column_key(column) for column in columns]
    if len(set(names)) != len(names):
        raise TableDeclarationError(f"列名重复: {', '.join(sorted(names))}")
    return tuple(columns)


def column_of(  # noqa: PLR0913 — 一列的全部字段就是这些；参数散开比收成结构体更直白
    field: str,
    source: ColumnSource,
    *,
    qualifier: str = "",
    type: ColumnType | None = None,
    not_null: bool | None = None,
    doc: str = "",
) -> Column:
    """按 ID 的字段造一列（**绑定列的程序式入口**）。

    它是解析口那条路的兄弟：YAML 里的 `id(名字).字段` 走 :func:`parse_id_ref` 与
    :func:`_bound_column`，登记表算出来的列走这里。两处共用同一套判据——
    类型随 `ID` 的字段走、能否留空由字段决定，故这里可以不传 `type` 与 `not_null`。

    Args:
        field: `ID` 的字段名（`value_uuid` / `value_hash` / `birth_time` / `name`）。
        source: 值从哪儿来；只有 ``IDENTITY``（本行主语）与 ``REFERENCE``（指向别处）是绑定列。
        qualifier: 引用别处时那个名字（表名），落成列名前缀。
        type: 显式类型；不给即按 `ID` 的字段推。
        not_null: 是否非空；不给即按字段的规矩（`value_uuid` 必填，其余可空）。
        doc: 说明文本。

    Raises:
        TableDeclarationError: 字段名不可绑，或限定词与来源对不上。
    """
    if source is ColumnSource.REFERENCE and not qualifier:
        raise TableDeclarationError(f"列 {field} 声明为引用，却没有说指向哪儿（缺限定词）")
    if source is ColumnSource.IDENTITY and qualifier:
        raise TableDeclarationError(f"列 {field} 是本行主语的字段，不该带限定词 {qualifier!r}")
    effective = _COLUMN_TYPE_OF_ID.get(field) if type is None else type
    if effective is None:
        raise TableDeclarationError(f"ID 没有字段 {field!r}：类型推不出来，必须显式给")
    if not_null is None:
        not_null = field == "value_uuid" or field not in _MAY_BE_EMPTY
    return Column(
        name=field,
        type=effective,
        not_null=not_null,
        doc=doc,
        qualifier=qualifier,
        source=source,
        identity=source in {ColumnSource.IDENTITY, ColumnSource.REFERENCE},
    )


def reference_column(table: str, field: str) -> Column:
    """造一条指向别处的指针列（`id(表名).字段`）。"""
    _identifier(table, "ID 名字")
    return column_of(field, ColumnSource.REFERENCE, qualifier=table)


def _source_of(qualifier: str) -> ColumnSource:
    """由限定词定来源：不写名字＝本行主语的字段，写了名字＝指向别处。"""
    return ColumnSource.IDENTITY if not qualifier else ColumnSource.REFERENCE


def _bound_column(qualifier: str, field: str, source: ColumnSource) -> Column:
    """造一条绑定列：字段必须是 `ID` 的字段，类型与说明都随 `ID` 走。"""
    if field not in BINDABLE_FIELDS:
        raise TableDeclarationError(
            f"ID 的字段 {field!r} 绑不了：可绑的是 {sorted(BINDABLE_FIELDS)}"
            "（落盘子集，设计篇 §3.5）"
        )
    if source is ColumnSource.REFERENCE:
        _identifier(qualifier, "ID 名字")
    return column_of(field, source, qualifier=qualifier)


def _plain_column(item: Mapping[str, object]) -> Column:
    """造一条**非绑定列**：观测 / 程序 / 派生，`type` 与 `from` 都得写。"""
    qualifier, name = _qualified(item.get("name"))
    source = _column_source(item.get("from"), name)
    return Column(
        name=name,
        type=_column_type(_type_of_plain(item, name)),
        unique=_flag(item.get("unique", False), "unique"),
        not_null=_flag(item.get("not_null", False), "not_null"),
        default=_default_of(item),
        doc=_text(item.get("doc", ""), "列说明"),
        qualifier=_text(item.get("qualifier", qualifier), "限定词"),
        source=source,
    )


def _column_key(column: Column) -> str:
    """列在表里的唯一键：限定词 + 字段名（两个 ID 的同名字段不撞）。"""
    return f"{column.qualifier}.{column.name}" if column.qualifier else column.name


def _default_of(item: Mapping[str, object]) -> DefaultValue | None:
    """取非绑定列的默认值；类型对不上由编译期（`_literal`）兜住。"""
    raw = item.get("default")
    if raw is None or isinstance(raw, str | int | float | bytes | bool):
        return raw
    raise TableDeclarationError(f"默认值只能是字面量: {raw!r}")


def _key_columns(raw: object) -> tuple[str, ...]:
    """解析表级主键（列名列表）；没写就是空元组，由 :class:`TableSpec` 去推断。"""
    if raw is None or raw in ((), []):
        return ()
    if not isinstance(raw, (list, tuple)):
        raise TableDeclarationError(f"主键必须是列名列表: {raw!r}")
    return tuple(_qualified(item)[1] for item in raw)


def _qualified(raw: object) -> tuple[str, str]:
    """解析 `[位置名.]字段`：返回（限定词，列名）；限定词空串表示本行主语。"""
    text = _text(raw, "列名")
    qualifier, dot, name = text.partition(".")
    if not dot:
        qualifier, name = "", qualifier
    _identifier(name, "列名")
    if qualifier:
        _identifier(qualifier, "位置名")
    return qualifier, name


def _column_source(raw: object, name: str) -> ColumnSource:
    """解析列的来源：写了 `from:` 按它认；没写时只有落盘子集里的字段名才算绑定列。"""
    if raw is None:
        if name in BINDABLE_FIELDS:
            return ColumnSource.IDENTITY
        raise TableDeclarationError(
            f"列 {name} 既不是 ID 的字段（{sorted(BINDABLE_FIELDS)}），也没有写 from:"
        )
    if not isinstance(raw, str) or raw not in _SOURCE_NAMES:
        allowed = " / ".join(sorted(_SOURCE_NAMES))
        raise TableDeclarationError(f"未知列来源 {raw!r}（只认 {allowed}）")
    return _SOURCE_NAMES[raw]


def _type_of_plain(item: Mapping[str, object], name: str) -> object:
    """非绑定列的显式类型：不给就在这里报错（那种值没有出处可推）。"""
    declared = item.get("type")
    if declared is None:
        raise TableDeclarationError(f"列 {name} 不是绑定列，必须写明 type 与 from")
    return declared


def _indexes(raw: object, columns: tuple[Column, ...]) -> tuple[IndexSpec, ...]:
    """解析索引声明，顺带查列存在、查同一列组合重复。"""
    if not isinstance(raw, (list, tuple)):
        raise TableDeclarationError(f"索引清单必须是序列: {raw!r}")
    by_name: dict[str, str] = {}
    for column in columns:
        by_name[column.sql_name] = column.sql_name
        by_name[column.reference] = column.sql_name
    indexes: list[IndexSpec] = []
    seen: set[tuple[tuple[str, ...], bool]] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise TableDeclarationError(f"索引声明必须是映射: {item!r}")
        _reject_unknown(item, _INDEX_KEYS, "索引声明")
        raw_columns = item.get("columns")
        if not isinstance(raw_columns, (list, tuple)) or not raw_columns:
            raise TableDeclarationError(f"索引必须给出非空的列组合: {raw_columns!r}")
        wanted = [_text(name, "索引列名") for name in raw_columns]
        missing = [name for name in wanted if name not in by_name]
        if missing:
            raise TableDeclarationError(f"索引列不在表内: {', '.join(missing)}")
        index_columns = tuple(by_name[name] for name in wanted)
        unique = _flag(item.get("unique", False), "unique")
        key = (tuple(sorted(index_columns)), unique)
        if key in seen:
            raise TableDeclarationError(f"索引重复声明: {', '.join(index_columns)}")
        seen.add(key)
        indexes.append(
            IndexSpec(
                columns=index_columns,
                unique=unique,
                doc=_text(item.get("doc", ""), "索引说明"),
            )
        )
    return tuple(indexes)


def _flag(value: object, what: str) -> bool:
    """约束开关必须是布尔；写成字符串会静默当成真，故这里只收布尔。"""
    if not isinstance(value, bool):
        raise TableDeclarationError(f"{what}必须是布尔值: {value!r}")
    return value


def quote_identifier(identifier: str) -> str:
    """给标识符加双引号：解析口已把名字限死为 ASCII 词，这里只需防 SQL 保留字。

    PRAGMA 语句不能带参数占位符，故开库比对处要靠它把表名与索引名拼进语句；
    名字形状由声明层把关，这里只负责引号。
    """
    return f'"{identifier}"'


def sql_type(column_type: ColumnType) -> str:
    """中立类型到 SQLite 类型名的映射：方言只在这一处。"""
    return _SQL_TYPES[column_type]


def _literal(value: DefaultValue, column_type: ColumnType) -> str:
    """把默认值编成 SQL 字面量；与列类型不匹配即报错。"""
    match (column_type, value):
        case (ColumnType.TEXT, str()):
            return "'" + value.replace("'", "''") + "'"
        case (ColumnType.INTEGER, int()) if not isinstance(value, bool):
            return str(value)
        case (ColumnType.REAL, float() | int()) if not isinstance(value, bool):
            return repr(float(value))
        case (ColumnType.BLOB, bytes()):
            return f"X'{value.hex()}'"
        case (ColumnType.BOOLEAN, bool()):
            return "1" if value else "0"
        case _:
            raise TableDeclarationError(f"默认值 {value!r} 与列类型 {column_type.value} 不符")


def tables_path() -> Path:
    """表声明文件的实际路径：配置根 ＋ 声明文件的文件名。

    文件名是 `registry.py` 的常量（`TABLES_FILENAME`），**不再是一个配置项**：这份文件
    由代码写出来、又被代码读回去，它不是"可以调的一个参数"——换名字只会让人到处找不到它。
    配置根有自己的规矩（`CAIRN_CONFIG` 旋钮 / 仓根下的 `config/`），故路径也不在这里猜。
    这一句导入故意放在函数里：**导入存储不该要求配置文件已经在那儿**。
    """
    from core.conf import conf

    return conf.config_root() / TABLES_FILENAME


def load_tables(path: Path | None = None) -> tuple[TableSpec, ...]:
    """读表声明文件并逐张解析成 :class:`TableSpec`。

    解析口是 `TableSpec.from_mapping`：未知项、非法类型、重复表名、档与来源不匹配一律报错。
    坏 YAML 与"根不是列表"同样当场报错，不静默出一份空声明——**空声明比没有声明更坏**
    （它会把库里已有的表判成"多出来的"）。

    Raises:
        TableDeclarationError: 文件不在、读不成 YAML，或任一项不合解析口规矩。
    """
    target = tables_path() if path is None else path
    if not target.is_file():
        raise TableDeclarationError(f"表声明文件不在: {target}")
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise TableDeclarationError(f"表声明文件读不出来: {target}（{error}）") from error
    if not isinstance(raw, list) or not raw:
        raise TableDeclarationError(f"表声明文件必须是一张表一项的非空列表: {target}")
    tables: list[TableSpec] = []
    for item in raw:
        if not isinstance(item, dict):
            raise TableDeclarationError(f"每一项表声明必须是映射: {item!r}")
        tables.append(TableSpec.from_mapping(cast("Mapping[str, object]", item)))
    return tuple(tables)


def kernel_tables() -> tuple[TableSpec, ...]:
    """内核的**全部**表声明：类型派生的（`block` / `body`）＋ 不由类型诞生的（`hub` / `edge`）。

    **不再读文件**：文件是这条路的投影，不是它的入口。谁用了 ID，谁就在登记表里
    （`Body` → `body`、`Block` → `block`），故这里问登记表即可——于是"表会自己诞生"
    这句话在代码上成立：加了类型，下一轮开库就多一张表（文件与库都由 `tablegen.sync`
    与开库对齐补齐）。

    领域层重建后，它的类型会登记进同一份登记表，这张清单自然变长，本函数不必改。

    Raises:
        TableDeclarationError: 有引用指向没登记的表（断链），或列的形状推不出来。
    """
    from .tablegen import kernel_declarations

    return kernel_declarations()


META_TABLE_SPEC = TableSpec(
    name="meta",
    tier=Tier.DERIVED,
    rebuild_from="当前表声明（由程序给出）",
    doc="索引库自用：存声明的规范化描述，开库时与当前声明比对",
    columns=(
        Column("name", ColumnType.TEXT, not_null=True, doc="登记项名", source=ColumnSource.PROGRAM),
        Column(
            "value", ColumnType.TEXT, not_null=True, doc="登记项的值", source=ColumnSource.PROGRAM
        ),
    ),
    primary_key=("name",),
)
"""索引库自用表 `meta`：**不属声明集**，故留在代码里（它是开库流程的脚手架，不是业务声明）。

它由开库流程自己保证存在（见 `index.py`），故业务声明不必（也不许）写它——
"源码内不得出现建表 SQL"这条规矩，`meta` 也不例外。
"""


__all__ = [
    "BINDABLE_FIELDS",
    "META_TABLE_SPEC",
    "POINTER_FIELDS",
    "Column",
    "ColumnSource",
    "ColumnType",
    "Declaration",
    "IndexSpec",
    "TableSpec",
    "Tier",
    "column_of",
    "kernel_tables",
    "load_tables",
    "quote_identifier",
    "reference_column",
    "sql_type",
    "tables_path",
]

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
from typing import TYPE_CHECKING

from core.exc import TableDeclarationError

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
POINTER_FIELDS: frozenset[str] = frozenset({"value_uuid", "value_hash"})

#: 能绑成列的 ID 字段 = 落盘子集（设计篇 §3.5）与身份字段的交集
BINDABLE_FIELDS: frozenset[str] = frozenset({"value_uuid", "value_hash", "birth_time", "name"})

#: 能依赖默认为空的绑定字段：其余绑定列必须非空，免得同一身份多出一行空值
_BINDABLE_NULLABLE: frozenset[str] = frozenset({"value_hash", "birth_time", "name"})

#: 绑定列的类型由 `ID` 的字段推出（设计篇 §3.2），声明里不写
_COLUMN_TYPE_OF_ID: dict[str, ColumnType] = {
    "name": ColumnType.TEXT,
    "value_uuid": ColumnType.TEXT,
    "value_hash": ColumnType.TEXT,
    "birth_time": ColumnType.INTEGER,
}

#: 身份表的固定列名：判别列 `name` 与主键另一半 `value_uuid`
IDENTITY_TABLE = "record"
IDENTITY_SCOPE_COLUMN = "name"
IDENTITY_KEY_COLUMN = "value_uuid"

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

    def bound_field(self) -> str:
        """绑定列取的 ID 字段名；不是绑定列即报错。"""
        if not self.bound:
            raise TableDeclarationError(f"列 {self.reference} 不是绑定列，取不到 ID 字段")
        return self.name

    def ddl(self) -> str:
        """编译成建表语句里的一段，形如 ``"列名" TYPE NOT NULL DEFAULT …``。

        主键由 :meth:`TableSpec.create_table_ddl` 以表级约束写出（复合主键没法写在列上）。
        """
        parts = [quote_identifier(self.name), sql_type(self.type)]
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

    def _default_key(self) -> tuple[str, ...]:
        """没写主键时的推断：唯一的身份列即主键；再不行就单列表的那一列。

        两张身份列的表（关系表那种）必须明写复合主键——那时候"取哪一列"没有确定答案。
        """
        own = [column.name for column in self.columns if column.identity and not column.qualifier]
        if len(own) == 1:
            return (own[0],)
        if len(own) > 1:
            raise TableDeclarationError(
                f"表 {self.name} 有多个身份列（{own}）：主键必须显式写明哪几列"
            )
        if len(self.columns) == 1:
            return (self.columns[0].name,)
        return ()

    @property
    def identity_columns(self) -> tuple[Column, ...]:
        """本行的身份列：绑定到本行主语那个 ID 的字段（不带限定词）。"""
        return tuple(column for column in self.columns if column.identity and not column.qualifier)

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
            if column.queryable and column.name not in covered:
                resolved.append(IndexSpec(columns=(column.name,)))
                covered.add(column.name)
        return tuple(resolved)

    def column_names(self) -> tuple[str, ...]:
        """全部列名，书写顺序。"""
        return tuple(column.name for column in self.columns)

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
        """核对每一列的来源，再核身份表那几条特有规矩。"""
        for column in self.columns:
            self._check_column(column)
        if self.name != IDENTITY_TABLE:
            return
        if self.primary_key != (IDENTITY_SCOPE_COLUMN, IDENTITY_KEY_COLUMN):
            raise TableDeclarationError(
                f"身份表 {IDENTITY_TABLE} 的主键必须是 "
                f"({IDENTITY_SCOPE_COLUMN}, {IDENTITY_KEY_COLUMN})，现在是 {self.primary_key}"
            )
        scope = self.column(IDENTITY_SCOPE_COLUMN)
        if scope is None or not (scope.identity and scope.qualifier):
            raise TableDeclarationError(
                f"身份表 {IDENTITY_TABLE} 的 {IDENTITY_SCOPE_COLUMN} 列必须是**带限定词**的绑定列："
                "作用域名由引用方写下（见设计篇 §8）"
            )

    def _check_column(self, column: Column) -> None:
        """核对一列的来源：绑定列的字段必须在落盘子集里，限定词只用两套凭证。

        例外只有一个：身份表的 `name` 判别列——它是"作用域名由引用方写下"的落点，
        不是指向某处的指针，故不受"限定词只用两套凭证"那条约束（见设计篇 §8）。
        """
        if not column.identity:
            return
        if column.name not in BINDABLE_FIELDS:
            raise TableDeclarationError(
                f"列 {self.name}.{column.reference} 绑不到 ID 的字段 {column.name}："
                f"可绑的是 {sorted(BINDABLE_FIELDS)}（落盘子集，见设计篇 §3.5）"
            )
        if not column.not_null and column.name not in _BINDABLE_NULLABLE:
            raise TableDeclarationError(
                f"绑定列 {self.name}.{column.reference} 必须非空：否则同一个身份会多出一行空值"
            )
        if self.name == IDENTITY_TABLE and column.name == IDENTITY_SCOPE_COLUMN:
            return
        if column.qualifier and column.name not in POINTER_FIELDS:
            raise TableDeclarationError(
                f"列 {self.name}.{column.reference} 取不到：载荷里的指针只带两套凭证 "
                f"{sorted(POINTER_FIELDS)}"
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
_COLUMN_KEYS = frozenset({"name", "type", "from", "qualifier", "unique", "not_null", "default", "doc"})
_INDEX_KEYS = frozenset({"columns", "unique", "doc"})

_SOURCE_NAMES: dict[str, ColumnSource] = {
    "id": ColumnSource.IDENTITY,
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


def _columns(raw: object) -> tuple[Column, ...]:
    """解析列清单：绑定列（裸字段名或 `位置名.字段`）与派生列（写 `from:` 标来路）。

    绑定列**不写类型**——类型从 `ID` 的字段推出；派生列必须写明 `type` 与 `from`，
    因为那种值没有出处可推。
    """
    if not isinstance(raw, (list, tuple)) or not raw:
        raise TableDeclarationError(f"表声明必须给出非空的列清单: {raw!r}")
    columns: list[Column] = []
    for entry in raw:
        item: object = entry
        if isinstance(item, str):
            if item not in BINDABLE_FIELDS:
                raise TableDeclarationError(f"列声明必须是映射或 ID 字段名: {item!r}")
            item = {"name": item, "from": "id", "type": _COLUMN_TYPE_OF_ID[item].value}
        if not isinstance(item, dict):
            raise TableDeclarationError(f"列声明必须是映射或字符串: {item!r}")
        _reject_unknown(item, _COLUMN_KEYS, "列声明")
        qualifier, name = _qualified(item.get("name"))
        if any(column.name == name for column in columns):
            raise TableDeclarationError(f"列名重复: {name}")
        source = _column_source(item.get("from"), name)
        identity = source is ColumnSource.IDENTITY
        # 绑定列的类型**一律由 ID 的字段推出**：声明里写什么都不作数（写了也推得回来）。
        column_type = _COLUMN_TYPE_OF_ID[name] if identity else _column_type(item.get("type"))
        columns.append(
            Column(
                name=name,
                type=column_type,
                unique=_flag(item.get("unique", False), "unique"),
                not_null=_flag(item.get("not_null", identity), "not_null"),
                default=item.get("default"),
                doc=_text(item.get("doc", ""), "列说明"),
                qualifier=qualifier,
                source=source,
                identity=identity,
            )
        )
    names = [column.name for column in columns]
    if len(set(names)) != len(names):
        raise TableDeclarationError(f"列名重复: {', '.join(sorted(names))}")
    return tuple(columns)


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


def _indexes(raw: object, columns: tuple[Column, ...]) -> tuple[IndexSpec, ...]:
    """解析索引声明，顺带查列存在、查同一列组合重复。"""
    if not isinstance(raw, (list, tuple)):
        raise TableDeclarationError(f"索引清单必须是序列: {raw!r}")
    names = {column.name for column in columns}
    indexes: list[IndexSpec] = []
    seen: set[tuple[tuple[str, ...], bool]] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise TableDeclarationError(f"索引声明必须是映射: {item!r}")
        _reject_unknown(item, _INDEX_KEYS, "索引声明")
        raw_columns = item.get("columns")
        if not isinstance(raw_columns, (list, tuple)) or not raw_columns:
            raise TableDeclarationError(f"索引必须给出非空的列组合: {raw_columns!r}")
        index_columns = tuple(_identifier(name, "索引列名") for name in raw_columns)
        missing = [name for name in index_columns if name not in names]
        if missing:
            raise TableDeclarationError(f"索引列不在表内: {', '.join(missing)}")
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


KERNEL_TABLES: tuple[TableSpec, ...] = (
    TableSpec(
        name="record",
        tier=Tier.DERIVED,
        rebuild_from="载体记录头（设计篇 §8.5 档一）",
        doc="身份表：一行一个 ID（块记录与内容记录同表）；name 是作用域名，由引用方写下",
        columns=(
            Column(
                IDENTITY_SCOPE_COLUMN,
                ColumnType.TEXT,
                not_null=True,
                doc="作用域名（引用方写下的名字，如 block / body）",
                qualifier="scope",
                source=ColumnSource.IDENTITY,
                identity=True,
            ),
            Column(
                IDENTITY_KEY_COLUMN,
                ColumnType.TEXT,
                not_null=True,
                doc="分配形态凭证（同一个值在不同作用域下各占一行）",
                source=ColumnSource.IDENTITY,
                identity=True,
            ),
            Column(
                "value_hash",
                ColumnType.TEXT,
                doc="摘要形态凭证（指向内容）",
                source=ColumnSource.IDENTITY,
                identity=True,
            ),
            Column(
                "kind",
                ColumnType.TEXT,
                doc="类型标号；由程序给出，不在记录头里",
                source=ColumnSource.PROGRAM,
            ),
            Column(
                "hub",
                ColumnType.TEXT,
                not_null=True,
                doc="所属 hub（目录名）",
                source=ColumnSource.STORED,
            ),
            Column(
                "pack",
                ColumnType.TEXT,
                not_null=True,
                doc="载体文件名",
                source=ColumnSource.STORED,
            ),
            Column(
                "slot_first",
                ColumnType.INTEGER,
                not_null=True,
                doc="起始格（两数格模型的第一个数字）",
                source=ColumnSource.STORED,
            ),
            Column(
                "slot_last",
                ColumnType.INTEGER,
                not_null=True,
                doc="末格（闭区间上界）",
                source=ColumnSource.STORED,
            ),
            Column(
                "size",
                ColumnType.INTEGER,
                not_null=True,
                doc="记录字节数，便于估算与巡检",
                source=ColumnSource.STORED,
            ),
            Column(
                "birth_time",
                ColumnType.INTEGER,
                doc="ID 签发时刻（unix 纳秒）",
                source=ColumnSource.IDENTITY,
                identity=True,
            ),
            Column(
                "created",
                ColumnType.INTEGER,
                doc="落盘时刻（unix 毫秒）",
                source=ColumnSource.STORED,
            ),
            Column(
                "updated",
                ColumnType.INTEGER,
                doc="最近一次改写时刻（unix 毫秒）",
                source=ColumnSource.STORED,
            ),
        ),
        indexes=(
            IndexSpec(columns=("value_hash",)),
            IndexSpec(columns=("kind",)),
            IndexSpec(columns=("hub", "pack")),
            IndexSpec(columns=("updated",)),
        ),
        primary_key=(IDENTITY_SCOPE_COLUMN, IDENTITY_KEY_COLUMN),
    ),
    TableSpec(
        name="hub",
        tier=Tier.DERIVED,
        rebuild_from="vault 下的 hub 目录（设计篇 §6）",
        doc="登记表：位置由目录名推出，真源是目录本身；主语不是 ID，故没有绑定列",
        columns=(
            Column(
                "name",
                ColumnType.TEXT,
                not_null=True,
                doc="hub 名（目录名）",
                source=ColumnSource.STORED,
            ),
            Column(
                "role",
                ColumnType.TEXT,
                doc="主 hub / 短命 hub；短命 hub 为未来项",
                source=ColumnSource.STORED,
            ),
            Column(
                "state",
                ColumnType.TEXT,
                doc="登记状态；合并期为未来项",
                source=ColumnSource.STORED,
            ),
            Column(
                "created",
                ColumnType.INTEGER,
                doc="第一次见到它的时刻（unix 毫秒）",
                source=ColumnSource.STORED,
            ),
        ),
        primary_key=("name",),
    ),
    TableSpec(
        name="edge",
        tier=Tier.DERIVED,
        rebuild_from="关系数据落在块内时的块记录（设计篇 §8.2 注；归属待定）",
        doc="关系表：一行一条；src 与 dst 两列指向 ID，关系不需要第二种语法",
        columns=(
            Column(
                "id",
                ColumnType.TEXT,
                not_null=True,
                doc="边身份摘要（由下列各列算出）",
                source=ColumnSource.DIGEST,
            ),
            Column(
                "src",
                ColumnType.TEXT,
                not_null=True,
                doc="起点 ID",
                source=ColumnSource.REFERENCE,
            ),
            Column(
                "dst",
                ColumnType.TEXT,
                not_null=True,
                doc="终点 ID",
                source=ColumnSource.REFERENCE,
            ),
            Column(
                "kind", ColumnType.TEXT, not_null=True, doc="关系种类", source=ColumnSource.PROGRAM
            ),
            Column("domain", ColumnType.TEXT, doc="所属领域", source=ColumnSource.PROGRAM),
            Column(
                "created",
                ColumnType.INTEGER,
                doc="建立时刻（unix 毫秒）",
                source=ColumnSource.STORED,
            ),
        ),
        indexes=(IndexSpec(columns=("src", "kind")), IndexSpec(columns=("dst", "kind"))),
        primary_key=("id",),
    ),
)
"""内核三表：`record` / `hub` / `edge`（设计篇 §8.2、§8.6）。

- `record` 是**身份表**：只放 ID 的面（作用域名 / 两套凭证 / 签发时刻）与存储层观测到的坐标；
  主键是 `(name, value_uuid)`——作用域名由引用方写下（设计篇 §8）。
- `hub` 是**登记表**：主语是载体目录、不是 ID，故一列绑定都写不出来（它进不了身份表）。
- `edge` 是**关系表**：两端各一列绑定，另有身份摘要与标签。

绑定列（`identity=True`）的索引由 `TableSpec.resolved_indexes()` 兜底补上，
故这里只写"额外的"那些。
"""


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
"""索引库自用表 `meta`：不属于任何声明集，但**建表语句同样由声明编译**。

它由开库流程自己保证存在（见 `index.py`），故业务声明不必（也不许）写它——
"源码内不得出现建表 SQL"这条规矩，`meta` 也不例外。
"""


__all__ = [
    "BINDABLE_FIELDS",
    "IDENTITY_KEY_COLUMN",
    "IDENTITY_SCOPE_COLUMN",
    "IDENTITY_TABLE",
    "KERNEL_TABLES",
    "META_TABLE_SPEC",
    "POINTER_FIELDS",
    "Column",
    "ColumnSource",
    "ColumnType",
    "Declaration",
    "IndexSpec",
    "TableSpec",
    "Tier",
    "quote_identifier",
    "sql_type",
]

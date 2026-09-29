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
    """一列：名字、中立类型与四个约束开关。

    Attributes:
        name: 列名（ASCII 标识符；解析口限死，故编译器只需防保留字）。
        type: 中立类型。
        primary_key: 是否主键。
        unique: 是否唯一。列级唯一由 SQLite 的列约束表达，索引唯一性由索引声明表达。
        not_null: 是否非空。
        default: 默认值；``None`` 表示不设默认值（SQLite 里与默认 NULL 等价）。
        doc: 说明文本；**不进签名**。
    """

    name: str
    type: ColumnType
    primary_key: bool = False
    unique: bool = False
    not_null: bool = False
    default: DefaultValue | None = None
    doc: str = ""

    def ddl(self) -> str:
        """编译成建表语句里的一段，形如 ``"列名" TYPE PRIMARY KEY NOT NULL``。"""
        parts = [quote_identifier(self.name), sql_type(self.type)]
        if self.primary_key:
            parts.append("PRIMARY KEY")
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
        """列在开库比对里的规范化描述（不含 ``doc``）。"""
        default = "-" if self.default is None else _literal(self.default, self.type)
        flags = "".join(
            flag
            for flag, on in (
                ("p", self.primary_key),
                ("u", self.unique),
                ("n", self.not_null),
            )
            if on
        )
        return f"{self.name}:{self.type.value}:{flags or '-'}:{default}"


@dataclass(frozen=True, slots=True)
class IndexSpec:
    """一个索引声明：列组合加唯一性开关。

    Attributes:
        columns: 参与索引的列，顺序即索引顺序（不影响索引名，名字按排序后的列推出）。
        unique: 是否唯一索引。
    """

    columns: tuple[str, ...]
    unique: bool = False


@dataclass(frozen=True, slots=True)
class TableSpec:
    """一张表的声明：表名、重建档、列、索引、归属与说明。

    Attributes:
        name: 表名。
        tier: 重建档。
        columns: 列，顺序即书写顺序（签名的排序是另一回事）。
        indexes: 索引声明。
        owner: 归属（`core` / 领域名）；领域表的归属由声明给出。
        rebuild_from: 重建来源；重建档为 ``SOURCE`` 时必须为空。
        doc: 说明文本；**不进签名**。
    """

    name: str
    tier: Tier
    columns: tuple[Column, ...]
    indexes: tuple[IndexSpec, ...] = ()
    owner: str = "core"
    rebuild_from: str = ""
    doc: str = ""

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
        )

    def column_names(self) -> tuple[str, ...]:
        """全部列名，书写顺序。"""
        return tuple(column.name for column in self.columns)

    def column(self, name: str) -> Column | None:
        """按名取列；不存在返回 ``None``。"""
        for column in self.columns:
            if column.name == name:
                return column
        return None

    def primary_key(self) -> Column:
        """主键列（声明校验保证恰好一列）。"""
        for column in self.columns:
            if column.primary_key:
                return column
        raise TableDeclarationError(f"表 {self.name} 没有主键列")  # pragma: no cover — 构造时已拦

    def index_name(self, index: IndexSpec) -> str:
        """索引名：``idx_<表>_<列...>``，列按名字排序，故声明里的书写顺序不影响它。"""
        return "_".join(("idx", self.name, *sorted(index.columns)))

    def index_names(self) -> tuple[str, ...]:
        """全部索引名，按名排序。"""
        return tuple(sorted(self.index_name(index) for index in self.indexes))

    def create_table_ddl(self) -> str:
        """编译出建表语句。"""
        body = ", ".join(column.ddl() for column in self.columns)
        return f"CREATE TABLE IF NOT EXISTS {quote_identifier(self.name)} ({body})"

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
        ordered = sorted(self.indexes, key=self.index_name)
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
            for index in sorted(self.indexes, key=self.index_name)
        )
        return (
            f"table={self.name}|tier={self.tier.value}|owner={self.owner}"
            f"|rebuild_from={self.rebuild_from}|columns=[{columns}]|indexes=[{indexes}]"
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


_TABLE_KEYS = frozenset({"name", "tier", "columns", "indexes", "owner", "rebuild_from", "doc"})
_COLUMN_KEYS = frozenset({"name", "type", "primary_key", "unique", "not_null", "default", "doc"})
_INDEX_KEYS = frozenset({"columns", "unique"})


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
    """解析列清单，顺带查重与主键唯一性。"""
    if not isinstance(raw, (list, tuple)) or not raw:
        raise TableDeclarationError(f"表声明必须给出非空的列清单: {raw!r}")
    columns: list[Column] = []
    for item in raw:
        if not isinstance(item, dict):
            raise TableDeclarationError(f"列声明必须是映射: {item!r}")
        _reject_unknown(item, _COLUMN_KEYS, "列声明")
        columns.append(
            Column(
                name=_identifier(item.get("name"), "列名"),
                type=_column_type(item.get("type")),
                primary_key=_flag(item.get("primary_key", False), "primary_key"),
                unique=_flag(item.get("unique", False), "unique"),
                not_null=_flag(item.get("not_null", False), "not_null"),
                default=item.get("default"),
                doc=_text(item.get("doc", ""), "列说明"),
            )
        )
    names = [column.name for column in columns]
    if len(set(names)) != len(names):
        raise TableDeclarationError(f"列名重复: {', '.join(sorted(names))}")
    keys = [column.name for column in columns if column.primary_key]
    if len(keys) != 1:
        raise TableDeclarationError(f"恰需一列主键，实际 {len(keys)} 列: {', '.join(keys) or '无'}")
    return tuple(columns)


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
        indexes.append(IndexSpec(columns=index_columns, unique=unique))
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
        doc="身份到位置：一行一条记录（块记录与内容记录同表）",
        columns=(
            Column(
                "value_uuid",
                ColumnType.TEXT,
                primary_key=True,
                not_null=True,
                doc="分配形态凭证",
            ),
            Column("value_hash", ColumnType.TEXT, not_null=True, doc="摘要形态凭证"),
            Column("kind", ColumnType.TEXT, doc="类型标号；由程序给出，不在记录头里"),
            Column("hub", ColumnType.TEXT, not_null=True, doc="所属 hub（目录名）"),
            Column("pack", ColumnType.TEXT, not_null=True, doc="载体文件名"),
            Column(
                "slot_first",
                ColumnType.INTEGER,
                not_null=True,
                doc="起始格（两数格模型的第一个数字）",
            ),
            Column("slot_last", ColumnType.INTEGER, not_null=True, doc="末格（闭区间上界）"),
            Column("size", ColumnType.INTEGER, not_null=True, doc="记录字节数，便于估算与巡检"),
            Column("issued", ColumnType.INTEGER, doc="ID 签发时刻（unix 毫秒）"),
            Column("created", ColumnType.INTEGER, doc="落盘时刻（unix 毫秒）"),
            Column("updated", ColumnType.INTEGER, doc="最近一次改写时刻（unix 毫秒）"),
        ),
        indexes=(
            IndexSpec(columns=("value_hash",)),
            IndexSpec(columns=("kind",)),
            IndexSpec(columns=("hub", "pack")),
            IndexSpec(columns=("updated",)),
        ),
    ),
    TableSpec(
        name="hub",
        tier=Tier.DERIVED,
        rebuild_from="vault 下的 hub 目录（设计篇 §6）",
        doc="hub 登记：位置由目录名推出，真源是目录本身",
        columns=(
            Column(
                "name",
                ColumnType.TEXT,
                primary_key=True,
                not_null=True,
                doc="hub 名（目录名）",
            ),
            Column("role", ColumnType.TEXT, doc="主 hub / 短命 hub；短命 hub 为未来项"),
            Column("state", ColumnType.TEXT, doc="登记状态；合并期为未来项"),
            Column("created", ColumnType.INTEGER, doc="第一次见到它的时刻（unix 毫秒）"),
        ),
    ),
    TableSpec(
        name="edge",
        tier=Tier.DERIVED,
        rebuild_from="关系数据落在块内时的块记录（设计篇 §8.2 注；归属待定）",
        doc="关系边：一行一条，身份由 (src, dst, kind, domain) 算摘要",
        columns=(
            Column("id", ColumnType.TEXT, primary_key=True, not_null=True, doc="边身份摘要"),
            Column("src", ColumnType.TEXT, not_null=True, doc="起点 ID"),
            Column("dst", ColumnType.TEXT, not_null=True, doc="终点 ID"),
            Column("kind", ColumnType.TEXT, not_null=True, doc="关系种类"),
            Column("domain", ColumnType.TEXT, doc="所属领域"),
            Column("created", ColumnType.INTEGER, doc="建立时刻（unix 毫秒）"),
        ),
        indexes=(
            IndexSpec(columns=("src", "kind")),
            IndexSpec(columns=("dst", "kind")),
        ),
    ),
)
"""内核三表：`record` / `hub` / `edge`（设计篇 §8.2）。

`record` 的位置列按**两数格模型**给（`slot_first` / `slot_last`）；§8.2 写的
`slot_head` / `slot_count` 属旧的三数模型，待回写。
"""


META_TABLE_SPEC = TableSpec(
    name="meta",
    tier=Tier.DERIVED,
    rebuild_from="当前表声明（由程序给出）",
    doc="索引库自用：存声明的规范化描述，开库时与当前声明比对",
    columns=(
        Column("name", ColumnType.TEXT, primary_key=True, not_null=True, doc="登记项名"),
        Column("value", ColumnType.TEXT, not_null=True, doc="登记项的值"),
    ),
)
"""索引库自用表 `meta`：不属于任何声明集，但**建表语句同样由声明编译**。

它由开库流程自己保证存在（见 `index.py`），故业务声明不必（也不许）写它——
"源码内不得出现建表 SQL"这条规矩，`meta` 也不例外。
"""


__all__ = [
    "KERNEL_TABLES",
    "META_TABLE_SPEC",
    "Column",
    "ColumnType",
    "Declaration",
    "IndexSpec",
    "TableSpec",
    "Tier",
    "quote_identifier",
    "sql_type",
]

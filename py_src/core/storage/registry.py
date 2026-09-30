# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""类型登记：谁用了 ID，谁就在这张表里留下一个可反查的名字。

**这是"表会自己诞生"的起点**（设计篇 §8.1.2、§8.2.1）。判据只有一句：
一个类型若持有 ID（自己的身份，或指向别处的指针），它就必然对应一张索引表——
表名就是那个名字，列就是那些 ID 的字段。故表的形状不必手写，**问登记表即可**。

三条口径：

- **登记发生在类型定义时**，不是运行时扫描全书。定义量小、确定、可复查；
  扫描要靠导入全仓模块，那既慢又会把"没被导入的类型"悄悄漏掉。
- **一张表一个类型**：谁登记在先谁定这张表的形状；后登记的同名者当场报错，
  不静默合并——两处写同一张表的列，等于两处事实。
- **登记是投影的输入，不是投影本身**：它交出列与主键，落地文件与建表语句由
  `tablegen` 与 `tables` 从它算出来（代码 → 文件 → 库，一条路，不跳过文件）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from core.exc import TableDeclarationError

from .format.id import ID_FIELDS

if TYPE_CHECKING:
    from collections.abc import Mapping

    from core.conf.types import TypeSpec

#: ID 上能绑成列的字段 = `ID` 的**全部**字段（`ID_FIELDS`）。
#: 表里的身份列照它逐列搬，故"哪个字段进不去库"这个问题在代码上没有第二种答案。
BINDABLE_FIELDS: frozenset[str] = frozenset(ID_FIELDS)

#: 指针能带的两套凭证：指向别处时只可能有这两列（设计篇 §3.2.1）。
POINTER_FIELDS: frozenset[str] = frozenset({"value_uuid", "value_hash"})

#: 两张内核表的名字：`body` 装内容、`block` 装"指向 body 的那份指针"。
BODY_TABLE = "body"
BLOCK_TABLE = "block"

#: 声明文件的文件名（相对配置根）：由代码写出来、又被代码读回去的那份投影。
TABLES_FILENAME = "tables.yaml"


class Tier(Enum):
    """重建档：判据是"写不写得出重建来源"（§8.5）。

    它既是**表**的档位也是**类型**的档位：类型的档位由声明给出，再流进它那张表的声明。
    """

    DERIVED = "derived"
    """档一：由真源（载体、目录）派生，可重建。**必须**写明重建来源。"""

    SOURCE = "source"
    """档三：真源就在库里，重建不成立，只能靠备份。**禁止**写重建来源。"""


class Nature(Enum):
    """类型性质：它是业务数据，还是内核自己的机制。"""

    DATA = "data"
    """业务数据：列举里看得见，备份覆盖它。"""

    TOL = "tol"
    """工具型（作者命名）：内核自己的机制（索引、登记一类），不是业务。

    它在库里是必要的，在界面上不是给人看的东西，故**不出现在列举里**。
    """


class OverBudget(Enum):
    """配额用满之后怎么办。"""

    DENY = "deny"
    """拒绝写入，抛 `BudgetExhaustedError`：宁可写不进去，也不让查询面变宽。"""

    NOTIFY = "notify"
    """续一份，并发一条 `budget.exhausted` 通知。"""

    EXTEND = "extend"
    """续一份，不吭声。**默认**——它等同于"没有配额"，也就是既有那条写入纪律。"""


@dataclass(frozen=True, slots=True)
class TypeDecl:
    """一个有 ID 的类型：它的名字即表名，它持有的 ID 字段即列。

    Attributes:
        name: 类型的登记名（`Body` / `Block` / 领域类名），由类定义处给出。
        table: 表名；默认取 `name` 的小写写法。
        doc: 说明文本；随表声明落进文件，**不进开库比对的签名**。
        ids: 本行主语的 ID 字段名，与 `ID` 的字段同名（`ID_FIELDS` 的全部）。
        refs: 指向别处的引用，字段名 → 目标表。
        attrs: 本类型声明的属性，字段名 → 类型判据，顺序即类里书写的顺序。
            属性**不是列**：它跟着块记录走，这里登记只为了让「哪些字段该落盘、
            各是什么类型」有确定答案。判据与配置共用（`core.conf.types`）。

    以下是**类型级声明**：它们描述"这个类型的块怎么被存储、被怎么对待"，
    与表的列形状无关，故**不进声明文件**（`tables.yaml` 只描述库的形状）。

    Attributes:
        nature: 类型性质（业务 / 工具型）；工具型不出现在列举里。
        owner: 归属（领域名 / `core`）；写进它那张表的声明。
        tier: 重建档；流进它那张表的声明。
        backup: 是否纳入备份。**当前只登记**，备份动作尚未实现。
        own_hub: 独占一个 hub，名字取 `table`；与 `hub` 互斥。
        hub: 指定写进哪个 hub（不存在则由写路径建立）；与 `own_hub` 互斥。
        slot_budget: 单个载体内的格配额。**当前只登记**——载体还没有"区段保留"
            这个概念，执行它要新机制（见 `progress.md`）。
        pack_budget: 载体份数配额；用满之后的处置见 `over_budget`。
        max_block_bytes: 单块体积上限（字节，已把分档位相加归一）；超限即拒写。
        over_budget: 配额用满之后的行为。
    """

    name: str
    table: str
    doc: str = ""
    ids: tuple[str, ...] = ID_FIELDS
    refs: Mapping[str, str] = field(default_factory=dict)
    attrs: tuple[tuple[str, TypeSpec], ...] = ()
    nature: Nature = Nature.DATA
    owner: str = "core"
    tier: Tier = Tier.DERIVED
    backup: bool = False
    own_hub: bool = False
    hub: str = ""
    slot_budget: int | None = None
    pack_budget: int | None = None
    max_block_bytes: int | None = None
    over_budget: OverBudget = OverBudget.EXTEND

    def __post_init__(self) -> None:
        """校验登记的字段名：能绑的只有落盘子集，指针只带两套凭证。

        属性不在这里校验：它只有 `register_type` 一个来源（受控的注解扫描），
        而同一个名字在注解里只会出现一次，不存在"两处写同一张表"的可能。
        """
        unknown = [name for name in self.ids if name not in BINDABLE_FIELDS]
        if unknown:
            raise TableDeclarationError(
                f"类型 {self.name} 登记了绑不成的 ID 字段 {unknown}："
                f"可绑的是 {sorted(BINDABLE_FIELDS)}（落盘子集，设计篇 §3.5）"
            )
        if "value_uuid" not in self.ids:
            raise TableDeclarationError(
                f"类型 {self.name} 必须登记 value_uuid：它是主键，缺了这张表就没有身份"
            )
        dangling = [f"{field} → {table}" for field, table in self.refs.items() if not table]
        if dangling:
            raise TableDeclarationError(f"类型 {self.name} 的引用没有说指向哪张表: {dangling}")
        object.__setattr__(self, "ids", tuple(dict.fromkeys(self.ids)))
        object.__setattr__(self, "refs", dict(self.refs or {}))
        if self.own_hub and self.hub:
            raise TableDeclarationError(
                f"类型 {self.name} 同时声明了 own_hub 与 hub：只能给一个——"
                "独占时 hub 名取表名，指定时是写进别人的地盘，两者互斥"
            )
        for label, value in (
            ("slot_budget", self.slot_budget),
            ("pack_budget", self.pack_budget),
            ("max_block_bytes", self.max_block_bytes),
        ):
            if value is not None and value < 1:
                raise TableDeclarationError(f"类型 {self.name} 的 {label} 必须为正: {value}")

    def referenced_tables(self) -> tuple[str, ...]:
        """本类型引用到的表名（去重、按出现顺序）。"""
        return tuple(dict.fromkeys(self.refs.values()))

    def hub_name(self, default: str) -> str:
        """这个类型的块写进哪个 hub：独占取表名、指定取 :attr:`hub`、都没有则用默认。"""
        if self.own_hub:
            return self.table
        return self.hub or default


class Registry:
    """类型登记表：定义时登记，随时可反查。

    它是**进程内的**：Python 的解释器跑起来、模块被导入，登记就发生了；没有落盘，
    也不需要落盘——因为它是代码侧的事实，落盘的是由它算出来的那份投影。
    """

    def __init__(self) -> None:
        """建一张空表。"""
        self._types: dict[str, TypeDecl] = {}
        self._tables: dict[str, str] = {}

    def register(self, decl: TypeDecl) -> TypeDecl:
        """登记一个类型；同名或同表重复登记即报错（不静默合并两处事实）。

        **同一个类可能被登记两次**：`@dataclass(slots=True)` 会重建一次类对象来加
        `__slots__`，于是 `__init_subclass__` 跑第二遍。这种情况按形状判：形状一样就是
        同一件事实的重放，放过；形状不同就是两处写同一张表，照样报错。

        Returns:
            登记进去的那份声明，便于调用点直接持有。

        Raises:
            TableDeclarationError: 名字或表名被别的类型占了，或同名重复但形状不同。
        """
        existing = self._types.get(decl.name)
        if existing is not None:
            if existing == decl:
                return existing
            raise TableDeclarationError(
                f"类型 {decl.name} 已经登记过，且这次的形状与上次不同："
                f"{existing.table} → {decl.table}"
            )
        owner = self._tables.get(decl.table)
        if owner is not None:
            raise TableDeclarationError(
                f"表 {decl.table} 已经由类型 {owner} 占着，{decl.name} 不能再用"
            )
        self._types[decl.name] = decl
        self._tables[decl.table] = decl.name
        return decl

    def get(self, name: str) -> TypeDecl | None:
        """按类型名反查；没有即 ``None``。"""
        return self._types.get(name)

    def table(self, name: str) -> TypeDecl | None:
        """按表名反查；没有即 ``None``。"""
        owner = self._tables.get(name)
        return None if owner is None else self._types[owner]

    def declarations(self) -> tuple[TypeDecl, ...]:
        """全部登记，按表名排序（书写顺序确定，投影才可复现）。"""
        ordered = sorted(self._tables.values(), key=self._table_of)
        return tuple(self._types[name] for name in ordered)

    def referenced_tables(self) -> tuple[str, ...]:
        """全部被引用到的表名，按名排序（投影前查断链用）。"""
        referenced = {table for decl in self._types.values() for table in decl.refs.values()}
        return tuple(sorted(referenced))

    def clear(self) -> None:
        """清空（工具与测试用；内核本身不清）。"""
        self._types.clear()
        self._tables.clear()

    def _table_of(self, type_name: str) -> str:
        """取一个类型对应的表名（排序用）。"""
        return self._types[type_name].table


#: 进程内的类型登记表：`Body` / `Block` 与各领域类型都登在这里。
REGISTRY = Registry()
"""全局登记表。领域层重建时在自己那边登记，内核这一侧只管 `body` / `block` 两张。"""


def register(
    name: str,
    *,
    table: str = "",
    doc: str = "",
    ids: tuple[str, ...] = ID_FIELDS,
    refs: Mapping[str, str] | None = None,
) -> TypeDecl:
    """向全局登记表登记一个类型；表名默认取名字的小写写法。

    Raises:
        TableDeclarationError: 字段名不可绑、缺 `value_uuid`，或名字 / 表名已被占用。
    """
    return REGISTRY.register(
        TypeDecl(
            name=name,
            table=table or name.lower(),
            doc=doc,
            ids=ids,
            refs={} if refs is None else refs,
        )
    )


def table_of(name: str) -> TypeDecl | None:
    """按表名反查登记；没有即 ``None``。"""
    return REGISTRY.table(name)


__all__ = [
    "BINDABLE_FIELDS",
    "BLOCK_TABLE",
    "BODY_TABLE",
    "POINTER_FIELDS",
    "REGISTRY",
    "TABLES_FILENAME",
    "Nature",
    "OverBudget",
    "Registry",
    "Tier",
    "TypeDecl",
    "register",
    "table_of",
]

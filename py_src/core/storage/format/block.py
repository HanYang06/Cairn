# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""块与载荷：块是身份壳，body 是块自带的载荷；类型在这里登记自己。

块不携带领域语义词，承载类型由继承类给出；body 的承载结构不收窄，
但落盘前必须能给出确定性编码，否则同一逻辑内容会算出不同地址、去重失效。

**一块落成两条记录**（设计篇 §3.2.1、§4.4）：

- **内容记录**：载荷就是 body 字节本身，身份由内容签发，故同内容只存一份；
- **块记录**：载荷是指向 body 的指针，身份是块自己的。

于是"块记录还是内容记录"要靠**载荷里的保留键**分辨（§3.2.1）：保留键带不可打印前缀，
业务数据不可能占用它。若拿一个业务可能用到的普通键（例如 ``body_addr``）当判据，
一份形如 ``{"body_addr": …}`` 的正文就会被误判成块记录，去重失效、列举整体报错。

**类型定义即登记**（设计篇 §8.2 的"表会自己诞生"）：`:class:`Body`` 与 :class:`Block`
在定义时就往登记表里写下自己的名字与 ID 字段，于是"谁用了 ID"这件事有确定答案——
表的形状由登记表现算，不必手写。领域类只消继承 `Block`、写上自己的 `__table__`，
那张表就会在那一次运行里诞生。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, get_args, get_type_hints

import cbor2

from ..registry import BINDABLE_FIELDS, REGISTRY, TypeDecl
from .id import ID

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

BODY_REF_KEY = "\x00cairn.body_ref"
"""块记录载荷里的保留键：指向 body 的两套凭证。前缀即"业务数据不可能占用"的命名空间。"""

UUID_KEY = "value_uuid"
"""指针里的分配形态凭证键名。"""

HASH_KEY = "value_hash"
"""指针里的摘要形态凭证键名。"""


@dataclass(frozen=True, slots=True)
class BodyRef:
    """指向 body 的指针：**两套凭证都带**（设计篇 §3.2.1）。

    只带摘要时，`block` 表里"指向哪个 body"就只写得出一半——另一半（分配形态）
    是 body 自己的身份，丢了它就没法从块指向"那一份 body 记录"，只能指向"那份内容"。
    而内容相同的 body 可能不止一次落盘过（去重的是记录，不是身份），故必须两样都带。

    Attributes:
        value_uuid: 被指向的 body 的分配形态凭证。
        value_hash: 被指向的 body 的摘要形态凭证（内容地址）。
    """

    value_uuid: str
    value_hash: str

    def to_record(self) -> dict[str, str]:
        """编进载荷的映射形态。"""
        return {UUID_KEY: self.value_uuid, HASH_KEY: self.value_hash}

    @classmethod
    def from_record(cls, raw: Mapping[str, object]) -> BodyRef:
        """由载荷里的映射还原指针；两样缺一即抛，不补。"""
        return cls(
            value_uuid=_required_text(raw, UUID_KEY),
            value_hash=_required_text(raw, HASH_KEY),
        )


def encode_block_payload(ref: BodyRef) -> bytes:
    """把"指向 body 的指针"编成块记录的载荷（canonical CBOR）。

    规范化是必须的：同一份指针每次都要编出同一段字节，否则块身份（载荷摘要）会漂。
    """
    return cbor2.dumps({BODY_REF_KEY: ref.to_record()}, canonical=True)


def body_ref_of(payload: bytes) -> BodyRef | None:
    """从记录载荷里取出 body 指针；**不是块载荷**即返回 ``None``（那它就是内容）。

    判据只有一条：载荷是不是一个带保留键的映射，且键下是两套凭证。解不成映射、
    映射里没有保留键、或凭证不全，都算"这是内容记录"，不猜、不降级。
    """
    try:
        decoded = cbor2.loads(payload)
    except cbor2.CBORDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    raw = decoded.get(BODY_REF_KEY)
    if not isinstance(raw, dict) or UUID_KEY not in raw or HASH_KEY not in raw:
        return None
    try:
        return BodyRef.from_record(raw)
    except (TypeError, ValueError):
        return None


def register_type(cls: type[object]) -> TypeDecl:
    """把一个类型登记进登记表：名字取它的 `__table__`，列取它持有的 ID 字段。

    扫描的是**类的注解**（`get_type_hints`）：哪一项是 `ID`，它就是身份（`id: ID`
    落成整整一套身份列）；哪一项是另一个已登记的类型（如 `body: Body[T]`），
    它就是指向那张表的指针。

    Raises:
        TableDeclarationError: 名字或表名已被别的类型占用，或引用指向没登记的表。
    """
    # 表名看的是**本类自己写下的** `__table__`；继承来的不算——否则子类会顶掉父类那张表，
    # 而"每个类型一张表"正是这条机制的立论。没写就按类名推。
    table = str(cls.__dict__.get("__table__") or cls.__name__.lower())
    ids: list[str] = []
    refs: dict[str, str] = {}
    for name, hint in _hints(cls):
        if hint is ID:
            ids.extend(_IDENTITY_FIELDS)
            continue
        if name in BINDABLE_FIELDS:
            ids.append(name)
            continue
        target = _table_of_type(hint)
        if target is not None:
            refs[name] = target
    return REGISTRY.register(
        TypeDecl(
            name=cls.__name__,
            table=table,
            doc=_summary(cls),
            ids=tuple(ids) or _IDENTITY_FIELDS,
            refs=refs,
        )
    )


#: `id: ID` 那个字段落成的整整一套身份列（顺序即书写顺序）。
_IDENTITY_FIELDS: tuple[str, ...] = ("value_uuid", "value_hash", "birth_time", "name")


def _summary(cls: type[object]) -> str:
    """取类的 docstring 首行当表说明；没有就空串。"""
    doc = cls.__doc__
    return doc.strip().splitlines()[0] if doc and doc.strip() else ""


def _hints(cls: type[object]) -> Iterator[tuple[str, object]]:
    """取一个类的注解（解析成真实对象）；解不出来的项跳过，不让登记失败。"""
    try:
        resolved = get_type_hints(cls)
    except NameError:  # 注解里引用了本模块还看不到的名字：按能解出来的那部分登记
        resolved = {}
    return iter(resolved.items())


def _table_of_type(hint: object) -> str | None:
    """一个注解指向哪张表：是已登记的类型才有答案，否则 ``None``（不是引用）。

    `body: Body[T]` 这类注解本身不是类（它是泛型别名），故要往它的 `__origin__` 看一层；
    泛型实参（`T`）只是"某一类载荷"，不构成引用。
    """
    candidates: list[object] = [hint, getattr(hint, "__origin__", None), *_generics_of(hint)]
    for candidate in candidates:
        if isinstance(candidate, type):
            decl = REGISTRY.get(candidate.__name__)
            if decl is not None:
                return decl.table
    return None


def _generics_of(hint: object) -> tuple[object, ...]:
    """取出泛型实参（`Body[T]` → `(T,)`）：它们是"某一类载荷"，不是登记类型。"""
    return get_args(hint) or ()


def _required_text(raw: Mapping[str, object], key: str) -> str:
    """取一段必需的文本；缺了或不是字符串即抛。"""
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"指针缺少必需字段 {key!r}: {raw!r}")
    return value


@dataclass(slots=True)
class Body[T]:
    """数据载荷载体。

    Attributes:
        data: 载荷；字符串、列表、字典、二进制皆可，结构不作收窄。
        id: 载荷的身份；摘要形态由载荷内容算出（见 `ID.of`）。
    """

    data: T | None = None
    id: ID = field(default_factory=ID)

    __table__ = "body"
    """这张表的名字：**名字是表的坐标**，登记表与 `id(名字).字段` 都用它。"""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """子类定义完就登记自己：谁用了 ID，谁就在登记表里留下名字（设计篇 §8.2）。"""
        # 直接叫 `type` 那一版，不走零参 `super()`：后者要用隐式 `__class__` 单元，
        # 而 `Block[str]` 那样具体化出来的子类会让它取不到定义类
        super(Body, cls).__init_subclass__(**kwargs)
        register_type(cls)


@dataclass(slots=True)
class Block[T]:
    """存储单元：身份壳加自包含属性。

    Attributes:
        id: 块自身的身份。
        body: 块携带的载荷；先立壳、后挂载荷，故默认给一份空载荷。
    """

    id: ID = field(default_factory=ID)
    body: Body[T] = field(default_factory=Body[T])

    __table__ = "block"
    """这张表的名字：块表另有指向 `body` 的两列，故它比内容表宽。"""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """子类定义完就登记自己（域表的诞生点就在这里）。"""
        super(Block, cls).__init_subclass__(**kwargs)
        register_type(cls)


#: 两张内核表的登记必须在类定义之后发生：`__init_subclass__` 不在定义它的那个类上触发。
register_type(Body)
register_type(Block)


__all__ = [
    "BODY_REF_KEY",
    "HASH_KEY",
    "UUID_KEY",
    "Block",
    "Body",
    "BodyRef",
    "body_ref_of",
    "encode_block_payload",
    "register_type",
]

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
from enum import Enum
from typing import TYPE_CHECKING, Any, get_args, get_type_hints

import cbor2

from core.attr import attr_type_of
from core.exc import AttrTypeError, TableDeclarationError

from ..registry import BINDABLE_FIELDS, REGISTRY, Nature, OverBudget, Tier, TypeDecl
from .id import ID, ID_FIELDS

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from core.conf.types import TypeSpec

BODY_REF_KEY = "\x00cairn.body_ref"
"""块记录载荷里的保留键：指向 body 的两套凭证。前缀即"业务数据不可能占用"的命名空间。"""

ATTRS_KEY = "\x00cairn.attrs"
"""块记录载荷里的保留键：块自己的属性（`conf` 那套类型判据下的字段值）。

与 body 指针同一层：**属性不进 body**（body 是大头内容、按地址去重），
也不靠数据库列承载（库只是索引）。顺扫读出载荷即得属性，故它可重建。
"""

TOMBSTONE_KEY = "\x00cairn.tombstone"
"""记录载荷里的保留键：**这一条是墓碑**，指向被删记录的身份与位置。

墓碑是删除留下的标记。载体是追加写，旧字节删不掉，故用一条标记说"那份不算数了"。
它**不进索引**——索引里不该有它的行（它是盘上的事实，顺扫即得）；巡检认识它，
不会再把被删的那条记录报成"盘上有、库里没行"。

**它破例落一个位置**：记录自己从不写"我在哪"（扫到它时那个位置就已知），
但墓碑说的是**别人**的位置，不说就无从判断哪一条已被删除。
这个位置是可重建的（顺扫一遍墓碑即得），故不破"库只做索引"。
"""

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


def encode_block_payload(ref: BodyRef, attrs: Mapping[str, object] | None = None) -> bytes:
    """把块记录的载荷编成 canonical CBOR：**body 指针必带，属性非空才写**。

    规范化是必须的：同一份载荷每次都要编出同一段字节，否则块身份（载荷摘要）会漂。

    属性跟着块走是刻意的：它**不进 body**（body 是大头内容、按地址去重，塞进去会把
    去重切碎），也**不靠数据库列承载**（库只是索引）。故顺扫读出载荷即得属性。

    Raises:
        AttrTypeError: 属性值编不进 CBOR（如 `Path`、自定义对象）。
    """
    payload: dict[str, object] = {BODY_REF_KEY: ref.to_record()}
    if attrs:
        payload[ATTRS_KEY] = dict(attrs)
    try:
        return cbor2.dumps(payload, canonical=True)
    except cbor2.CBOREncodeError as error:
        raise AttrTypeError(f"块属性编不进载荷: {error}") from error


@dataclass(frozen=True, slots=True)
class BlockPayload:
    """块记录载荷的两部分：指向 body 的指针，与块自己的属性。

    Attributes:
        ref: 被指向的 body 的两套凭证。
        attrs: 块自己声明的属性值；没有声明过属性的块，这里是空映射。
    """

    ref: BodyRef
    attrs: Mapping[str, object]


def block_payload_of(payload: bytes) -> BlockPayload | None:
    """从记录载荷里取出块的两部分；**不是块载荷**即返回 ``None``（那它就是内容）。

    判据只有一条：载荷是不是一个带保留键的映射，且键下是两套凭证。解不成映射、
    映射里没有保留键、或凭证不全，都算"这是内容记录"，不猜、不降级。

    属性是**可选**的：没有那个键就是"这块没声明过属性"，不是错——旧记录与没有任何
    属性的块都长这样，故此处不报错、也不补一个空映射以外的任何东西。
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
        ref = BodyRef.from_record(raw)
    except (TypeError, ValueError):
        return None
    attrs = decoded.get(ATTRS_KEY)
    return BlockPayload(ref=ref, attrs=attrs if isinstance(attrs, dict) else {})


def body_ref_of(payload: bytes) -> BodyRef | None:
    """只取 body 指针（块身份核对与巡检的常用面）；不是块载荷即 ``None``。"""
    parsed = block_payload_of(payload)
    return None if parsed is None else parsed.ref


@dataclass(frozen=True, slots=True)
class Tombstone:
    """一块墓碑：被删记录的身份，与它躺在哪儿。

    Attributes:
        value_uuid: 被删记录的身份（分配形态）。
        value_hash: 被删记录的摘要形态（内容地址）。
        hub: 被删记录所在的 hub。
        pack: 被删记录所在的载体。
        span: 被删记录占的格区间（头格，末格），闭区间。
    """

    value_uuid: str
    value_hash: str
    hub: str
    pack: str
    span: tuple[int, int]

    def to_record(self) -> dict[str, object]:
        """编进载荷的映射形态：位置写成两格号，与 `SlotRange` 同一口径。"""
        return {
            UUID_KEY: self.value_uuid,
            HASH_KEY: self.value_hash,
            "hub": self.hub,
            "pack": self.pack,
            "span": [self.span[0], self.span[1]],
        }

    @classmethod
    def from_record(cls, raw: Mapping[str, object]) -> Tombstone:
        """由载荷里的映射还原墓碑；任一项不合法即抛，不补。"""
        span = raw.get("span")
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            raise ValueError(f"墓碑的格区间不合法: {span!r}")
        first, last = span
        if not isinstance(first, int) or not isinstance(last, int) or isinstance(first, bool):
            raise TypeError(f"墓碑的格区间不是两个整数: {span!r}")
        return cls(
            value_uuid=_required_text(raw, UUID_KEY),
            value_hash=_required_text(raw, HASH_KEY),
            hub=_required_text(raw, "hub"),
            pack=_required_text(raw, "pack"),
            span=(first, last),
        )


def encode_tombstone(tombstone: Tombstone) -> bytes:
    """把一块墓碑编成记录载荷（canonical CBOR）。"""
    return cbor2.dumps({TOMBSTONE_KEY: tombstone.to_record()}, canonical=True)


def tombstone_of(payload: bytes) -> Tombstone | None:
    """从记录载荷里取出墓碑；**不是墓碑**即返回 ``None``。

    判据与块载荷同一套：带保留键、且键下解得出来。解不出就算"这不是墓碑"，
    不猜、不降级——按内容读它是巡检那一侧的事。
    """
    try:
        decoded = cbor2.loads(payload)
    except cbor2.CBORDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    raw = decoded.get(TOMBSTONE_KEY)
    if not isinstance(raw, dict):
        return None
    try:
        return Tombstone.from_record(raw)
    except (TypeError, ValueError):
        return None


def register_type(cls: type[object]) -> TypeDecl:
    """把一个类型登记进登记表：名字取它的 `__table__`，列取它持有的 ID 字段。

    扫描的是**类的注解**（`get_type_hints`），四种注解各有归宿：

    - `id: ID` —— 身份，落成整整一套身份列；
    - 名字本身就是 `ID` 的字段（`name` / `birth_time` …）—— 那一列；
    - `field: attr[T]` —— **属性**：跟着块记录走，登记下来只为「哪些字段该落盘、
      各是什么类型」有确定答案（判据与 `conf` 共用）；
    - 另一个已登记的类型（如 `body: Body[T]`）—— 指向那张表的指针。

    其余的注解（如裸的 `title: str`）**不算数**：没声明过的字段不落盘，内核也不替它猜。

    Raises:
        TableDeclarationError: 名字或表名已被别的类型占用，或引用指向没登记的表。
        AttrTypeError: 写了 `attr` 但类型实参不合规矩。
    """
    # 表名看的是**本类自己写下的** `__table__`；继承来的不算——否则子类会顶掉父类那张表，
    # 而"每个类型一张表"正是这条机制的立论。没写就按类名推。
    table = str(cls.__dict__.get("__table__") or cls.__name__.lower())
    ids: list[str] = []
    refs: dict[str, str] = {}
    attrs: list[tuple[str, TypeSpec]] = []
    for name, hint in _hints(cls):
        if hint is ID:
            ids.extend(_IDENTITY_FIELDS)
            continue
        if name in BINDABLE_FIELDS:
            ids.append(name)
            continue
        spec = attr_type_of(hint)
        if spec is not None:
            attrs.append((name, spec))
            continue
        target = _table_of_type(hint)
        if target is not None:
            refs[name] = target
    return REGISTRY.register(
        _decl_of(
            cls,
            table=table,
            ids=tuple(ids) or _IDENTITY_FIELDS,
            refs=refs,
            attrs=tuple(attrs),
        )
    )


def _decl_of(
    cls: type[object],
    *,
    table: str,
    ids: tuple[str, ...],
    refs: dict[str, str],
    attrs: tuple[tuple[str, TypeSpec], ...],
) -> TypeDecl:
    """由类体的注解与那组 `__…__` 拼出一份类型登记。

    注解定**列与属性**（`ID` / ID 字段名 / `attr[T]` / 已登记类型）；
    `__…__` 定**存储行为**（性质、归属、配额、体积上限）。后者**不进声明文件**——
    那份文件只描述库的形状，而"配额多少"是策略，不是形状。
    """
    return TypeDecl(
        name=cls.__name__,
        table=table,
        doc=_summary(cls),
        ids=ids,
        refs=refs,
        attrs=attrs,
        nature=_enum_field(cls, "__nature__", Nature, Nature.DATA),
        owner=_text_field(cls, "__owner__", "core"),
        tier=_enum_field(cls, "__tier__", Tier, Tier.DERIVED),
        backup=_flag_field(cls, "__backup__"),
        own_hub=_flag_field(cls, "__own_hub__"),
        hub=_text_field(cls, "__hub__", ""),
        slot_budget=_budget_field(cls, "__slot_budget__"),
        pack_budget=_budget_field(cls, "__pack_budget__"),
        max_block_bytes=_max_block_bytes(cls),
        over_budget=_enum_field(cls, "__over_budget__", OverBudget, OverBudget.EXTEND),
        indexed=_texts_field(cls, "__indexed__"),
    )


#: 单块上限的分档：后缀 → 每单位多少字节（1024 进制）。**单位是字节，不是位。**
_BLOCK_SIZE_FACTORS: tuple[tuple[str, int], ...] = (
    ("byte", 1),
    ("kbyte", 1024),
    ("mbyte", 1024**2),
    ("gbyte", 1024**3),
)


def _enum_field[T: Enum](cls: type[object], dunder: str, expected: type[T], default: T) -> T:
    """读一个枚举声明：本类没写就用默认值，写了但不是那个枚举即报错。"""
    value = cls.__dict__.get(dunder)
    if value is None:
        return default
    if not isinstance(value, expected):
        raise TableDeclarationError(
            f"{cls.__name__} 的 {dunder} 必须是 {expected.__name__}: {value!r}"
        )
    return value


def _text_field(cls: type[object], dunder: str, default: str) -> str:
    """读一段文本声明：本类没写就用默认值，写了但不是字符串即报错。"""
    value = cls.__dict__.get(dunder)
    if value is None:
        return default
    if not isinstance(value, str):
        raise TableDeclarationError(f"{cls.__name__} 的 {dunder} 必须是字符串: {value!r}")
    return value


def _flag_field(cls: type[object], dunder: str) -> bool:
    """读一个开关声明：本类没写即关。只收布尔——`1` 与 `True` 是两回事。"""
    value = cls.__dict__.get(dunder)
    if value is None:
        return False
    if not isinstance(value, bool):
        raise TableDeclarationError(f"{cls.__name__} 的 {dunder} 必须是布尔值: {value!r}")
    return value


def _budget_field(cls: type[object], dunder: str) -> int | None:
    """读一个配额声明：本类没写即 `None`（等于没有这个配额）。"""
    value = cls.__dict__.get(dunder)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TableDeclarationError(f"{cls.__name__} 的 {dunder} 必须是整数: {value!r}")
    return value


def _texts_field(cls: type[object], dunder: str) -> tuple[str, ...]:
    """读一串名字的声明（如 `__indexed__`）：本类没写即空。

    只收字符串序列——写成单个字符串是最常见的笔误，故不让它"看起来也能用"。
    """
    value = cls.__dict__.get(dunder)
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        raise TableDeclarationError(f"{cls.__name__} 的 {dunder} 必须是字符串序列: {value!r}")
    return tuple(value)


def _max_block_bytes(cls: type[object]) -> int | None:
    """把分档写下的单块上限**相加归一**成字节数；一档都没写即 `None`。

    分档只为写得直观（`__max_block_mbyte__ = 1`）；进登记的只有归一后的那个数——
    否则同一份上限的两种等价写法会变成两份事实。
    """
    total = 0
    for suffix, factor in _BLOCK_SIZE_FACTORS:
        value = _budget_field(cls, f"__max_block_{suffix}__")
        if value is not None:
            total += value * factor
    return total or None


def block_attrs[T](block: Block[T]) -> dict[str, object]:
    """取一个块实例上**声明过的**属性值：只取登记里有的那些字段。

    判据用登记的 `TypeDecl.attrs`，故没声明过的字段不进载荷——"哪些字段算数"有确定
    答案，不必靠 `__dict__` 猜。返回空映射的意思是"这块没有属性"，不是"取不出来"。
    """
    decl = REGISTRY.get(type(block).__name__)
    if decl is None or not decl.attrs:
        return {}
    return {name: getattr(block, name) for name, _ in decl.attrs}


#: `id: ID` 那个字段落成的整整一套身份列 = `ID` 的全部字段（顺序即 `ID` 的声明顺序）。
_IDENTITY_FIELDS: tuple[str, ...] = ID_FIELDS


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
    "ATTRS_KEY",
    "BODY_REF_KEY",
    "HASH_KEY",
    "TOMBSTONE_KEY",
    "UUID_KEY",
    "Block",
    "BlockPayload",
    "Body",
    "BodyRef",
    "Tombstone",
    "block_attrs",
    "block_payload_of",
    "body_ref_of",
    "encode_block_payload",
    "encode_tombstone",
    "register_type",
    "tombstone_of",
]

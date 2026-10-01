# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
r"""块与载荷：块是身份壳，body 是块自带的载荷；类型在这里登记自己。

**块的形状在 ``__init__`` 里声明**——声明与构造写在一处：

    class NoteGroup(Block):
        def __init__(self) -> None:
            super().__init__()
            self.name = attr(default="")
            self.notes = Body(factory=list[str])

三种声明各有各的落点：

- ``attr(...)`` —— **属性**，跟着块记录走（`\\x00cairn.attrs`）；
- ``Body(...)`` —— **载荷**，落成 body 记录（按内容地址去重）；
- 其余赋值 —— 普通实例状态，**不落盘**。

基座把子类的 ``__init__`` 包一层：用户的声明跑完之后扫一遍实例，把这些标记收成**类型形状**
（谁用了 ID、有哪些属性、哪些是载荷），并把标记换成真实默认值。形状**由一次零参探针现算**，
故 ``__init__`` 必须能零参调用；形状**不许依赖运行期条件**，否则同一张表的列会随环境变。

**一块落成两条记录**（设计篇 §3.2.1、§4.4）：

- **内容记录**：载荷就是 body 字节本身，身份由内容签发，故同内容只存一份；
- **块记录**：载荷是指向 body 的指针，身份是块自己的。

于是"块记录还是内容记录"要靠**载荷里的保留键**分辨（§3.2.1）：保留键带不可打印前缀，
业务数据不可能占用它。若拿一个业务可能用到的普通键（例如 ``body_addr``）当判据，
一份形如 ``{"body_addr": …}`` 的正文就会被误判成块记录，去重失效、列举整体报错。

**继承即登记**：定义时把类排进待探清单，形状第一次被问到时（开库算表、按类型查行）
探一次、登记一次；表随之诞生。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import TYPE_CHECKING, Any, overload

import cbor2

from core.attr import AttrDecl, attr_decl
from core.conf.types import MISSING
from core.exc import AttrTypeError, BlockShapeError, TableDeclarationError

from ..registry import REGISTRY, OverBudget, Tier, TypeDecl
from .id import ID, ID_FIELDS

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

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


# ---- 载荷声明：`Body(...)` ----


def _fresh(value: object) -> object:
    """把缺省值取一份：容器现拷，标量原样。理由与属性那边同一条（实例之间不串）。"""
    if isinstance(value, list):
        return list(value)
    if isinstance(value, dict):
        return dict(value)
    return value


@dataclass(frozen=True, slots=True)
class BodyDecl:
    """一条载荷声明：这个字段进 body 记录（按内容地址去重的那一份）。

    Attributes:
        default: 字面缺省值；写工厂时是 ``None``。
        factory: 缺省值的工厂；写字面值时是 ``None``。
    """

    default: object = None
    factory: Callable[[], object] | None = None

    def make(self) -> object:
        """造一个缺省值：有工厂就现调一次，否则把字面值拷一份。"""
        if self.factory is not None:
            return self.factory()
        return _fresh(self.default)


@overload
def Body[T](*, default: T) -> T: ...


@overload
def Body[T](*, factory: Callable[[], T]) -> T: ...


def Body(*, default: object = MISSING, factory: Callable[[], object] | None = None) -> object:
    """声明一条**载荷**。**类型上返回缺省值的类型，运行时返回 :class:`BodyDecl`。**

    载荷与属性的分别只在落点：载荷进 body 记录（大头内容、按内容地址去重），
    属性跟着块记录走。同一个块可以声明多条载荷，它们一起编进那一份 body。

    Args:
        default: 字面缺省值。
        factory: 缺省值的工厂（可变默认值走它，``list[str]`` 一类）。

    Raises:
        BlockShapeError: 缺省值给重了，或一个都没给。
    """
    if default is MISSING and factory is None:
        raise BlockShapeError("载荷声明要给出缺省值：`Body(default=…)` 或 `Body(factory=…)`")
    if default is not MISSING and factory is not None:
        raise BlockShapeError("载荷声明的缺省值只能给一个出处：default 或 factory")
    return BodyDecl(default=None if default is MISSING else default, factory=factory)


def body_decl(value: object) -> BodyDecl | None:
    """这个值是不是一条载荷声明；不是即 ``None``。"""
    return value if isinstance(value, BodyDecl) else None


# ---- 形状：从实例上收声明 ----

_WRAPPER_FLAG = "_cairn_declaring"
"""基座包过的 ``__init__`` 上的记号：认得出就不重复包（探针可以被重新排多次）。"""


@dataclass(frozen=True, slots=True)
class _Shape:
    """一个类型报上来的形状：ID 角色、属性（名字 + 声明）、载荷字段名，顺序即声明顺序。

    ``ids`` 装的是**持有 ID 的字段名**：名字叫 ``id`` 的那一个是它自己的身份，
    有它才产生一张表；没有就是"只活在载荷里的结构"，不登记、不建表。
    """

    ids: tuple[str, ...] = ()
    attrs: tuple[tuple[str, AttrDecl], ...] = ()
    payload: tuple[str, ...] = ()


_SHAPES: dict[type[object], _Shape] = {}
"""已收货的形状：键是**实例的真实类**，收货时与上一份**并**起来——
逐层包 `__init__` 会让内层先把父类的标记换成真实值，故不能重扫覆盖。"""


def _declaring_init(base: Callable[..., None]) -> Callable[..., None]:
    """把一个 ``__init__`` 包一层：先跑它，再收货并换成真实默认值。"""

    @wraps(base)
    def start(self: object, *args: Any, **kwargs: Any) -> None:
        base(self, *args, **kwargs)
        _harvest(self)

    setattr(start, _WRAPPER_FLAG, True)
    return start


def _harvest(instance: object) -> None:
    """扫一遍实例：把声明收成形状，并把标记换成真实默认值。

    **只认标记，不认注解**：``self.x: attr[str] = …`` 里的注解在函数体里会被 Python
    丢掉（连求值都不发生），故性质只能由右边的标记给出——这也正是"各有各的结构"。

    **ID 是报上来的**：哪个字段上是 :class:`ID`，哪个字段就是一条"用 ID 的角色"；
    其中名字叫 ``id`` 的那一条是它自己的身份，**有它才有表**。
    """
    ids: list[str] = []
    attrs: list[tuple[str, AttrDecl]] = []
    payload: list[str] = []
    fields = vars(instance)
    for name, value in list(fields.items()):
        if isinstance(value, ID):
            ids.append(name)
            continue
        attribute = attr_decl(value)
        if attribute is not None:
            attrs.append((name, attribute))
            fields[name] = attribute.make()
            continue
        body = body_decl(value)
        if body is not None:
            payload.append(name)
            fields[name] = body.make()
    previous = _SHAPES.get(type(instance))
    _SHAPES[type(instance)] = _Shape(
        ids=_union(() if previous is None else previous.ids, ids),
        attrs=_merged_attrs(() if previous is None else previous.attrs, attrs),
        payload=_union(() if previous is None else previous.payload, payload),
    )


def _union(previous: tuple[str, ...], new: list[str]) -> tuple[str, ...]:
    """并两拨名字，保持先出现的顺序（继承来的在前，本类后声明的在后）。"""
    return tuple(dict.fromkeys((*previous, *new)))


def _merged_attrs(
    previous: tuple[tuple[str, AttrDecl], ...], new: list[tuple[str, AttrDecl]]
) -> tuple[tuple[str, AttrDecl], ...]:
    """并两拨属性：同名的以后声明的为准，位置保持先出现的那个。"""
    merged = dict(previous)
    merged.update(new)
    return tuple(merged.items())


def _ensure_shape(cls: type[object]) -> _Shape:
    """取一个类型的形状：没有就跑一次**零参探针**（``cls()``）现收。

    Raises:
        BlockShapeError: 这个类没法零参构造（形状探不出来）。
    """
    shape = _SHAPES.get(cls)
    if shape is not None:
        return shape
    try:
        cls()
    except TypeError as error:
        # 探不动的类型撤掉它的探针：否则每一次查登记都要再炸一遍，一个坏类型毒掉一片查询。
        REGISTRY.drop_probe(cls)
        raise BlockShapeError(
            f"类型 {cls.__name__} 的形状探不出来：`__init__` 必须能零参调用（{error}）"
        ) from error
    return _SHAPES[cls]


def declare_type(cls: type[object]) -> TypeDecl | None:
    """把一个块类型报上来的形状交给登记表；**没有自己的 ID 就不登记**。

    这就是"表自然产生"那一步：类型不必去认领一张表，它只消在 ``__init__`` 里
    给 ``self.id`` 放一个 :class:`ID`；没有 ID 的类型是**只活在载荷里的结构**
    （值对象），它不进登记表、不建表，但形状照样收着——编码器按它遍历。

    Returns:
        登记进去的那份声明；这个类型没有自己的 ID 时返回 ``None``。

    Raises:
        TableDeclarationError: 名字或表名已被别的类型占用，或表形状立不起来。
        BlockShapeError: 形状探不出来。
    """
    shape = _ensure_shape(cls)
    if "id" not in shape.ids:
        return None
    return REGISTRY.register(_decl_of(cls, shape))


def adopt(cls: type[object]) -> None:
    """接管一个块类型：包一层 ``__init__``，并排一次零参探针。重复调用是幂等的。

    探针的意义：**开库算表的时候还没有人构造过任何实例**，表形状仍要有答案。
    故形状第一次被问到时探一遍——探针只做声明，不许有外部副作用。
    """
    current = cls.__dict__.get("__init__")
    if not getattr(current, _WRAPPER_FLAG, False):
        # 本类没写 `__init__` 时取**继承下来的那一个**（父类已被包过的那层），
        # 而不是 `Block.__init__`：继承来的声明也要跑一遍，否则子类会整份丢掉父类的字段。
        base = cls.__init__ if current is None else current
        setattr(cls, "__init__", _declaring_init(base))  # noqa: B010 — 类对象上的方法不能直接赋值

    def probe() -> None:
        """探一次：没有 ID 的类型不登记，故这里的返回值直接丢掉。"""
        declare_type(cls)

    REGISTRY.add_probe(probe, key=cls)


def install_core_types() -> None:
    """装上内核自己那两张表的形状：`block`（块）与 `body`（内容）。

    它们不由用户类型的构造声明而来：块表的主语是块、body 表的主语是内容，
    都是内核机制，故在这里写死（与 `hub` 那张"不由类型诞生"的表同一路数）。
    """
    REGISTRY.register(
        TypeDecl(
            name="Block",
            table="block",
            doc="存储单元：身份壳，指向它携带的那份作业",
            ids=ID_FIELDS,
            refs={"body": "body"},
        )
    )
    REGISTRY.register(
        TypeDecl(
            name="Body",
            table="body",
            doc="内容记录：按内容地址去重的载荷本身",
            ids=ID_FIELDS,
        )
    )


class Block:
    """数据结构的基座：**身份可选**，字段在 ``__init__`` 里声明。

    有没有给 ID 决定它是哪一种：

    - 给了 ``self.id = ID()`` —— 它是一个**块**：登记、建表，可单独落盘与查询；
    - 没给 —— 它是一个**结构**：只活在别人的载荷里（值对象），不登记、不建表。

    于是"创建一个数据结构"只有一条路：**继承 + 在 ``__init__`` 里写字段**，
    没有第二个类、没有 dunder 样板：

        class NoteGroup(Block):
            def __init__(self) -> None:
                super().__init__()
                self.id = ID()
                self.name = attr(default="")
                self.notes = Body(factory=list[str])

    表名默认取类名的小写写法，要改就写 ``__table__``；归属默认按包路径推
    （``model.<域>.**`` → 域名），要改就写 ``__owner__``。

    Attributes:
        id: 块自身的身份。**由声明给出**：本基座不代为签发——要就要，不要就没有表。
    """

    __table__ = "block"
    """这张表的名字：块表另有指向 `body` 的两列，故它比内容表宽。"""

    def __init__(self, *, id: ID | None = None) -> None:
        """不自动签发身份：要 ID 就自己声明（``self.id = ID()``），加了才有表。"""
        if id is not None:
            self.id = id

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """子类定义完就接管它（形状待探、`__init__` 待包）。"""
        super().__init_subclass__(**kwargs)
        adopt(cls)


def _decl_of(cls: type[object], shape: _Shape) -> TypeDecl:
    """由类的声明与那组 `__…__` 拼出一份类型登记。

    注解与标记定**属性与载荷**；`__…__` 定**存储行为**（归属、配额、体积上限）。
    后者**不进声明文件**——那份文件只描述库的形状，而"配额多少"是策略，不是形状。
    """
    return TypeDecl(
        name=cls.__name__,
        table=str(cls.__dict__.get("__table__") or cls.__name__.lower()),
        doc=_summary(cls),
        ids=_IDENTITY_FIELDS if "id" in shape.ids else (),
        refs={"body": "body"},
        attrs=tuple((name, declaration.spec) for name, declaration in shape.attrs),
        payload=shape.payload,
        owner=_owner(cls),
        tier=_enum_field(cls, "__tier__", Tier, Tier.DERIVED),
        backup=_flag_field(cls, "__backup__"),
        own_hub=_flag_field(cls, "__own_hub__"),
        hub=_text_field(cls, "__hub__", ""),
        slot_budget=_budget_field(cls, "__slot_budget__"),
        pack_budget=_budget_field(cls, "__pack_budget__"),
        max_block_bytes=_max_block_bytes(cls),
        over_budget=_enum_field(cls, "__over_budget__", OverBudget, OverBudget.EXTEND),
        indexed=tuple(name for name, declaration in shape.attrs if declaration.indexed),
    )


#: 单块上限的分档：后缀 → 每单位多少字节（1024 进制）。**单位是字节，不是位。**
_BLOCK_SIZE_FACTORS: tuple[tuple[str, int], ...] = (
    ("byte", 1),
    ("kbyte", 1024),
    ("mbyte", 1024**2),
    ("gbyte", 1024**3),
)


def _owner(cls: type[object]) -> str:
    """归属：本类写死的优先，否则按包路径推——`model.<域>.**` 归那个域，其余归 `core`。"""
    declared = cls.__dict__.get("__owner__")
    if declared is not None:
        if not isinstance(declared, str):
            raise TableDeclarationError(f"{cls.__name__} 的 __owner__ 必须是字符串: {declared!r}")
        return declared
    parts = str(getattr(cls, "__module__", "")).split(".")
    return parts[1] if len(parts) >= 2 and parts[0] == "model" else "core"


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


def block_attrs[T](block: Block) -> dict[str, object]:
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


def _required_text(raw: Mapping[str, object], key: str) -> str:
    """取一段必需的文本；缺了或不是字符串即抛。"""
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"指针缺少必需字段 {key!r}: {raw!r}")
    return value


install_core_types()


__all__ = [
    "ATTRS_KEY",
    "BODY_REF_KEY",
    "HASH_KEY",
    "TOMBSTONE_KEY",
    "UUID_KEY",
    "Block",
    "BlockPayload",
    "Body",
    "BodyDecl",
    "BodyRef",
    "Tombstone",
    "adopt",
    "block_attrs",
    "block_payload_of",
    "body_decl",
    "body_ref_of",
    "declare_type",
    "encode_block_payload",
    "encode_tombstone",
    "install_core_types",
    "tombstone_of",
]

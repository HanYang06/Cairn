# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""块（Block）：唯一被存进桶的东西，也是所有领域结构的**基类**。

``Block`` 本身不直接实例化（未登记的 ``type`` 会退回它，作为裸块）。领域结构继承它，
用 ``Attr`` / ``Body`` 重新描述字段。它是**面向存储/硬件**的、自利自足的：
只关心「怎么把这块内容存下去、取回来」，不关心上层业务语义。

字段一览（子类可重新描述 body / attrs，不可动 id 与 checksum 口径）：

    id        稳定身份（OID，ULID），创建时分配，**锁死不可改**
    checksum  内容签名（BLAKE3 十六进制），由 ``content()`` 推出；子类可覆写口径
    type     承载类型（str / Enum），如 ``notedata``
    body      主体，由子类用 ``Body(...)`` 重新描述（默认是裸 Body）
    attrs     原生属性，用 ``Attr`` 声明；**领域数据都放这里**（含 config 之外的一切）
    config    写入配置：驱动写入行为（如 ``isolated`` 独占载体）
    author    作者（存储写入者）
    size      主体字节数（bytes 取长度，其余取确定性编码长度）
    created   创建时间（unix 毫秒）
    updated   最近写入时间（unix 毫秒）

铁律 / 约定（谁都不许破）：

1. **id 锁死**：创建即分配，之后不可改（改则抛 ``AttributeError``）。
2. **checksum 是 body 哈希**：``body_hash()`` 只算 body（不含 id / attrs / 签名），
   桶据此在**内容池**里按哈希去重——同 body 复用同一份内容。子类可覆写口径
   （如笔记剥离行 id、把行内样式算入）。attrs 随块行单独存，不参与去重。
3. **decode 用子类口径重算**：读回时由「body 字节 + attrs」拼合，再调 ``compute_checksum()``，
   保证与 ``put`` 时一致（否则覆写了口径的领域对象会读回失败）。
4. **块不承载版本**：版本是笔记 / 项目各自的策略（走 ``VersionStore``），块只存当前内容。
5. **去重发生在领域层**：小内容按 checksum 共享物理内容；分片块（PART/INDEX）不去重。
6. **读写不碰事务、不碰目录**：把整个对象交给桶即可；事务由桶统一收口。

用法：

    note = bucket.new(Note)      # 拿到一个可编辑对象（id 已分配）
    note.title = "第一则"
    note.body.append("正文")
    bucket.put(note)             # 一次调用即落盘；不碰任何事务

    same = bucket.get(Note, note.id)   # 按稳定 id 取回，仍是可编辑对象
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, Self, get_origin

import cbor2
from blake3 import blake3

from core.types import (
    ROLE_DATA,
    CairnError,
    CorruptObjectError,
    TypeInfo,
    ValueUuid,
    collect_fields,
    register,
)
from core.types.attr import Attr, Data

if TYPE_CHECKING:
    import builtins

INDEX_TYPE = "index"
PART_TYPE = "part"
"""分片用到的两个块类型（大 body 切成 part、由 index 块聚合）。

**预留**：分片尚未接到块面（见设计篇 §5.6 的分片粒度与 §12），此处只留词表。
"""

_MISSING = object()


def canonical(obj: Any) -> bytes:
    """确定性 CBOR 编码：同一结构字节唯一，服务 checksum / 去重。"""
    return cbor2.dumps(obj, canonical=True)


def decode_canonical(data: bytes) -> Any:
    """解码 ``canonical`` 的输出。"""
    return cbor2.loads(data)


def _digest(payload: bytes) -> str:
    return blake3(payload).hexdigest()


def _type_name(value: str | Enum) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


class Body:
    """body 容器基类：**无 ID**、依存于块；自带状态字段 ``hash``。

    子类声明自己的内容字段，并实现 ``content()``（参与哈希的内容视图）与
    ``to_data()`` / ``from_data()``（落盘）。``hash`` **只覆盖内容字段**，
    排除自身状态（hash 自己、时间戳等）——否则自我指涉、且时间戳会让去重永远失败。

    约定：内容一变更就调 ``refresh()`` 重算一次并存下来，之后直接用，不重复算。
    但**去重键不信任这份缓存**——``Block.body_hash()`` 每次都重算，见其说明。
    """

    hash: str = ""

    def content(self) -> Any:
        """参与哈希的内容字段（子类实现）。"""
        raise NotImplementedError

    def refresh(self) -> Body:
        """内容变更后重算一次 ``hash``。"""
        self.hash = _digest(canonical(self.content()))
        return self

    def to_data(self) -> Any:
        raise NotImplementedError

    @classmethod
    def from_data(cls, data: Any) -> Body:
        raise NotImplementedError


class BodyField[T = Any]:
    """``body`` 字段的声明：惰性建值、每实例一份、结构化时校验是 ``Body``。

    - ``BodyField()``：裸 body（bytes / list / 标量），原样存取。
    - ``BodyField(prototype=NoteBody())``：结构化 body；读取按 prototype 类型**每实例新建**
      （用 ``from_data(to_data())``），写入时非 ``Body`` 则 ``from_data`` 转换。
    """

    def __init__(
        self,
        default: Any = _MISSING,
        *,
        factory: Callable[[], Any] | None = None,
        prototype: Body | None = None,
    ) -> None:
        self._default = default
        self._factory = factory
        self._prototype = prototype
        self.key = ""

    def __set_name__(self, _owner: type, name: str) -> None:
        self.key = name

    def _fresh(self) -> Any:
        if self._prototype is not None:
            return type(self._prototype).from_data(self._prototype.to_data())
        if self._factory is not None:
            return self._factory()
        return None if self._default is _MISSING else self._default

    def __get__(self, obj: Block | None, _owner: type | None = None) -> Any:
        if obj is None:
            return self
        if "_body" not in obj.__dict__:
            obj.__dict__["_body"] = self._fresh()
        return obj.__dict__["_body"]

    def __set__(self, obj: Block, value: Any) -> None:
        if self._prototype is not None and not isinstance(value, Body):
            value = type(self._prototype).from_data(value)
        obj.__dict__["_body"] = value


def _annotation_kind(annotation: Any) -> str | None:
    """注解是 ``Attr`` 还是 ``Data``（及其下标）；都不是返回 ``None``。"""
    if isinstance(annotation, str):
        name = annotation.split("[", 1)[0].strip()
        if name in ("Attr", "Data"):
            return name.lower()
        return None
    origin = get_origin(annotation)
    if origin is Attr:
        return "attr"
    if origin is Data:
        return "data"
    return None


def _is_container_annotation(annotation: Any) -> bool:
    """注解是否是裸容器（``list[...]`` / ``dict[...]``）——数据字段可自证类型、免标记。"""
    if isinstance(annotation, str):
        return annotation.startswith(("list[", "dict[", "tuple[", "set["))
    return get_origin(annotation) in (list, dict, tuple, set)


def _attr_from_value(value: Any) -> Attr[Any]:
    """把类体里的裸默认值包成 ``Attr``：注解即类型，右边即值。"""
    if isinstance(value, (list, tuple)):
        items = list(value)
        return Attr(factory=lambda: list(items))
    if isinstance(value, Mapping):
        mapping = dict(value)
        return Attr(factory=lambda: dict(mapping))
    if hasattr(value, "to_data"):
        return Attr(item=type(value), default=value)
    return Attr(default=value)


def _data_from_value(value: Any) -> Data[Any]:
    """把容器注解的裸默认值包成 ``Data``（数据字段）。"""
    if isinstance(value, list):
        items = list(value)
        return Data(factory=lambda: list(items))
    mapping = dict(value)
    return Data(factory=lambda: dict(mapping))


def _descriptor_for(annotation: Any, value: Any) -> Any:
    """按「注解 + 裸默认值」解析字段描述符；不适用返回 ``None``（跳过）。

    - 结构化 ``Body`` → ``BodyField(prototype=...)``；已是描述符的原样跳过。
    - ``Data[...]`` 容器 → ``Data``；标量退回 ``Attr``。
    - ``Attr[...]`` → ``Attr``；裸容器注解（``list[...]`` 等）→ ``Data``。
    """
    if isinstance(value, Body):
        return BodyField(prototype=value)
    if isinstance(value, Attr):
        return None  # 已是描述符，Python 会自动 __set_name__，不重包
    kind = _annotation_kind(annotation)
    descriptor: Any = None
    if kind == "data":
        descriptor = (
            _data_from_value(value) if isinstance(value, (list, dict)) else _attr_from_value(value)
        )
    elif kind == "attr":
        descriptor = _attr_from_value(value)
    elif _is_container_annotation(annotation) and isinstance(value, (list, dict)):
        descriptor = _data_from_value(value)
    return descriptor


def _body_type(cls: builtins.type[Block]) -> builtins.type[Body] | None:
    """类声明的 body 类型（结构化 body）；裸 body 返回 ``None``。"""
    field = cls.__dict__.get("body")
    if isinstance(field, BodyField) and field._prototype is not None:  # noqa: SLF001 — 同模块内省
        return type(field._prototype)  # noqa: SLF001
    return None


def _body_from_data(target: builtins.type[Block], raw: Any) -> Any:
    kind = _body_type(target)
    if kind is not None and not isinstance(raw, Body):
        return kind.from_data(raw)
    return raw


class Block:
    """所有内容类型的基类（也是未登记 ``type`` 的兜底裸块）。

    子类通过**重新描述字段**来定义领域结构，而不是加新顶层字段。字段两种写法等价：

        class Note(Block):
            type = "notedata"
            title: Attr[str] = ""            # 注解即类型，右边即值（自动包成字段）
            tags = Attr(factory=dict)        # 也可显式写描述符

            @classmethod
            def tables(cls):                 # 领域自描述的业务表（含关联表）
                return {"notes": {...}}

    注册：定义 ``type`` 的子类会自动进 ``_REGISTRY``（``__init_subclass__``），
    ``decode`` 据此还原成正确的子类。
    """

    type: str | Enum = "block"
    kind: str | Enum = "block"
    # 所属内核：**不写注解**——写了会被 `__init_subclass__` 当成字段包成描述符，
    # 赋值会落进 attrs、`block.core` 取不回来。它是运行期引用，不是数据字段。
    core = None
    body: Any = BodyField()
    _REGISTRY: ClassVar[dict[str, builtins.type[Block]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        declared = cls.__dict__.get("type")
        if declared is not None:
            Block._REGISTRY[_type_name(declared)] = cls
        if "kind" not in cls.__dict__:
            cls.kind = cls.type
        # 注解即类型、右边即值：把类体裸值自动包成字段描述符。
        for name, annotation in cls.__dict__.get("__annotations__", {}).items():  # noqa: RUF063
            value = cls.__dict__.get(name, _MISSING)
            if value is _MISSING:
                continue
            descriptor = _descriptor_for(annotation, value)
            if descriptor is None:
                continue
            descriptor.__set_name__(cls, name)
            setattr(cls, name, descriptor)
        if declared is not None:
            register(
                TypeInfo(
                    type=_type_name(cls.type),
                    role=ROLE_DATA,
                    cls=cls,
                    name=cls.__name__,
                    fields=collect_fields(cls),
                )
            )

    def __init__(  # noqa: PLR0913 — 块记录的扁平字段构造器，拆包反而更绕
        self,
        *,
        id: str | None = None,
        body: Any = _MISSING,
        attrs: dict[str, Any] | None = None,
        type: str | Enum | None = None,
        checksum: str | None = None,
        config: dict[str, Any] | None = None,
        author: str = "",
        created: int = 0,
        updated: int = 0,
        size: int = 0,
    ) -> None:
        self._id: str | None = None
        self.id = id if id is not None else str(ValueUuid.new())
        self.type = _type_name(type if type is not None else self.__class__.type)
        if body is not _MISSING:
            self.body = body
        self.attrs: dict[str, Any] = dict(attrs or {})
        self.checksum = checksum
        self.config: dict[str, Any] = dict(config or {})
        self.author = author
        self.created = created
        self.updated = updated
        self.size = size
        # 所属内核（由领域服务在创建时递进来，或 `Core.get` 载入时挂上）。
        # **不要在这里重置为 None**：子类若已带类级 `core`（领域服务给数据类设过），
        # 重置会把它抹掉，导致 `data.info` / `data.save()` 报"块未挂门户"。
        self._info: Any = None

    def validate(self) -> None:
        """写入前的校验；子类重写，非法即抛异常。默认放行。"""
        return

    # id 锁死：创建后不可改
    @property
    def id(self) -> str:
        if self._id is None:
            raise CairnError("块 id 未初始化")
        return self._id

    @id.setter
    def id(self, value: str) -> None:
        if self._id is not None and value != self._id:
            raise AttributeError("块 id 不可修改")
        self._id = value

    def body_hash(self) -> str:
        """**去重键**：只算 ``body``（不含 id / attrs / 签名 / 时间戳）。

        - 结构化 body（``Body`` 子类）**恒重算**，不信任字段 ``hash``。
        - 裸 body 直接按内容算。子类可覆写口径。

        ``body.hash`` 只是「上次 ``refresh()`` 的结果」：子类把内部容器暴露成属性后，
        就地改动（如 ``canvas.graphics.append(...)``）不会自动重算。去重键一旦与真实
        负载脱钩，``bucket.put`` 会命中旧内容池行、**不存新负载**（读回是旧内容），
        且 ``verify()`` 也会跟着报健康——故这里不接受缓存。
        """
        body = self.body
        if isinstance(body, Body):
            return body.refresh().hash
        return _digest(canonical(body))

    def compute_checksum(self) -> str:
        """块签名 = ``body_hash``；桶按它去重，``verify`` 也按它。"""
        return self.body_hash()

    def content_size(self) -> int:
        """主体字节数：bytes 取长度，其余取确定性编码长度。"""
        body = self.body
        if isinstance(body, (bytes, bytearray)):
            return len(body)
        if isinstance(body, Body):
            body = body.to_data()
        return len(canonical(body))

    def encode_body(self) -> bytes:
        """编码 body 为落盘字节（进桶的内容池，按 ``body_hash`` 去重）。"""
        body = self.body
        if isinstance(body, Body):
            body = body.to_data()
        return canonical(body)

    @classmethod
    def decode(
        cls,
        data: bytes,
        *,
        id: str | None = None,
        attrs: Any = None,
        type: str | None = None,
    ) -> Block:
        """由「body 字节 + attrs + type」还原为对应子类；未知类型退回基类。

        body 与 attrs 分开存（body 进内容池、attrs 随块行），这里拼合后按子类口径重算
        ``checksum``，保证读回与写入一致。
        """
        if id is None:
            raise CorruptObjectError("decode 需要块 id")
        try:
            raw = cbor2.loads(data) if data else None
        except (cbor2.CBORDecodeError, cbor2.CBOREncodeError) as exc:
            raise CorruptObjectError("块解析失败") from exc
        try:
            kind = _type_name(type if type is not None else cls.type)
            target = Block._REGISTRY.get(kind, Block)
            body = _body_from_data(target, raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise CorruptObjectError("块内容解析失败") from exc
        block = target(id=id, body=body, attrs=dict(attrs or {}), type=kind)
        try:
            block.checksum = block.compute_checksum()
        except cbor2.CBOREncodeError as exc:
            # 解出的 body 无法再编码（如损坏得到的 CBOR 特殊值）→ 视为损坏
            raise CorruptObjectError("块内容不可编码") from exc
        return block

    def verify(self) -> bool:
        """重算 checksum，校验内容未被篡改。"""
        return self.checksum == self.compute_checksum()

    @classmethod
    def new(cls) -> Block:
        """新建一个空对象，id 已分配。"""
        return cls()

    # ---- 挂门户之后的通用读写（save / delete / info）----
    # 领域结构直接继承本类，不再有中间层；这些方法对任何块都通用。
    @property
    def oid(self) -> str:
        """对象身份的字符串形态（与 `ObjectInfo.oid` 同名同义）。"""
        return str(ValueUuid.parse(self.id))

    @property
    def info(self) -> Any:
        """中立视图（``ObjectInfo``）；未挂门户时**按需向门户取**。"""
        if self._info is None:
            if self.core is None:
                raise CairnError("块未挂门户：请用 Core.load / attach")
            self._info = self.core.info(self.id)
        return self._info

    # title / tags / authors 等业务字段**不属于块**：由各领域用 ``Attr`` 自行声明
    # （见 ``domains/base.py`` 的 ``normalize_tags`` 与各领域类）。

    def meta(self) -> dict[str, Any]:
        return dict(self.attrs)

    def props(self) -> dict[str, Any]:
        return dict(self.attrs.get("props") or {})

    def read(self) -> bytes:
        """裸 body 的字节视图；结构化 body 请走 ``encode_body()``。

        只认 bytes 一族：``Body`` 子类有自己的落盘编码，盲调 ``bytes(body)`` 会对
        list body 返回无意义字节、对 ``Body`` 抛不透明错误，故这里一律 fail loud。
        """
        body = self.body
        if isinstance(body, bytes):
            return body
        if isinstance(body, (bytearray, memoryview)):
            return bytes(body)
        if isinstance(body, Body):
            raise TypeError("结构化 body 无字节视图，请用 encode_body()")
        raise TypeError(f"body 不是字节：{type(body).__name__}")

    # ---- 门户（归属显式：字段名就叫 ``core``，不再是私藏引用）----
    def attach(self, portal: Any) -> Self:
        """把对象挂到门户：此后 ``save / delete / info`` 都经它。

        **落盘是显式动作**：领域更推荐直接 ``core.put(data)``；``save()`` 是便捷写法。
        """
        self.core = portal
        return self

    @property
    def attached(self) -> bool:
        """是否已挂门户（未挂的裸对象只能被存储层收下）。"""
        return self.core is not None

    def detach(self) -> Self:
        """摘掉门户归属（变回纯值对象）。"""
        self.core = None
        self._info = None
        return self

    def save(self) -> Self:
        """经门户落盘（**纯落盘**；版本由领域服务负责）。需先挂门户。"""
        portal = self._portal()
        portal.put(self)
        self.sync_info(portal)
        return self

    def delete(self) -> None:
        """经门户删除自身（门户的删除口是 `Core.drop`）。需先挂门户。"""
        self._portal().drop(self.id)

    def sync_info(self, portal: Any = None) -> Self:
        """刷新自身的中立视图（``info``）：``portal`` 缺省用已挂的门户。"""
        source = portal if portal is not None else self._portal()
        self._info = source.info(self.id)
        return self

    def _portal(self) -> Any:
        if self.core is None:
            raise CairnError("块未挂门户：请用 Core.load / attach")
        return self.core

    @classmethod
    def load(cls, portal: Any, oid: str) -> Self:
        """经门户载入对象并挂接（``portal`` 是 `Core`）。"""
        block: Self = portal.storage.get(cls, str(oid))
        block.attach(portal)
        block._info = portal.info(block.id)
        return block

    @classmethod
    def list(
        cls,
        portal: Any,
        *,
        tags: Iterable[str] | None = None,
    ) -> Iterator[Self]:
        """经门户遍历同类型对象。"""
        for info in portal.iter(type=cls.type, tags=tags):
            yield cls.load(portal, info.oid)


register(
    TypeInfo(
        type=_type_name(Block.type),
        role=ROLE_DATA,
        cls=Block,
        name="Block",
        fields=collect_fields(Block),
    )
)


__all__ = [
    "INDEX_TYPE",
    "PART_TYPE",
    "Attr",
    "Block",
    "Body",
    "canonical",
    "decode_canonical",
]

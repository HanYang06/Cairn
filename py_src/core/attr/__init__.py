# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""属性声明：块上的字段怎么被认出来、怎么判类型。

用法是**在 ``__init__`` 里声明**——声明与构造写在一处：

    class NoteData(Block):
        def __init__(self) -> None:
            super().__init__()
            self.title = attr(default="")
            self.tags = attr(factory=list[str])

**声明在哪儿发生，形状就在哪儿定**：块基座在子类构造跑完之后扫一遍实例，把这些声明收成
类型形状（见 `core/storage/format/block.py`），并把标记**换成真实默认值**——
故构造出来的实例上 ``note.title`` 就是 ``str``，不是声明对象。

**类型上返回的是默认值的类型**：``attr(default="")`` 在 mypy 眼里就是 ``str``。
故这里不需要 mypy 插件，也不需要类体注解（类体注解在 ``__init__`` 里本来就会被丢掉）。

**类型判据与 ``conf`` 共用一套**（`core.conf.types`）：不为属性另立一套类型词汇，
于是不会出现「配置放行、属性拦下」这种两边各写一套才会有的矛盾。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast, overload

from core.conf.types import MISSING, TypeSpec, check_type, spec_of
from core.exc import AttrTypeError, ConfigTypeError

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["AttrDecl", "attr", "attr_decl", "check_type"]


def _copy_default(value: object, spec: TypeSpec) -> object:
    """把默认值取一份：容器现拷，标量原样（标量不可变，拷不拷都一样）。

    不拷的话，``attr(default=[])`` 造出来的两个实例会共用同一个列表——
    这类错误在内容寻址的底座上会变成"改一篇笔记，别篇跟着变"。
    """
    if spec.scalar is list:
        return list(cast("list[Any]", value))
    if spec.scalar is dict:
        return dict(cast("dict[str, Any]", value))
    return value


@dataclass(frozen=True, slots=True)
class AttrDecl:
    """一条属性声明：类型判据、缺省值出处、要不要进速查。

    ``default`` 与 ``factory`` 只有一个为真：给工厂的场合（``factory=list[str]``）每次现造
    一个新值；给字面默认值的场合每次拷一份。两条路都保证实例之间不串。

    Attributes:
        spec: 类型判据（与 `conf` 共用一套）。
        default: 字面缺省值；写工厂时是 ``None``。
        factory: 缺省值的工厂；写字面值时是 ``None``。
        indexed: 这个属性要不要进速查倒排。只收标量——容器值不可哈希。
        doc: 说明文本。
    """

    spec: TypeSpec
    default: object = None
    factory: Callable[[], object] | None = None
    indexed: bool = False
    doc: str = ""

    def make(self) -> object:
        """造一个缺省值：有工厂就现调一次，否则把字面值拷一份。"""
        if self.factory is not None:
            return self.factory()
        return _copy_default(self.default, self.spec)


@overload
def attr[T](*, default: T, type: object = ..., indexed: bool = ..., doc: str = ...) -> T: ...


@overload
def attr[T](
    *, factory: Callable[[], T], type: object = ..., indexed: bool = ..., doc: str = ...
) -> T: ...


def attr(
    *,
    default: object = MISSING,
    factory: Callable[[], object] | None = None,
    type: object = MISSING,
    indexed: bool = False,
    doc: str = "",
) -> object:
    """声明一条属性。**类型上返回缺省值的类型，运行时返回 :class:`AttrDecl`。**

    Args:
        default: 字面缺省值；类型按它自己的类型判（``""`` → `str`，``False`` → `bool`）。
        factory: 缺省值的工厂；类型按工厂推（``list[str]`` → ``list[str]``），推不出即要求
            显式给 `type=`。
        type: 显式类型；给了就以它为准（`conf` 的那套词表）。
        indexed: 要不要进速查倒排。
        doc: 说明文本。

    Raises:
        AttrTypeError: 缺省值给重了、一个都没给，或类型不在词表里。
    """
    if default is MISSING and factory is None:
        raise AttrTypeError("属性声明要给出缺省值：`attr(default=…)` 或 `attr(factory=…)`")
    if default is not MISSING and factory is not None:
        raise AttrTypeError("属性声明的缺省值只能给一个出处：default 或 factory")
    spec = _spec_of_decl(default, factory, type)
    try:
        plain = MISSING if default is MISSING else check_type(cast("Any", default), spec)
    except ConfigTypeError as error:
        raise AttrTypeError(f"属性的缺省值与声明的类型不符: {error}") from error
    return AttrDecl(
        spec=spec,
        default=None if plain is MISSING else plain,
        factory=factory,
        indexed=indexed,
        doc=doc,
    )


def _spec_of_decl(
    default: object, factory: Callable[[], object] | None, declared: object
) -> TypeSpec:
    """一条声明的类型判据从哪儿来：显式给的 > 默认值自身的类型 > 工厂本身。"""
    if declared is not MISSING:
        try:
            return spec_of(declared)
        except ConfigTypeError as error:
            raise AttrTypeError(f"属性的类型不在词表里: {error}") from error
    if default is not MISSING:
        try:
            return spec_of(type(default))
        except ConfigTypeError as error:
            raise AttrTypeError(f"属性的类型不在词表里: {error}") from error
    if factory is None:  # 调用点已保证二者必有其一；这一句只让类型收窄
        raise AttrTypeError("属性声明要给出缺省值：`attr(default=…)` 或 `attr(factory=…)`")
    try:
        return spec_of(factory)
    except ConfigTypeError as error:
        raise AttrTypeError(
            f"属性的工厂 {factory!r} 推不出类型，请显式给 `type=`（{error}）"
        ) from error


def attr_decl(value: object) -> AttrDecl | None:
    """这个值是不是一条属性声明；不是即 ``None``（那它就是普通实例状态）。"""
    return value if isinstance(value, AttrDecl) else None

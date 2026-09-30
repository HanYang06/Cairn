# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""属性声明：块上的字段怎么被认出来、怎么判类型。

用法就一句：``from core.attr import attr``，然后在一个块的类体里标注字段——

    class NoteData(Block[NoteBody]):
        title: attr[str] = ""                    # 简单形式：右边就是真实默认值
        tags: attr[dict] = field(default_factory=dict)

**`attr` 与 `conf` 同族**：都是「声明即事实」的全小写入口，全局可用、不限定在哪一层。
两者的分别只在落点——``conf`` 的值落进单份值文件，``attr`` 标注的字段**跟着块走**
（进块记录的载荷），数据库那边最多只是它的索引。

**类型判据与 ``conf`` 共用一套**（:mod:`core.conf.types`）：类型词表、校验函数都是同一条。
于是「属性是配置」这件事在代码上成立——不需要为属性另立一套类型词汇，
也就不会出现「配置放行、属性拦下」这种两边各写一套才会有的矛盾。

**复杂形式（右边写 ``attr(...)``）尚未实现**：那要引入哨兵与运行时包装，而简单形式
已经够用——需要工厂默认值时用 ``dataclasses.field``，需要值变换时在领域侧做。
"""

from __future__ import annotations

from typing import get_args, get_origin

from core.conf.types import TypeSpec, check_type, spec_of
from core.exc import AttrTypeError

__all__ = ["TypeSpec", "attr", "attr_type_of", "check_type"]


class attr[T]:  # noqa: N801 — 与 `conf` 同族的全小写入口，作者定（见 `pyproject.toml` 豁免）
    """属性声明：把块上的一个字段标成**可落盘、可校验**的属性。

    它只借类型实参：``title: attr[str]``。故这个类**不实例化**，右侧写的是真实默认值，
    字段取出来就是那个值——不存在「声明对象与默认值混在一起」的情形，也不必在
    ``__init_subclass__`` 里把裸值再包一层。

    类型实参就是这条属性的判据，收的是 ``conf`` 那套：``int`` / ``float`` / ``bool`` /
    ``str`` / ``list`` / ``dict``（可带一层元素）与 ``None``。
    """

    __slots__ = ()


def attr_type_of(hint: object) -> TypeSpec | None:
    """一个注解是不是属性声明：是则给出它的类型判据，不是即 ``None``。

    判据是**注解的形状**：``attr[...]`` 是声明（取它的类型实参），别的都不是。
    故 ``title: str`` 与 ``tags: dict[str, str]`` 这种裸注解不会被误当成属性——
    它们既没有声明，内核也就没有理由替它们落盘。

    Args:
        hint: 类上某一项的注解（已解析成真实对象）。

    Raises:
        AttrTypeError: 写了 ``attr`` 却没写类型实参（``attr`` 本身），或实参不在类型词表里。
    """
    if hint is attr:
        raise AttrTypeError("属性声明要写类型实参，如 `attr[str]`")
    if get_origin(hint) is not attr:
        return None
    arguments = get_args(hint)
    try:
        return spec_of(arguments[0])
    except ValueError as error:
        raise AttrTypeError(f"属性的类型 {arguments[0]!r} 不在词表里: {error}") from error

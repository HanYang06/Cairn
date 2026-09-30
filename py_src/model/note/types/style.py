# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""样式：CSS 属性名 → CSS 值的 KV。

两个作用域，**不得混**：

- :class:`NoteStyle` 是**笔记级**，管整篇长什么样（背景一类），塞在正文里；
- :class:`SpanStyle` 是**行内**，管一段文字的观感，它是 :class:`Span` 的元素。

键名与取值**照抄行业**：键用 CSS 的文本属性名（``font-weight`` / ``color`` / …），
值用 CSS 的值。于是"命名值"不必另发明语法——**CSS 的 ``var(--color-…)`` 本身就是令牌引用**，
这套 KV 到前端近乎直通，不另设翻译层。

只存**非默认值**（空值等于不写），并把键按名排序：于是同一份逻辑样式编出的字节唯一，
而"同一事实只有一种写法"正是内容地址稳定的前提。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Self

__all__ = ["NoteStyle", "SpanStyle"]


def _canonical(values: Mapping[str, str] | None) -> tuple[tuple[str, str], ...]:
    """把一份 KV 收成规范形态：丢掉空值，按属性名排序。"""
    if not values:
        return ()
    return tuple(sorted((name, value) for name, value in values.items() if value))


@dataclass(frozen=True, slots=True)
class _StyleKV:
    """样式 KV 的共同形态。

    **不对外**：两个作用域各是一个具体类型，共用形态只为不把"丢空值 + 排序"抄两遍。
    两种类型的实例互不相等（dataclass 的比较要求同类），故不存在"改错了那一份"的余地。
    """

    values: tuple[tuple[str, str], ...] = ()

    @classmethod
    def of(cls, values: Mapping[str, str] | None = None) -> Self:
        """由一份 KV 造样式：键序与空值都被规范化。

        Args:
            values: 属性名 → 值；不给或给空映射都得到空样式。

        Returns:
            规范化之后的样式。
        """
        return cls(_canonical(values))

    def __bool__(self) -> bool:
        """有没有写任何属性。空样式的意思就是"这里没有样式"。"""
        return bool(self.values)


@dataclass(frozen=True, slots=True)
class SpanStyle(_StyleKV):
    """**行内**样式：一段文字的观感。"""


@dataclass(frozen=True, slots=True)
class NoteStyle(_StyleKV):
    """**笔记级**样式：整篇的观感（背景一类）。"""

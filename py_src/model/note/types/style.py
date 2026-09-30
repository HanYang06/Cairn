# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""行内样式：CSS 属性名 → CSS 值的 KV。

键名与取值**照抄行业**：键用 CSS 的文本属性名（``font-weight`` / ``color`` / …），
值用 CSS 的值。于是"命名值"不必另发明语法——**CSS 的 ``var(--color-…)`` 本身就是令牌引用**，
这套 KV 到前端近乎直通，不另设翻译层。

只存**非默认值**（空值等于不写），并把键按名排序，故同一份逻辑样式编出的字节唯一。

**笔记级样式不在这里**：它是 :class:`~model.note.types.note.NoteData` 上的一个**属性**
（纯 KV），因为它**不进正文**——写进正文就等于"改一次背景把整篇重存一遍"，
而正文是按内容地址去重的。行内的这一份则跟着行走，两者作用域不同，也不共用类型。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Self

__all__ = ["SpanStyle"]


def _canonical(values: Mapping[str, str] | None) -> tuple[tuple[str, str], ...]:
    """把一份 KV 收成规范形态：丢掉空值，按属性名排序。"""
    if not values:
        return ()
    return tuple(sorted((name, value) for name, value in values.items() if value))


@dataclass(frozen=True, slots=True)
class SpanStyle:
    """**行内**样式：一段文字的观感。它是 `Span` 的元素。"""

    values: tuple[tuple[str, str], ...] = ()

    @classmethod
    def of(cls, values: Mapping[str, str] | None = None) -> Self:
        """由一份 KV 造行内样式：键序与空值都被规范化。

        Args:
            values: 属性名 → 值；不给或给空映射都得到空样式。

        Returns:
            规范化之后的样式。
        """
        return cls(_canonical(values))

    def __bool__(self) -> bool:
        """有没有写任何属性。空样式的意思就是"这里没有样式"。"""
        return bool(self.values)

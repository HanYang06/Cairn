# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""笔记的数据结构：值对象与行载荷。

这一层只放**形状**，不放算法（算法在 ``engine/``、编解码在 ``format/``）。
这里的东西全都不登记、不建表：它们是 ``NoteData`` 载荷内部的结构，
随载荷一起落盘、一起重建，内核不需要认识它们。
"""

from __future__ import annotations

from model.note.types.body import NoteBody
from model.note.types.kinds import REFERENCE_TABLES, LineKind, reference_table
from model.note.types.line import (
    Code,
    Heading,
    LineData,
    Link,
    ListItem,
    NoteLine,
    Ref,
    Span,
    Todo,
)
from model.note.types.style import NoteStyle, SpanStyle

__all__ = [
    "REFERENCE_TABLES",
    "Code",
    "Heading",
    "LineData",
    "LineKind",
    "Link",
    "ListItem",
    "NoteBody",
    "NoteLine",
    "NoteStyle",
    "Ref",
    "Span",
    "SpanStyle",
    "Todo",
    "reference_table",
]

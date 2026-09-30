# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""笔记的数据结构：值对象与落盘载体。

这一层只放**形状**，不放算法（算法在 ``engine/``、编解码在 ``format/``）。
前半是值对象——它们不登记、不建表，只活在各自载体的载荷内部，随载荷一起重建；
后半是**继承 ``Block`` 的落盘载体**——它们**一写就登记、开库即建表**，
故本模块被 import 的那一刻，``notedata`` / ``notetag`` / ``notegroup`` /
``noteasset`` / ``notediff`` / ``notecanvas`` 几张表就进了登记表。
"""

from __future__ import annotations

from model.note.types.asset import Chunk, NoteAsset, NoteAssetBody
from model.note.types.body import NoteBody
from model.note.types.canvas import CanvasLink, Figure, NoteCanvas, NoteCanvasBody, PlacedShape
from model.note.types.diff import DiffStep, NoteDiff, NoteDiffBody
from model.note.types.group import NoteGroup, NoteGroupBody
from model.note.types.kinds import REFERENCE_TABLES, LineKind, reference_table
from model.note.types.line import (
    Code,
    Heading,
    LineContent,
    LineData,
    Link,
    ListItem,
    NoteLine,
    Ref,
    Span,
    Todo,
)
from model.note.types.note import NoteData
from model.note.types.style import SpanStyle
from model.note.types.tag import NoteTag, NoteTagTable

__all__ = [
    "REFERENCE_TABLES",
    "CanvasLink",
    "Chunk",
    "Code",
    "DiffStep",
    "Figure",
    "Heading",
    "LineContent",
    "LineData",
    "LineKind",
    "Link",
    "ListItem",
    "NoteAsset",
    "NoteAssetBody",
    "NoteBody",
    "NoteCanvas",
    "NoteCanvasBody",
    "NoteData",
    "NoteDiff",
    "NoteDiffBody",
    "NoteGroup",
    "NoteGroupBody",
    "NoteLine",
    "NoteTag",
    "NoteTagTable",
    "PlacedShape",
    "Ref",
    "Span",
    "SpanStyle",
    "Todo",
    "reference_table",
]

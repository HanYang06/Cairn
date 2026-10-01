# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""笔记的数据结构：载荷内的结构与落盘载体。

这一层只放**形状**，不放算法（算法在 `engine/`、编解码在 `format/`）。

两种东西，一条写法——**继承 ``Block``、在 ``__init__`` 里声明字段**：

- **载体**（``NoteData`` / ``NoteTag`` / ``NoteGroup`` / ``NoteAsset`` / ``NoteCanvas``）：
  声明里有 ``self.id = ID()``，故**有表**，可单独落盘与查询；
- **载荷内的结构**（``NoteLine`` / ``Span`` / ``Heading`` / ``Chunk`` / ``Figure`` …）：
  没有 ID，故**不登记、不建表**，只活在各自载体的载荷里，随载荷一起重建。

容器选型有一条规矩：**变长的用列表**（行、区间、分片、图），**定长的用元组**
（`(start, end, style)`、`(操作, 坐标)`）；结构整体**默认不冻结**——
盘上是追加写、旧字节不动，内存里冻结换不来好处，只会逼着每次编辑整份复制。

**变更记录（diff）不在这一层**：它整体**推迟成预留**，等真有调用方再设计（见 `progress.md`）。
"""

from __future__ import annotations

from model.note.types.asset import Chunk, NoteAsset
from model.note.types.canvas import CanvasLink, Figure, NoteCanvas, PlacedShape
from model.note.types.group import NoteGroup
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
from model.note.types.note import NoteData
from model.note.types.tag import NoteTag

__all__ = [
    "REFERENCE_TABLES",
    "CanvasLink",
    "Chunk",
    "Code",
    "Figure",
    "Heading",
    "LineData",
    "LineKind",
    "Link",
    "ListItem",
    "NoteAsset",
    "NoteCanvas",
    "NoteData",
    "NoteGroup",
    "NoteLine",
    "NoteTag",
    "PlacedShape",
    "Ref",
    "Span",
    "Todo",
    "reference_table",
]

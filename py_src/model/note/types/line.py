# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""一行笔记：载荷的判别联合与行内区间。

行取**单字段形式**：``(id, kind, data, spans)``。

- ``id``：行身份，**稳定**——行增删与重排都不动它，故样式与版本不会因下标漂移而错位；
- ``kind``：:class:`LineKind`，只回答"这一行是什么"，同时是 ``data`` 的**判别位**；
- ``data``：随 ``kind`` 而定（判别联合）——内容类装文字，引用类装 ID 串；
- ``spans``：行内样式区间，按起点有序；没有行内样式的行留空。

**行不是块**：它不登记、不建表、没有自己那张 ID 表，只活在 ``NoteData`` 的载荷里。
同族的先例是 ``BodyRef`` / ``BlockPayload`` / ``Tombstone``：都是载荷内的值对象。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

from core.storage.format.id import new_uuid
from model.note.exc import LineShapeError, SpanRangeError
from model.note.types.kinds import LineKind
from model.note.types.style import SpanStyle

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "Code",
    "Heading",
    "LineData",
    "Link",
    "ListItem",
    "NoteLine",
    "Ref",
    "Span",
    "Todo",
]


@dataclass(frozen=True, slots=True)
class Heading:
    """文本内标题：文字 + 级别。**级别缺省即最高一级**，第 1 级不写进载荷。"""

    text: str = ""
    level: int = 1


@dataclass(frozen=True, slots=True)
class ListItem:
    """列表项：文字 + 层级 + 有序无序。"""

    text: str = ""
    level: int = 1
    ordered: bool = False


@dataclass(frozen=True, slots=True)
class Code:
    """代码行：文字 + 语言（语言可为空，即"没标"）。"""

    text: str = ""
    language: str = ""


@dataclass(frozen=True, slots=True)
class Todo:
    """待办行：文字 + 勾选状态。

    行内的待办**就是这一行**，与"整篇一个待办状态"（`NoteData` 的属性）是两回事。
    """

    text: str = ""
    done: bool = False


@dataclass(frozen=True, slots=True)
class Link:
    """链接行：目标 + 可选的显示文字。

    目标是**两可**的——站内笔记的 ID，或站外地址；故它不进 ``REFERENCE_TABLES``，
    由这条载荷自己说清是哪一种。
    """

    target: str = ""
    label: str = ""


@dataclass(frozen=True, slots=True)
class Ref:
    """引用行的载荷：一串 ID。

    **落点表由 :func:`~model.note.types.kinds.reference_table` 给出**，不由本类型自带——
    否则同一个"查哪张表"的事实会写成两处。资产行可能装多个 ID；画板与嵌入笔记只装一个。
    """

    ids: tuple[str, ...] = ()


type LineData = str | Heading | ListItem | Code | Todo | Link | Ref
"""``NoteLine.data`` 的值域：内容类是文字，引用类是 ID。"""

#: 每种行类型的 ``data`` 该是什么——判别联合的判据，一处定义。
_DATA_TYPES: Mapping[LineKind, type[object]] = MappingProxyType(
    {
        LineKind.TEXT: str,
        LineKind.HEADING: Heading,
        LineKind.LIST: ListItem,
        LineKind.CODE: Code,
        LineKind.TODO: Todo,
        LineKind.LINK: Link,
        LineKind.ASSET: Ref,
        LineKind.CANVAS: Ref,
        LineKind.NOTE: Ref,
    }
)


@dataclass(frozen=True, slots=True)
class Span:
    """行内样式区间：半开区间 ``[start, end)``，落在行内**字符**偏移上。

    偏移是位置、不是身份：行内改一个字，其后的区间都要重算——**只重算这一行**，
    行级的稳定由行 id 保证。区间允许重叠（后写覆盖前写），归并成规范形态是引擎的活。
    """

    start: int
    end: int
    style: SpanStyle = field(default_factory=SpanStyle)

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise SpanRangeError(f"行内区间非法: [{self.start}, {self.end})")


@dataclass(frozen=True, slots=True)
class NoteLine:
    """一行：身份 + 类型 + 载荷 + 行内样式区间。"""

    id: str = field(default_factory=new_uuid)
    kind: LineKind = LineKind.TEXT
    data: LineData = ""
    spans: tuple[Span, ...] = ()

    def __post_init__(self) -> None:
        expected = _DATA_TYPES[self.kind]
        if not isinstance(self.data, expected):
            raise LineShapeError(
                f"行类型 {self.kind.value} 的载荷应是 {expected.__name__}，"
                f"而给的是 {type(self.data).__name__}: {self.data!r}"
            )

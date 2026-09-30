# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""一行笔记：载荷的判别联合与行内区间。

行条目取**单字段形式**：``(id, kind, data, spans)``。

- ``id``：行身份，**稳定**——行增删与重排都不动它，故样式与版本不会因下标漂移而错位；
- ``kind``：:class:`LineKind`，只回答"这一行是什么"，同时是 ``data`` 的**判别位**；
- ``data``：随 ``kind`` 而定（判别联合）——内容类装文字，引用类装 ID 串；
- ``spans``：行内样式区间，按起点有序；没有行内样式的行留空。

**行不是块**：它不登记、不建表、没有自己那张 ID 表，只活在 ``NoteData`` 的载荷里。

**这里一律用可变容器（列表）**：行与区间都会被就地增删改，而盘上那条记录是追加写的、
旧字节一个都不动——内存里"冻结"既换不来盘上的好处，又逼着每次编辑整份复制一遍。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

from core.storage.format.id import new_uuid
from model.note.exc import LineShapeError, SpanRangeError
from model.note.types.kinds import LineKind

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


@dataclass(slots=True)
class Heading:
    """文本内标题：文字 + 级别。**级别缺省即最高一级**，第 1 级不写进载荷。"""

    text: str = ""
    level: int = 1


@dataclass(slots=True)
class ListItem:
    """列表项：文字 + 层级 + 有序无序。"""

    text: str = ""
    level: int = 1
    ordered: bool = False


@dataclass(slots=True)
class Code:
    """代码行：文字 + 语言（语言可为空，即"没标"）。"""

    text: str = ""
    language: str = ""


@dataclass(slots=True)
class Todo:
    """待办行：文字 + 勾选状态。

    行内的待办**就是这一行**，与"整篇一个待办状态"（`NoteData` 的属性）是两回事。
    """

    text: str = ""
    done: bool = False


@dataclass(slots=True)
class Link:
    """链接行：目标 + 可选的显示文字。

    目标是**两可**的——站内笔记的 ID，或站外地址；故它不进 ``REFERENCE_TABLES``，
    由这条载荷自己说清是哪一种。
    """

    target: str = ""
    label: str = ""


@dataclass(slots=True)
class Ref:
    """引用行的载荷：一串 ID。

    **落点表由 :func:`~model.note.types.kinds.reference_table` 给出**，不由本类型自带——
    否则同一个"查哪张表"的事实会写成两处。资产行可能装多个 ID；画板与嵌入笔记只装一个。
    """

    ids: list[str] = field(default_factory=list)


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


def _check_shape(kind: LineKind, data: LineData) -> None:
    """载荷与行类型必须配套：读 `data` 之前要按 `kind` 分支，判据不能破。"""
    expected = _DATA_TYPES[kind]
    if not isinstance(data, expected):
        raise LineShapeError(
            f"行类型 {kind.value} 的载荷应是 {expected.__name__}，"
            f"而给的是 {type(data).__name__}: {data!r}"
        )


@dataclass(slots=True)
class Span:
    """行内样式区间：半开区间 ``[start, end)``，落在行内**字符**偏移上。

    偏移是位置、不是身份：行内改一个字，其后的区间都要重算——**只重算这一行**，
    行级的稳定由行 id 保证。区间允许重叠（后写覆盖前写），归并成规范形态是引擎的活。

    样式是一份 KV（CSS 属性名 → CSS 值），**只存非默认值**；键序与去默认归编码那一侧。
    """

    start: int
    end: int
    style: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise SpanRangeError(f"行内区间非法: [{self.start}, {self.end})")


@dataclass(slots=True)
class NoteLine:
    """一行：身份 + 类型 + 载荷 + 行内区间。

    内容那三样原样摊在本类上（``kind`` / ``data`` / ``spans``），不另嵌一层：
    行是编辑与编码的最小单位，多一层包装只让读写绕路。
    """

    id: str = field(default_factory=new_uuid)
    kind: LineKind = LineKind.TEXT
    data: LineData = ""
    spans: list[Span] = field(default_factory=list)

    def __post_init__(self) -> None:
        _check_shape(self.kind, self.data)

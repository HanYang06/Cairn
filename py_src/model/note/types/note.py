# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""笔记的载体：``NoteData``。

创建一篇笔记，落的是**这个数据结构**：正文是**载荷**（进内容记录、按内容地址去重），
标题一类小字段是**属性**（跟着块记录走），两者各归各的落点，故改一次标题不会把整篇重存。

**声明写在类体上**：注解是字段类型（给 mypy 看），右值是落点声明（``Attr`` / ``Body``）。
容器默认值由描述符在**实例第一次取值时现拷一份**，故类体上写 ``Attr({})`` / ``Attr([])``
不会串实例。

**时间是自己的字段，不借 ``birth_time``**：``birth_time`` 是**身份**被签发的时刻——
它说的是"这个身份什么时候生的"，而 ``created`` / ``updated`` 说的是**这篇笔记**什么时候写下、
什么时候改过；一次保存只换载荷摘要、不动签发时刻，两者因此不会重合。
它们只在块**自签身份**那一刻盖上创建值；身份由调用方递进来时一律照用，不覆盖读回来的值。

**现状与缺口**：``lines`` 里装的是 `NoteLine` 对象，而 ``cbor2`` 编不出 dataclass，
故本文件目前只保证空 ``lines`` 的往返。把行结构规范化成字节的那一层是
``py_src/model/note/format/``，**尚未实现**。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.clock import now_ms
from core.storage.engine import Block
from core.storage.types import Attr, Body

if TYPE_CHECKING:
    from core.storage.db.id import ID
    from model.note.types.line import NoteLine

__all__ = ["NoteData"]


class NoteData(Block):
    """一篇笔记。

    字段按落点分两拨：``lines`` 是**载荷**（大头内容、按内容地址去重），
    其余是**属性**（跟着块记录走）。``id`` 是身份——**有它才有这张表**。

    表名不写：它只由类名算出来（``NoteData`` → ``notedata``）；领域专属的类型以域名开头，
    于是 ``project`` 那边可以做出同名概念而互不相干，两张表也不会撞。
    """

    # 注：注解写字段的类型，右值是落点声明（描述符）；实例上取到的是裸值。
    title: str = Attr("")  # type: ignore[assignment]
    subtitle: str = Attr("")  # type: ignore[assignment]
    style: dict[str, str] = Attr({})  # type: ignore[assignment]
    tags: list[str] = Attr([])  # type: ignore[assignment]
    created: int = Attr(0)  # type: ignore[assignment]
    updated: int = Attr(0)  # type: ignore[assignment]
    todo: bool = Attr(False)  # type: ignore[assignment]
    lines: list[NoteLine] = Body([])  # type: ignore[assignment]

    def __init__(self, id: ID | None = None) -> None:
        """身份可省：省了就是块自己现签一个，并一并盖上创建时刻。

        落点不在这里写：字段进哪个记录由**类体上的声明**定，与这一次构造无关。
        """
        fresh = id is None
        super().__init__(id)
        if fresh:
            self.created = now_ms()
            self.updated = self.created

    def __len__(self) -> int:
        """有多少行。"""
        return len(self.lines)

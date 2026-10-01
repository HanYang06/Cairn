# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""笔记的载体：``NoteData``。

创建一篇笔记，落的是**这个数据结构**：正文是**载荷**（进 body 记录、按内容地址去重），
标题一类小字段是**属性**（跟着块记录走），两者各归各的落点，故改一次标题不会把整篇重存。

**时间是两个，且都不能拿 ``birth_time`` 顶**：``birth_time`` 是 ID 被签发的时刻，
而每存一次都会新签一个——**每存一次它就换一个**，当不了"创建时间"。
"""

from __future__ import annotations

from core.attr import attr
from core.clock import now_ms
from core.storage.format.block import Block, Body
from core.storage.format.id import ID
from model.note.types.line import NoteLine

__all__ = ["NoteData"]


class NoteData(Block):
    """一篇笔记。

    字段按落点分两拨：``lines`` 是**载荷**（大头内容、按内容地址去重），
    其余是**属性**（跟着块记录走）。``id`` 是身份——**有它才有这张表**。

    ``__table__`` 不写：默认取类名的小写写法（``notedata``）；领域专属的类型以域名开头，
    于是 ``project`` 那边可以做出同名概念而互不相干，两张表也不会撞。
    """

    def __init__(self) -> None:
        """声明字段。**形状在这一刻定下**，故这里不许依赖运行期条件。"""
        super().__init__()
        self.id = ID()
        self.title = attr(default="")
        self.subtitle = attr(default="")
        self.style = attr(factory=dict[str, str])
        self.tags = attr(factory=list[str])
        self.created = attr(factory=now_ms, type=int)
        self.updated = attr(factory=now_ms, type=int)
        self.todo = attr(default=False)
        self.lines = Body(factory=list[NoteLine])

    def __len__(self) -> int:
        """有多少行。"""
        return len(self.lines)

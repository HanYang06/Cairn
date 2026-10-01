# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""分组：**一个组一个块**，组里嵌组靠引用。

淘汰掉的那一版是"整个组体系一个块"（KV 里既装成员又装子组）：它与"一篇笔记一条 diff"
否掉的是同一种形态——**一个对象装下整棵体系，丢了就是全丢**；而且单块会无界增长，
早晚撞上体积上限。故取一个组一个块，成员与子组都以 ID 出现。

**不设递归深度上限**（叠得深是用户自己的事），但遍历必须**迭代**而非递归：
不设上限可以，"用户叠得深"不该变成"程序爆栈"。
"""

from __future__ import annotations

from core.attr import attr
from core.storage.format.block import Block, Body
from core.storage.format.id import ID

__all__ = ["NoteGroup"]


class NoteGroup(Block):
    """一个组。

    名字走 ``title``：``ID`` 自己已经有一个 ``name`` 字段（可读名称），
    组的名字再用 ``name`` 就是同名两义，故不取。
    """

    def __init__(self) -> None:
        """声明字段。成员与子组都是**载荷**：顺序即用户摆的顺序，是内容的一部分。"""
        super().__init__()
        self.id = ID()
        self.title = attr(default="")
        self.collapsed = attr(default=False)
        self.notes = Body(factory=list[str])
        self.groups = Body(factory=list[str])

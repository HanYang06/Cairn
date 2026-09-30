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

from dataclasses import dataclass, field

from core.attr import attr
from core.storage.format.block import Block

__all__ = ["NoteGroup", "NoteGroupBody"]


@dataclass(slots=True)
class NoteGroupBody:
    """组的载荷：成员笔记 ID + 子组 ID。

    两张表都只装 ID；顺序即用户摆的顺序，故是个**列表**、不排序（顺序是内容的一部分）。
    """

    notes: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)


@dataclass(slots=True)
class NoteGroup(Block[NoteGroupBody]):
    """一个组。

    ``title`` 是组的名字：**不叫 `name`**——`name` 是 ID 的可绑字段，写成 `attr[str]`
    会被登记成身份列而不是属性（`register_type` 先看字段名是不是 ID 字段）。
    """

    __table__ = "notegroup"
    __owner__ = "note"

    title: attr[str] = ""
    """组的名字。"""

    collapsed: attr[bool] = False
    """界面上收起来没有；它是**视图偏好**，故只是一个跟着块走的小字段。"""

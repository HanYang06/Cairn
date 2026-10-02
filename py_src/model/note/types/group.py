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

from core.storage.engine import Block
from core.storage.types import Attr, Body

__all__ = ["NoteGroup"]


class NoteGroup(Block):
    """一个组。

    名字走 ``title``：``ID`` 自己已经有一个 ``name`` 字段（可读名称），
    组的名字再用 ``name`` 就是同名两义，故不取。

    表名只由类名算出来（``NoteGroup`` → ``notegroup``），故本类不写 ``__init__``：
    基座那一支收下身份，不给就现签一个。
    """

    title: str = Attr("")  # type: ignore[assignment]
    collapsed: bool = Attr(False)  # type: ignore[assignment]
    notes: list[str] = Body([])  # type: ignore[assignment]
    groups: list[str] = Body([])  # type: ignore[assignment]

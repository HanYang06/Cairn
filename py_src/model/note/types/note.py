# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""笔记的载体：``NoteData``。

创建一篇笔记，落的是**这个 Block 子对象**（不是"笔记"这个概念本身）：正文在 ``body`` 里、
按内容地址去重；描述性的小字段跟着块走，进块记录的载荷。

**时间是两个，且都不能拿 ``birth_time`` 顶**：``birth_time`` 是块身份被签发的时刻，
而 ``store`` 每次保存都会新签一个身份——**每存一次它就换一个**，当不了"创建时间"。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.attr import attr
from core.clock import now_ms
from core.storage.format.block import Block
from model.note.types.body import NoteBody

__all__ = ["NoteData"]


@dataclass(slots=True)
class NoteData(Block[NoteBody]):
    """一篇笔记。

    **``id`` 与 ``body`` 来自基类 ``Block[NoteBody]``，故不写在这里**——
    类体里只列它自己新增的那几个属性。``body`` 那一份是**已编码的正文**（按内容地址去重）。

    ``__table__`` 带 ``note`` 前缀是刻意的：领域专属的类型以域名开头，
    于是 ``project`` 那边可以做出同名概念而互不相干，两张表也不会撞。
    """

    __table__ = "notedata"
    __owner__ = "note"

    title: attr[str] = ""
    """文本级大标题。**它不是正文里的标题行**——那个走 `LineKind.HEADING`。"""

    subtitle: attr[str] = ""
    """副标题。"""

    style: attr[dict[str, str]] = field(default_factory=dict)
    """**笔记级**样式：整篇的观感（背景一类）。

    它是**属性**，不是正文的一部分。理由与所有属性同一条：正文按内容地址去重，
    把"改一次背景"写进正文，等于每改一次外观就把整篇重存一遍。
    值域就是 `conf` 那套——这里只有字符串键值对。
    """

    tags: attr[list[str]] = field(default_factory=list)
    """标签名。

    **非空就去标签表（`NoteTag`）里登记，空就不去**：判定只在这一处发生，
    两边因此不会各说自己那一套。装的是**名字**（与标签表里的键同一形态），
    名字一改就是另一个标签，旧的那份成为空悬标签，等回收机制清掉。
    """

    created: attr[int] = field(default_factory=now_ms)
    """这一篇被创建的时刻（unix 毫秒）。"""

    updated: attr[int] = field(default_factory=now_ms)
    """最后一次改动的时刻（unix 毫秒）。"""

    todo: attr[bool] = False
    """整篇算不算一件待办。行内的待办是行自己的事（`LineKind.TODO`）。"""

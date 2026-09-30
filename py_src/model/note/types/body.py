# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""笔记正文：有序行序列 + 笔记级样式。

**外层是有序列表**，不是以行 id 为键的映射：行序不在行数据里，而规范 CBOR 的映射
按键排序、行 id 又是 ``uuid4``，排序结果与文档顺序无关——存下去再读回来，整篇都会打乱。

正文的编码**落地之后很难再改**：改一次内容地址全变、去重池整份作废。所以形状按
"能忽略未知键、能往后追加"来定，宁可每行多几个字节。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from model.note.types.style import NoteStyle

if TYPE_CHECKING:
    from model.note.types.line import NoteLine

__all__ = ["NoteBody"]


@dataclass(frozen=True, slots=True)
class NoteBody:
    """笔记正文：行序列与笔记级样式。

    整份是不可变的：编辑一次就是造一份新的（落盘也随之产生新的块身份）。
    """

    lines: tuple[NoteLine, ...] = ()
    style: NoteStyle = field(default_factory=NoteStyle)

    def __len__(self) -> int:
        """有多少行。"""
        return len(self.lines)

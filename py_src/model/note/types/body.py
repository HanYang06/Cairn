# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""笔记正文：有序的行序列。

**外层是有序列表**，不是以行 id 为键的映射：行序不在行数据里，而规范 CBOR 的映射
按键排序、行 id 又是 ``uuid4``，排序结果与文档顺序无关——存下去再读回来，整篇都会打乱。

**这里只有行**。笔记级样式与标题一类小字段**不进来**：它们是属性，跟着块走——
塞进正文就等于"改一次背景或标题就把整篇重存一遍"，而正文是按内容地址去重的。

正文的编码**落地之后很难再改**：改一次内容地址全变、去重池整份作废。所以形状按
"能忽略未知键、能往后追加"来定，宁可每行多几个字节。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from model.note.types.line import NoteLine

__all__ = ["NoteBody"]


@dataclass(frozen=True, slots=True)
class NoteBody:
    """笔记正文：行序列。

    整份不可变：编辑一次就是造一份新的（落盘也随之产生新的块身份）。
    """

    lines: tuple[NoteLine, ...] = ()

    def __len__(self) -> int:
        """有多少行。"""
        return len(self.lines)

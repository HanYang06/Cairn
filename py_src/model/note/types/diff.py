# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""变更记录：**只记动作，不记内容**。

正文的变更有三种形式（作者口径）：**新增 / 修改 / 删除**。三种都只要"行 ID + 一个动作"，
内容一个字节都不写：

- **修改**：行 ID + ``change`` → 新内容按行 ID 回当前正文里取；
- **新增**：行 ID + ``insert`` → 内容与位置都在当前正文里（正文的顺序就是最终顺序）；
- **删除**：行 ID + ``delete`` → 那一行已不在正文里，故只剩 ID。

**故 diff 不是文档，是动作日志。** 把内容也写进来，它就成了正文的一份副本：
既冗余，又不好发送、不好分享——要分享得先压一遍，而"不可变"还逼着先复制一遍才能压。

结构是**列表套字典**：外层列表就是链（有序），每个元素是
``{这一步的哈希: [(行 id, 动作), …]}``。哈希的用处是**连续性**（与 git 一致），
不是行内容的摘要。

**线性历史，不分叉**：多分支由派生关系承担（跨作者改写 = 新节点 + 派生边），
同一节点长不出多条支线。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from core.storage.format.block import Block

if TYPE_CHECKING:
    from model.note.types.kinds import LineAction

__all__ = ["DiffStep", "NoteDiff", "NoteDiffBody"]


@dataclass(slots=True)
class DiffStep:
    """一步变更：它的哈希，以及这一步动了哪些行、怎么动的。

    ``hash`` 是这一步的摘要，用来把链串起来（**不是行内容的哈希**）。
    每一项是 ``(行 id, 动作)``——**定长两项，故用元组**；内容不在这里。
    """

    hash: str = ""
    lines: list[tuple[str, LineAction]] = field(default_factory=list)


@dataclass(slots=True)
class NoteDiffBody:
    """变更日志：有序的若干步。"""

    steps: list[DiffStep] = field(default_factory=list)

    def step(self, step_hash: str) -> DiffStep | None:
        """按哈希取一步；不在链上即 ``None``。

        Args:
            step_hash: 那一步的哈希。

        Returns:
            那一步；链上没有它时返回 ``None``。
        """
        for step in self.steps:
            if step.hash == step_hash:
                return step
        return None

    def __len__(self) -> int:
        """链上有多少步。"""
        return len(self.steps)


@dataclass(slots=True)
class NoteDiff(Block[NoteDiffBody]):
    """一篇笔记的变更日志。"""

    __table__ = "notediff"
    __owner__ = "note"

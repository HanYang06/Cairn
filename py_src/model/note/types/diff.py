# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""变更记录：**只记新信息的补丁链**。

三件事先说清：

- **是补丁，不是快照**：只记"这一步把哪几行改成了什么"，**不记旧值**。要比对就拿两个
  历史节点比（上一个对下一个，或当前对 first commit）。
- **哈希是"连续性"**（作者口径）：与 git 一样，用哈希把一步接上一步，除此之外没别的意思。
- **线性历史，不分叉**：多分支由**派生关系**承担（跨作者改写 = 新节点 + 派生边），
  同一节点长不出多条支线；硬要分叉等于把 git 嵌进来。

结构是**列表套字典**：外层列表就是链（有序），每个元素是 `{这一步的哈希: {行 id: 新内容}}`。
故行 id 只写在键上，值是 :class:`~model.note.types.line.LineContent`——同一条事实不写两处。

**一处代价要认**：若一条链整份装在一个块里，那么每保存一次都要把整条链重写一遍——
第 n 次保存的记录里含 n 步，总存储随步数平方增长，且每步的摘要都不复用。
逃法有两条（**待裁**）：① 一步一个块、用 `prev` 串起来；② 链块只装"步的 ID 列表"。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.storage.format.block import Block

if TYPE_CHECKING:
    from model.note.types.line import LineContent

__all__ = ["DiffStep", "NoteDiff", "NoteDiffBody"]


@dataclass(frozen=True, slots=True)
class DiffStep:
    """一步变更：它的哈希，以及这一步把哪些行改成了什么。

    ``hash`` 是这一步的摘要，用来把链串起来（**不是行内容的哈希**）。
    """

    hash: str = ""
    lines: tuple[tuple[str, LineContent], ...] = ()


@dataclass(frozen=True, slots=True)
class NoteDiffBody:
    """变更链：有序的若干步。"""

    steps: tuple[DiffStep, ...] = ()

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
    """一篇笔记的变更链。"""

    __table__ = "notediff"
    __owner__ = "note"

# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""标签：一张表 + 承载它的块。

**标签是真源在标签这一侧的一张表**：K 是标签、V 是笔记 ID 的列表，故一个标签可以同时
被很多笔记引用，而"哪些笔记用了这个标签"是**读这一张表**，不必全库顺扫。

笔记那边只留一串**标签名**（`NoteData.tags`）：非空就来这张表里登记，空就不来——
判定只在这一处发生，两边因此不会各说自己那一套。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.storage.format.block import Block

__all__ = ["NoteTag", "NoteTagTable"]


@dataclass(slots=True)
class NoteTagTable:
    """标签表：标签 → 笔记 ID 的列表。

    用**可变映射**：标签与成员都会被就地增删。键序与去重归编码那一侧，
    不在这里排——排序是落盘那一层的规范化，不是这张表的日常形态。
    """

    entries: dict[str, list[str]] = field(default_factory=dict)

    def notes_of(self, name: str) -> list[str]:
        """用了这个标签的笔记 ID；标签不在表里即空。

        Args:
            name: 标签名（与 `NoteData.tags` 里那一串同一形态）。

        Returns:
            表里那一份 ID 列表；没有这个标签时返回一张空表。
        """
        return self.entries.get(name, [])

    @property
    def names(self) -> list[str]:
        """有哪些标签。"""
        return list(self.entries)

    def __len__(self) -> int:
        """有多少个标签。"""
        return len(self.entries)


@dataclass(slots=True)
class NoteTag(Block[NoteTagTable]):
    """标签表的载体：**一张表一个块**。"""

    __table__ = "notetag"
    __owner__ = "note"

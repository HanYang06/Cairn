# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""标签：一张表 + 承载它的块。

**标签是真源在标签这一侧的一张表**：K 是标签、V 是笔记 ID 的列表，故一个标签可以同时
被很多笔记引用，而"哪些笔记用了这个标签"是**读这一张表**，不必全库顺扫。

笔记那边只留一串**标签名**（`NoteData.tags`）：非空就去这张表里登记，空就不去——
判定只在这一处发生，两边因此不会各说自己那一套。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.storage.format.block import Block

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["NoteTag", "NoteTagTable"]


@dataclass(frozen=True, slots=True)
class NoteTagTable:
    """标签表：标签 → 笔记 ID 的列表。

    条目按标签名排序，故同一份逻辑内容编出的字节唯一。
    """

    entries: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @classmethod
    def of(cls, table: Mapping[str, tuple[str, ...]] | None = None) -> NoteTagTable:
        """由一份映射造标签表：按标签名排序，空成员也留着（标签存在但暂时没人用）。

        Args:
            table: 标签 → 笔记 ID；不给即空表。

        Returns:
            排序之后的标签表。
        """
        if not table:
            return cls()
        return cls(tuple(sorted((name, tuple(ids)) for name, ids in table.items())))

    def notes_of(self, name: str) -> tuple[str, ...]:
        """用了这个标签的笔记 ID；标签不在表里即空。

        Args:
            name: 标签名（与 `NoteData.tags` 里那一串同一形态）。

        Returns:
            笔记 ID，顺序即登记顺序。
        """
        for entry_name, ids in self.entries:
            if entry_name == name:
                return ids
        return ()

    @property
    def names(self) -> tuple[str, ...]:
        """有哪些标签（表里的键，已排序）。"""
        return tuple(name for name, _ in self.entries)

    def __len__(self) -> int:
        """有多少个标签。"""
        return len(self.entries)


@dataclass(slots=True)
class NoteTag(Block[NoteTagTable]):
    """标签表的载体：**一张表一个块**。"""

    __table__ = "notetag"
    __owner__ = "note"

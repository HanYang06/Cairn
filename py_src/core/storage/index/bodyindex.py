# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""`BodyIndex`：内容索引——**按内容地点查回块**，并回答"多少块在用它"。

**它直接继承 `Block`**：与 `AttrIndex` 平级，两条索引互不为父子，也都与任何块同路。
内容按地址去重：同内容只存一份，而引用它的块可能不止一个。故它要答三件事：

1. **谁在用它**：`search(BodyIndex, CONTENT_FIELD, 摘要)` 交出持有它的那些块的行；
2. **有几个人用**：`count(...)` —— **引用数**，删除与压实判"这份内容还有没有人要"靠它；
3. **同一份内容只算一次**：内容的地点就是它的摘要，同摘要即同一份内容，
   故去重在这条线上是**天然的**——这也是内容寻址的全部意义。

**它持有正表、不存反表**：载荷里装的是"某个块的内容地点是某摘要"这一行，
"按摘要查回块"是现算的，故不必按摘要再维护一份倒排。

它认的值是**内容地点（摘要）**，与引擎写出内容记录时那一份逐字相同——两处口径若各算一份，
按内容反查就永远查不到，而且**不报错**。
"""

from __future__ import annotations

from core.storage.db.id import ID
from core.storage.engine import Block
from core.storage.index.index import CONTENT_FIELD
from core.storage.types import BODY_KIND

__all__ = ["BodyIndex"]


class BodyIndex(Block):
    """内容的索引：按内容地点查回块，并给出引用数。"""

    manages = BODY_KIND
    """它管内容——声明成 `Body(...)` 的字段都归它。"""

    def __init__(self, id: ID | None = None) -> None:
        """**身份按块的标准用法来**：调用方签发，或自己现签一个。

        Args:
            id: 身份。不给即现签一个（`ID(self)`）——那正是"造一个新索引块"那条路。
        """
        self.id = ID(self) if id is None else id
        super().__init__(self.id)

    @classmethod
    def holds(cls, block: Block) -> dict[str, object]:
        """内容在索引里的那一列：**只有内容地点（摘要）**。

        字段名不参与：同一份正文挂在两个不同名字的字段上，仍然只算一份内容。
        摘要取自引擎那一个函数（`content_digest`），故与内容记录的身份逐字相同。
        """
        from core.storage.engine import content_digest  # noqa: PLC0415 — 打断环形引用

        place = content_digest(block)
        return {} if place is None else {CONTENT_FIELD: place}

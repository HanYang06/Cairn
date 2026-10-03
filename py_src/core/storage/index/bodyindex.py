# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""`BodyIndex`:正文索引——**按正文摘要查回块**,并回答"多少块在用它".

**它直接继承 `Block`**:与 `AttrIndex` 平级,两条索引互不为父子,也都与任何块同路.
正文按内容寻址:同内容只写一份槽,而引用它的块可能不止一个.故它要答三件事:

1. **谁在用它**:`search(BodyIndex, CONTENT_FIELD, 摘要)` 交出持有它的那些块的行;
2. **有几个人用**:`count(...)` —— **引用数**,回收判"这份内容还有没有人要"靠它;
3. **同一份内容只算一次**:正文的地点就是它的摘要(`engine.body_digest`),同摘要即同一份
   正文,故去重在这条线上是**天然的**——这也是内容寻址的全部意义.

**它持有正表,不存反表**:槽里装的是"某个块的正文地点是某摘要"这一行,
"按摘要查回块"是现算的,故不必按摘要再维护一份倒排.

它认的值是**正文地点(摘要)**,与引擎写正文槽时那一份逐字相同——两处口径若各算一份,
按正文反查就永远查不到,而且**不报错**.

**缺位即退化**:去掉它,按正文查不了,写入去重退化为"每次都写新槽",
而**数据不丢**——这是允许的降级,不是错误.
"""

from __future__ import annotations

from core.storage.db.id import ID
from core.storage.engine import Block
from core.storage.types import BODY_KIND

__all__ = ["BodyIndex"]


class BodyIndex(Block):
    """正文的索引:按正文摘要查回块,并给出引用数."""

    manages = BODY_KIND
    """它管正文——声明成 `Body(...)` 的字段都归它。"""

    def __init__(self, id: ID | None = None) -> None:
        """**身份按块的标准用法来**:调用方签发,或自己现签一个.

        Args:
            id: 身份.不给即现签一个(`ID(self)`)——那正是"造一个新索引块"那条路.
        """
        self.id = ID(self) if id is None else id
        super().__init__(self.id)

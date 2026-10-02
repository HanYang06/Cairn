# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""`AttrIndex`：属性索引——**按属性值查回块**。

**它直接继承 `Block`**：与任何块同路，没有第二条继承关系要记。身份也按同一条路来——

    class AttrIndex(Block):
        def __init__(self) -> None:
            self.id = ID(self)          # 调用方签发身份
            super().__init__(self.id)   # 递给基座

**这两行是必然条件**：没有它，"有 ID 才有表"这条就落不下来，索引块也不会进库——
那就会出现"查索引时不知道它搁哪儿"。故身份由索引块自己签发并递给基座，与任何块一样；
引擎只在需要时**造一个空索引块**（`AttrIndex()`），用它的身份去落盘与登记。

它管的是声明成 `Attr(...)` 的那些字段：**用了就进，没有开关**（不要索引就别声明，
裸赋值照样落盘，只是不进这里）。

**它持有正表、不存反表**：载荷里装的是"某个块的某个属性等于某个值"这一行；
"按值查回块"是把这些行**翻过来看**，现算（`IndexEngine.search`）——存下来的反表要在写路径
上增量维护，漏一处**不报错、只是查不到**；由正表翻过来的没有这个问题。

它自己只声明两样：**管哪一类字段**（`manages`）与**正表那一行长什么样**（`holds`）。
续块、挑活跃块、写行、翻表全在引擎那边；体积上限取配置面的 `index.max.byte`
（块要用别的数才在类体上声明 `max_bytes`，不声明就跟着配置走）。
"""

from __future__ import annotations

from core.storage.db.id import ID
from core.storage.engine import Block
from core.storage.index.index import holds
from core.storage.types import ATTR_KIND

__all__ = ["AttrIndex"]


class AttrIndex(Block):
    """块属性的索引：按属性值查回块。"""

    manages = ATTR_KIND
    """它管属性——声明成 `Attr(...)` 的字段都归它。"""

    def __init__(self, id: ID | None = None) -> None:
        """**身份按块的标准用法来**：调用方签发，或自己现签一个。

        Args:
            id: 身份。不给即现签一个（`ID(self)`）——那正是"造一个新索引块"那条路。
        """
        self.id = ID(self) if id is None else id
        super().__init__(self.id)

    @classmethod
    def holds(cls, block: Block) -> dict[str, object]:
        """正表那一行：这个块的属性字段 → 值。"""
        return holds(block, cls.manages)

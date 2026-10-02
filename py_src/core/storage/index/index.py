# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""索引引擎：**由正表现算反表**；索引类型各自继承 `Block`。

**继承关系与任何块一样，没有第二条要记**：

    Block ── AttrIndex      属性索引（在 attrindex.py）
          └─ BodyIndex      内容索引（在 bodyindex.py）

两个索引**直接继承 `Block`**，彼此平级，也与任何块同路：它们有 ID，因此自己就落进库里
那张身份表——"索引一多，查它的时候得知道它搁哪儿"靠的就是这一条。

**共用逻辑放在本模块的函数上，不放一个中间基类**：那样会多出一层"只为放代码而存在"的
继承（`AttrIndex` 就不是直接继承 `Block` 了），而按块的标准用法，它们本该是块。
故 :func:`holds` 是模块级函数，两个索引各写一行把它接上。

**正表与反表的分工**（本模块的核心）：

| | 是什么 | 谁持有 |
|---|---|---|
| **正表** | 某个块的某一列等于某个值（一行） | **索引块的载荷**（存下来） |
| **反表** | 值 → 哪些块 | **现算**，不存 |

**为什么不把反表存下来**：存下来的反表要在写路径上增量维护，而对不上的时候**不报错**，
只是查不到。由正表翻过来的反表每次都是同一个答案——确定、稳定。

用法（都在引擎上）：

- :meth:`IndexEngine.record`：把一个块的正表行写进对应索引（满了引擎自动续块）；
- :meth:`IndexEngine.search`：按（字段，值）翻出块的**行**；
- :meth:`IndexEngine.count`：数一数某个值被几行指着（`BodyIndex` 的引用数靠它）。
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from core.storage.types import kind_of, kinds_of

if TYPE_CHECKING:
    from collections.abc import Iterator

    from core.storage.engine import Block, Engine

CONTENT_FIELD = "content"
"""内容索引里的字段名：内容按地址寻址，故它那一列就叫这个。"""


def holds(block: Block, manages: str) -> dict[str, object]:
    """一个块在**某一类索引**里正表的那一行：字段名 → 值。

    判据只看字段的落点——声明成 `Attr(...)` 的进属性索引，声明成 `Body(...)` 的进内容索引。
    故"用了就必然进"，没有第二个开关。

    清单**以类体声明的为准**，再并上实例上多出来的：没显式赋过值的声明字段不在 `vars()`
    里，只看它就会把"带默认值就存"的字段整个漏掉（而且不报错）。

    Args:
        block: 要落成索引行的那个块。
        manages: 这一类索引管哪种落点（`'attr'` / `'body'`）。
    """
    names = list(kinds_of(type(block)))
    for name in vars(block):
        if name != "id" and not name.startswith("_") and name not in names:
            names.append(name)
    row: dict[str, object] = {}
    for name in names:
        if kind_of(type(block), name) != manages:
            continue
        row[name] = getattr(block, name, None)
    return row


class IndexEngine:
    """索引引擎：**由正表现算反表**。

    它只管索引，不认识块的内容语义；它拿到的每一行都是"某个块在某个索引里的一行"。

    Args:
        engine: 它为之服务的存储引擎（正表行与反表查询都经它落地）。
    """

    def __init__(self, engine: Engine) -> None:
        """接上存储引擎。"""
        self._engine = engine

    def record(self, block: Block) -> None:
        """把一个块的**正表行**写进它该进的索引。

        哪些字段进哪一类索引由索引类自己声明（它自己的 `manages`）；
        本方法只管把行写下去、满了续块。
        """
        for owner in owners():
            row = owner.holds(block)
            if not row:
                continue
            self._engine.write_index_row(owner, block.id.value_uuid, row)

    def search(
        self, owner: type[Block], field: str, value: object
    ) -> tuple[dict[str, object], ...]:
        """按（字段，值）**翻出正表里的行**：一行是"某个块这一列等于这个值"。

        反表是现算的：读遍这类索引块的全部行，挑出匹配的那些。行里带 `value_uuid`，
        故顺着它就能把块取回来——这就是"按属性查块"那条完整路。
        """
        wanted = index_text(value)
        found: list[dict[str, object]] = []
        for row in self._engine.read_index_rows(owner):
            if row.get("field") != field:
                continue
            if row.get("value") != wanted:
                continue
            found.append(row)
        return tuple(found)

    def count(self, owner: type[Block], field: str, value: object) -> int:
        """这个值被**几行**指着——`BodyIndex` 的引用数（去重判据）靠它。"""
        return len(self.search(owner, field, value))

    def field_names(self, owner: type[Block]) -> tuple[str, ...]:
        """这类索引里有哪些字段可查——界面拿它显示"能按什么查"。"""
        return tuple(sorted({str(row.get("field")) for row in self._engine.read_index_rows(owner)}))


def owners() -> tuple[type[Block], ...]:
    """进程内已知的**具体**索引类型（引擎开库时照它建表）。

    **判据是"它声明了自己管哪一类字段"**（自己的 `manages`），不是"它继承了谁"：
    两个索引直接继承 `Block`（与任何块同路），按继承找会一个都找不到，而且**整条索引链
    会静默失效**——表不建、行不写，只是查不到。

    **这里用了一次运行期导入**（本仓不常用的那一档，理由写在这里）：

    - 具体索引各在自己的文件里，而"Block 的子类"这个清单**只看谁被 import 过**；
    - 若不导入，索引类型就一个都看不到，于是表不建、行不写，而**整条链不报错**——
      这种失败最难查，因为它什么都不说；
    - 代价只是一次 `importlib.import_module`（幂等、有缓存），换来"索引永远在册"。

    另一条路是在 `storage/__init__.py` 里写两行静态 import，但那会让"打开存储"顺带
    拉进索引实现，而索引本该是按需的。两害相权，取这一条，并把理由留在这里。
    """
    for module in ("core.storage.index.attrindex", "core.storage.index.bodyindex"):
        importlib.import_module(module)
    return tuple(cls for cls in _all_subclasses(_block_root()) if cls.__dict__.get("manages"))


def table_of(owner: type[Block]) -> str:
    """索引块的表名（＝它自己的类型名下方写法）。"""
    return owner.__name__.lower()


def index_text(value: object) -> str:
    """把索引值文本化：**带上类型名**，免得 `1` 与 `True` 撞在一起。

    读与写两侧共用这一条口径，故查的时候写 `1` 不会查到 `True`。
    """
    return f"{type(value).__name__}:{value}"


def _block_root() -> type[Block]:
    """块基座（惰性取，免得本模块在引擎之前初始化）。"""
    from core.storage.engine import Block  # noqa: PLC0415 — 打断环形引用

    return Block


def _all_subclasses(root: type[Block]) -> Iterator[type[Block]]:
    """递归收集全部子类（含隔代）。"""
    for child in root.__subclasses__():
        yield child
        yield from _all_subclasses(child)


__all__ = [
    "CONTENT_FIELD",
    "IndexEngine",
    "holds",
    "index_text",
    "owners",
    "table_of",
]

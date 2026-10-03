# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""索引引擎:**由正表现算反表**;索引类型各自继承 `Block`.

**继承关系与任何块一样,没有第二条要记**:

    Block ── AttrIndex      属性索引(在 attrindex.py)
          └─ BodyIndex      正文索引(在 bodyindex.py)

两个索引**直接继承 `Block`**,彼此平级,也与任何块同路:它们有 ID,因此自己就落进库里
那张身份表——"索引一多,查它的时候得知道它搁哪儿"靠的就是这一条.

**共用逻辑放在本模块的函数上,不放一个中间基类**:那样会多出一层"只为放代码而存在"的
继承(`AttrIndex` 就不是直接继承 `Block` 了),而按块的标准用法,它们本该是块.

**正表与反表的分工**(本模块的核心):

| | 是什么 | 谁持有 |
|---|---|---|
| **正表** | 某个块的某一列等于某个值(一行) | **索引块的槽**(存下来) |
| **反表** | 值 → 哪些块 | **现算**,不存 |

**为什么不把反表存下来**:存下来的反表要在写路径上增量维护,而对不上的时候**不报错**,
只是查不到.由正表翻过来的反表每次都是同一个答案——确定,稳定.

**正表行落在载体的槽上**:一条正表行一个槽,故写路径只有追加,没有改动.
"这一行在哪"进索引块自己那张身份表——**索引块也是块**,它走块的标准用法.

用法(都在 :class:`IndexEngine` 上):

- :meth:`IndexEngine.search`:按(列,值)翻出块的**行**;
- :meth:`IndexEngine.count`:数一数某个值被几行指着(属性那一路靠它);
- :meth:`IndexEngine.holders`:**谁在要这份正文**——扫各块的摘要链现算;
- :meth:`IndexEngine.field_names`:这类索引里有哪些列可查.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from ..db.id import parse_body_history
from ..db.payload import COLUMN_KEY
from ..db.payload import index_text as _text_of

if TYPE_CHECKING:
    from collections.abc import Iterator

    from core.storage.engine import Block, Engine

CONTENT_FIELD = "cairn.body"
"""正文索引里的列名：正文按**整份内容的摘要**寻址，故它那一列是这个名字。"""


class IndexEngine:
    """索引引擎:**由正表现算反表**.

    它只管索引,不认识块的内容语义;它拿到的每一行都是"某个块在某个索引里的一行".

    Args:
        engine: 它为之服务的存储引擎(正表行与反表查询都经它落地).
    """

    def __init__(self, engine: Engine) -> None:
        """接上存储引擎."""
        self._engine = engine

    def records(self, owner: type[Block]) -> tuple[dict[str, object], ...]:
        """翻出一类索引的**全部正表行**:一行是"某个块这一列等于这个值".

        同一类索引可以有好几块,它们**并起来**才是完整的正表;同一个块同一列若被写过
        多次,取最后写的那一条.

        **它是元组而不是生成器**:下面那几问要反复遍历它,生成器一趟就空.
        """
        return tuple(self._engine.read_index_rows(owner))

    def search(
        self, owner: type[Block], field: str, value: object
    ) -> tuple[dict[str, object], ...]:
        """按(列,值)**翻出正表里的行**:一行是"某个块这一列等于这个值".

        反表是现算的:读遍这类索引块的全部行,挑出匹配的那些.行里带 `value_uuid`,
        故顺着它就能把块取回来——这就是"按属性查块"那条完整路.
        """
        wanted = _text_of(value)
        found: list[dict[str, object]] = []
        for row in self.records(owner):
            if str(row.get(COLUMN_KEY)) != field:
                continue
            if str(row.get("value")) != wanted:
                continue
            found.append(row)
        return tuple(found)

    def count(self, owner: type[Block], field: str, value: object) -> int:
        """这个值被几条正表行指着.

        **正文索引不适用**:它的正表行答的是"这份正文在哪",不是"哪个块提过它";
        要问"谁在用它"走 :meth:`holders`.
        """
        return len(self.search(owner, field, value))

    def holders(self, value: object) -> tuple[dict[str, object], ...]:
        """**谁在要这份正文**:摘要被哪些块的摘要链指着,交出那些块的行.

        **现算,不落盘**:位置行只答"这份正文在哪"(位置不挂在某个块身上——那一块
        被删了,还在引用它的块就断了),故"还有几个人在用它"只能扫各块的 `body_history`
        现算.每条行里都有 `value_uuid`,顺着它就能把那个块取回来.

        Args:
            value: 正文摘要(原样;文本化由本方法做,与写侧同一口径).
        """
        wanted = _text_of(value)
        found: list[dict[str, object]] = []
        for _table, row in self._engine.identity_rows():
            chain = tuple(parse_body_history(str(row.get("body_history") or "")))
            if not chain or _text_of(chain[0]) != wanted:
                continue
            found.append(row)
        return tuple(found)

    def field_names(self, owner: type[Block]) -> tuple[str, ...]:
        """这类索引里有哪些列可查——界面拿它显示"能按什么查"."""
        return tuple(sorted({str(row.get(COLUMN_KEY)) for row in self.records(owner)}))


def owners() -> tuple[type[Block], ...]:
    """进程内已知的**具体**索引类型(引擎开库时照它建表).

    **判据是"它声明了自己管哪一类字段"**(自己的 `manages`),不是"它继承了谁":
    两个索引直接继承 `Block`(与任何块同路),按继承找会一个都找不到,而且**整条索引链
    会静默失效**——表不建,行不写,只是查不到.

    **这里用了一次运行期导入**(本仓不常用的那一档,理由写在这里):

    - 具体索引各在自己的文件里,而"Block 的子类"这个清单**只看谁被 import 过**;
    - 若不导入,索引类型就一个都看不到,于是表不建,行不写,而**整条链不报错**——
      这种失败最难查,因为它什么都不说;
    - 代价只是一次 `importlib.import_module`(幂等,有缓存),换来"索引永远在册".

    另一条路是在 `storage/__init__.py` 里写两行静态 import,但那会让"打开存储"顺带
    拉进索引实现,而索引本该是按需的.两害相权,取这一条,并把理由留在这里.
    """
    for module in ("core.storage.index.attrindex", "core.storage.index.bodyindex"):
        importlib.import_module(module)
    return tuple(cls for cls in _all_subclasses(_block_root()) if cls.__dict__.get("manages"))


def table_of(owner: type[Block]) -> str:
    """索引块的表名(=它自己的类型名下方写法)."""
    return owner.__name__.lower()


def _block_root() -> type[Block]:
    """块基座(惰性取,免得本模块在引擎之前初始化)."""
    from core.storage.engine import Block  # noqa: PLC0415 — 打断环形引用

    return Block


def _all_subclasses(root: type[Block]) -> Iterator[type[Block]]:
    """递归收集全部子类(含隔代)."""
    for child in root.__subclasses__():
        yield child
        yield from _all_subclasses(child)


__all__ = ["CONTENT_FIELD", "IndexEngine", "owners", "table_of"]

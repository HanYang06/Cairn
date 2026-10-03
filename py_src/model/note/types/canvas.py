# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""画板:图的摆放,加上图与图之间的连线.

**图的形状走"类型 + 参数"**:图的类型会一直长(矩形 / 椭圆 / 箭头 / 路径 / 位图 …),
做成每类一个类型或一张表,每加一种就要改一次口径.故它是一个 `kind` 加一串几何参数,
形态由类型自己解释——与"媒体种类由 mime 决定,不立三个类型"是同一条判断.

**图元类型是开放字符串 + 一份图元库**(作者口径):写作时写的是图元名,渲染时**先去库里找**,
有就取出来,没有就报错.故加载顺序是**先读库**(我有哪些图),用户用的都是库里已有的.
图元库本体是仓里的 `config/shapes.json`;**读它的那一层尚未实现**(渲染归界面层).

连线是**逻辑图**,故**不存折点**:只记"连哪些图,怎么连,标什么,线是什么形式",
几何由渲染时自动布局生成.于是手绘的走向不会被原样复现,而是给一套自动优化的——
**优化就发生在绘制过程中**,用户只管拽图形,确认关系.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.storage.engine import Block
from core.storage.types import Body

__all__ = ["CanvasLink", "Figure", "NoteCanvas", "PlacedShape"]


@dataclass(slots=True)
class Figure:
    """一枚图:图元类型 + 几何参数.

    ``path`` 是**绘图指令流**(作者口径:`M` / `L` / `C` / `Q` / `A` / `Z` 那一套):
    外层是**列表**(指令条数会变),每条指令是**定长两项** `(操作, 坐标)`,故用元组.
    **裸点坐标不足以确定图形**,必须带"怎么连"的指令.
    """

    kind: str = ""
    """图元类型。**开放字符串**：加一种图只加一个取值，不动这里的形状。"""

    path: list[tuple[str, tuple[float, ...]]] = field(default_factory=list)
    """指令流：`[("M", (10.0, 20.0)), ("L", (30.0, 40.0)), …]`。"""

    ref: str = ""
    """要指向外部东西的图元（如位图）在这里放那个 ID；不需要时为空。"""


@dataclass(slots=True)
class PlacedShape:
    """画板上的一枚图:它是什么,以及怎么摆.

    字段按作者给的顺序:图 / 缩放 / 旋转 / 坐标 / 样式.

    **这里没有"关系"字段**:一枚图参与哪些逻辑关系,由 :class:`CanvasLink` 表达
    (连线里列出它连的图).同一张板子上再存一份"我连着谁",就是同一条事实写两处.
    """

    figure: Figure = field(default_factory=Figure)
    scale: float = 1.0
    rotation: float = 0.0
    at: tuple[float, float] = (0.0, 0.0)
    style: dict[str, str] = field(default_factory=dict)
    """**图形**样式（描边 / 填充 / 线宽…），与行内文字样式不是同一样东西，故不共用类型。"""


@dataclass(slots=True)
class CanvasLink:
    """一条连线:连哪些图,怎么连,标什么,线长什么样.

    **不存折点**:几何归自动布局,故这里只有语义.标签写在边上,不画在图里.
    """

    figures: list[str] = field(default_factory=list)
    """这条连线连的是哪几枚图（图编号）。"""

    mode: str = ""
    """链接方式（直连 / 折线 / 树形 …）。取值开放，与图类型同一口径。"""

    label: str = ""
    """连线上的标签。"""

    line: str = ""
    """链接线形式（实线 / 虚线 / 粗细…）。"""


class NoteCanvas(Block):
    """一张画板.

    载荷是两样:一枚枚图,一条条连线.``shapes`` 是**列表**而不是映射——
    **画的先后是内容**,而规范 CBOR 会给映射的键排序,顺序一排序就丢了.
    故它是一串 `(编号, 那一枚图)`:外层列表保序,内层定长两项.
    ``links`` 用映射即可(连线的顺序不是内容).

    编号一律是**字符串**:它要当映射的键,而 JSON 的键只能是字符串——
    契约面(Python → JSON → TS)过不去的东西,不该在存储面里先埋下.

    表名只由类名算出来(``NoteCanvas`` → ``notecanvas``),故本类不写 ``__init__``:
    基座那一支收下身份,不给就现签一个.
    """

    shapes: list[tuple[str, PlacedShape]] = Body([])  # type: ignore[assignment]
    links: dict[str, CanvasLink] = Body({})  # type: ignore[assignment]

    def shape(self, identifier: str) -> PlacedShape | None:
        """按编号取一枚图;没有即 ``None``.

        Args:
            identifier: 图编号.

        Returns:
            那一枚图;编号不在板上时返回 ``None``.
        """
        for key, placed in self.shapes:
            if key == identifier:
                return placed
        return None

    def link(self, identifier: str) -> CanvasLink | None:
        """按编号取一条连线;没有即 ``None``."""
        return self.links.get(identifier)

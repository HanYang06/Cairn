# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""画板：图的摆放，加上图与图之间的连线。

**图的形状也走"类型 + 参数"**：图的类型会一直长（矩形 / 椭圆 / 箭头 / 路径 / 位图 …），
做成每类一个类型或一张表，每加一种就要改一次口径。故它是一个 `kind` 加一串几何参数，
形态由类型自己解释——与"媒体种类由 mime 决定、不立三个类型"是同一条判断。

连线是**逻辑图**，故**不存折点**：只记"连哪些图、怎么连、标什么、线是什么形式"，
几何由渲染时自动布局生成。于是手绘的走向不会被原样复现，而是给一套自动优化的——
**优化就发生在绘制过程中**，边画边优化。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.storage.format.block import Block

__all__ = ["CanvasLink", "Figure", "NoteCanvas", "NoteCanvasBody", "PlacedShape"]


@dataclass(frozen=True, slots=True)
class Figure:
    """一枚图：图元类型 + 几何参数。

    ``path`` 是**绘图指令流**（作者口径：`M` / `L` / `C` / `Q` / `A` / `Z` 那一套），
    每条指令一串坐标。**裸点坐标不足以确定图形**，必须带"怎么连"的指令。
    """

    kind: str = ""
    """图元类型。**开放字符串**：加一种图只加一个取值，不动这里的形状。"""

    path: tuple[tuple[str, tuple[float, ...]], ...] = ()
    """指令流：`(("M", (10.0, 20.0)), ("L", (30.0, 40.0)), …)`。"""

    ref: str = ""
    """要指向外部东西的图元（如位图）在这里放那个 ID；不需要时为空。"""


@dataclass(frozen=True, slots=True)
class PlacedShape:
    """画板上的一枚图：它是什么，以及怎么摆。

    字段按作者给的顺序：图 / 缩放 / 旋转 / 坐标 / 样式。

    **这里没有"关系"字段**：一枚图参与哪些逻辑关系，由 :class:`CanvasLink` 表达
    （连线里列出它连的图）。同一张板子上再存一份"我连着谁"，就是同一条事实写两处。
    """

    figure: Figure = field(default_factory=Figure)
    scale: float = 1.0
    rotation: float = 0.0
    at: tuple[float, float] = (0.0, 0.0)
    style: tuple[tuple[str, str], ...] = ()
    """**图形**样式（描边 / 填充 / 线宽…），与行内文字样式不是同一样东西，故不共用类型。

    键按名排序：同一份逻辑内容编出的字节必须唯一。
    """


@dataclass(frozen=True, slots=True)
class CanvasLink:
    """一条连线：连哪些图、怎么连、标什么、线长什么样。

    **不存折点**：几何归自动布局，故这里只有语义。标签写在边上，不画在图里。
    """

    figures: tuple[str, ...] = ()
    """这条连线连的是哪几枚图（图编号）。"""

    mode: str = ""
    """链接方式（直连 / 折线 / 树形 …）。取值开放，与图类型同一口径。"""

    label: str = ""
    """连线上的标签。"""

    line: str = ""
    """链接线形式（实线 / 虚线 / 粗细…）。"""


@dataclass(frozen=True, slots=True)
class NoteCanvasBody:
    """画板的载荷：一枚枚图，加上一条条连线。

    两张表都按**编号**索引，且**编号一律是字符串**：它要当映射的键，而 JSON 的键只能是
    字符串——契约面（Python → JSON → TS）过不去的东西，不该在存储面里先埋下。
    """

    shapes: tuple[tuple[str, PlacedShape], ...] = ()
    """图编号 → 那一枚图。顺序即画的先后。"""

    links: tuple[tuple[str, CanvasLink], ...] = ()
    """链接编号 → 那一条连线。"""

    def shape(self, identifier: str) -> PlacedShape | None:
        """按编号取一枚图；没有即 ``None``。

        Args:
            identifier: 图编号。

        Returns:
            那一枚图；编号不在板上时返回 ``None``。
        """
        for key, placed in self.shapes:
            if key == identifier:
                return placed
        return None

    def link(self, identifier: str) -> CanvasLink | None:
        """按编号取一条连线；没有即 ``None``。

        Args:
            identifier: 链接编号。

        Returns:
            那一条连线；编号不在板上时返回 ``None``。
        """
        for key, connection in self.links:
            if key == identifier:
                return connection
        return None


@dataclass(slots=True)
class NoteCanvas(Block[NoteCanvasBody]):
    """一张画板。"""

    __table__ = "notecanvas"
    __owner__ = "note"

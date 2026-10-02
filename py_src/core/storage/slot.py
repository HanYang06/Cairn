# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""格与 slot：载体里等大的分配单位，以及"一条记录占的那一段"。

模型只有一条：**载体是一串等大的格，记录从格边界开始写，按需占用连续的多个格**。
一条记录的位置就是它占的**头格与末格**两个整数，字节偏移由算术得出，不另存一份。

**格长按五档相加**（``slot.max.byte.{b,kb,mb,gb,tb}``）：声明与相加都在 `storage/conf.py`，
本模块只做算术。格长从哪儿来与格长怎么用是两件事，混在一边会让"改一个数字"看起来像改了定位口径。

**`Slot` 是"一条记录占的那一段"，不是"一个格子"**：一条记录跨 N 格时只有**头格**写着总长，
中间与末格除了补零什么都没有。若让它表示单格，一次匹配就要造 N 个对象、其中 N−1 个问什么都是
无意义的。故它对应的是"头格 + 末格"加一个已知的载体。

**它不持有可变状态**：格长在载体文件头里、总长与校验和在记录头里，"这段还作不作数"由
调用方拿身份去核对。任何缓存在对象上的状态都会在压实、追加、删墓碑之后与文件分叉，
而且不报错——只是读出来不对。故它只**代理** pack 的读写：

- `Slot`（只读视图）：知道自己在哪个 pack、占哪几格，能交出字节；
- `Pack`（唯一可变面）：持有文件尾这一个可变事实，独占写口与封口判定。

**定位没有第二套口径**：不存在"格内偏移"——记录起点就在格边界上，这正是"两个数字即精确
位置"的前提。格长随载体走（写进载体文件头），故本模块只做算术，不读盘。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from core.exc import SlotError

if TYPE_CHECKING:
    from .pack import Pack

DEFAULT_SLOT_BYTES = 512
"""开箱格长（字节）：声明处（`storage/conf.py`）拿它当默认值。

五档全不写等于零、等于错，故至少要有一档带默认值。取最小的一档带它，是因为**格长要小**：
一条记录至少占一格，格长即每条记录的平均浪费上限；512 B 是"装得下小字段、又不浪费大截"
的那一档。要更大就往上写 ``kb`` 及以上——**加一档是加法，不是替换**。

**这个数住在这里**：它是格这一层的开箱值；把它抬进配置声明那份文件会让本模块反过来依赖
配置引擎，而本模块只做算术（读配置是 `storage/conf.py` 的事）。
"""


class SlotRange(NamedTuple):
    """一条记录占的格区间：**头格与末格两个整数，闭区间**。

    两数即精确位置：字节偏移由 :func:`offset_of` 算出，不落盘、不另存。
    """

    first: int
    """头一格（从载体文件头之后起算，故文件头不必凑成整格）。"""

    last: int
    """末一格，闭区间。单格记录即 ``first == last``。"""

    @property
    def size(self) -> int:
        """占了多少格。

        **不叫 `count`**：NamedTuple 继承 `tuple`，而 `tuple.count` 是"某个值出现几次"，
        同名的属性会把它盖掉（mypy 直接拒绝）。要"几格"用本属性或 `len()`。
        """
        return self.last - self.first + 1

    def __len__(self) -> int:
        """占了多少格（`len(span)` 与 :attr:`size` 同义）。"""
        return self.last - self.first + 1


def span_of(total: int, *, slot: int) -> SlotRange:
    """一条记录要占哪几格：由总长与格长算出，从**头格零**起算。

    Args:
        total: 记录总长（字节，含记录头）。
        slot: 格长（字节）。

    Returns:
        它占的格区间。

    Raises:
        SlotError: 总长不是正数，或格长不是正数。
    """
    if slot <= 0:
        raise SlotError(f"格长必须是正数: {slot}")
    if total <= 0:
        raise SlotError(f"记录总长必须是正数: {total}")
    return SlotRange(0, (total - 1) // slot)


def offset_of(first: int, *, head: int, slot: int) -> int:
    """某一格在载体文件里的字节偏移：``文件头长度 + 格号 × 格长``。

    **故载体自描述**：只凭文件头里的格长与一条记录的格区间即可算出偏移，不必再存一套。

    Raises:
        SlotError: 格号或格长不合法。
    """
    if slot <= 0:
        raise SlotError(f"格长必须是正数: {slot}")
    if first < 0:
        raise SlotError(f"格号不能为负: {first}")
    return head + first * slot


class Slot:
    """一条记录在某个载体里占的那一段格：**只读视图，不持有可变状态**。

    它由 :meth:`Pack.slot` 造出来（读侧）或由写入的结果交回（写侧），随后只回答两件事：
    "占哪几格"与"这一段是什么字节"。**它不改文件**——改文件是 pack 的事，因为
    "文件尾在哪"是唯一需要可变状态的地方，它归 pack 所有。

    Args:
        pack: 这个 slot 所在的载体。
        span: 它占的格区间（头格与末格，闭区间）。
    """

    __slots__ = ("_pack", "_span")

    def __init__(self, pack: Pack, span: SlotRange) -> None:
        """接上载体与格区间。**这里不读盘、不校验**：读是 :meth:`read` 的事。"""
        self._pack = pack
        self._span = span

    @property
    def pack(self) -> Pack:
        """它所在的载体：读与写都经由它。"""
        return self._pack

    @property
    def span(self) -> SlotRange:
        """占的格区间（头格与末格）。"""
        return self._span

    @property
    def first(self) -> int:
        """头一格：**只有这一格写着总长**，故按格号定位的记录从这里开始读。"""
        return self._span.first

    @property
    def last(self) -> int:
        """末一格（闭区间）。"""
        return self._span.last

    @property
    def count(self) -> int:
        """占了多少格（同 :attr:`SlotRange.size`）。"""
        return self._span.size

    def __len__(self) -> int:
        """占了多少格。"""
        return self._span.size

    @property
    def offset(self) -> int:
        """这一段在载体文件里的字节偏移：由载体文件头长度与格长算出。"""
        layout = self._pack.layout()
        return offset_of(self.first, head=layout.head, slot=layout.slot)

    @property
    def byte_size(self) -> int:
        """这一段的总字节数：格数 × 格长。**记录总长通常小于它**，差的那截是补零。"""
        return len(self._span) * self._pack.layout().slot

    def read(self) -> bytes:
        """读出这一段字节（**含记录头与格尾补零**）。

        记录的总长写在记录头里，故调用方据此切掉尾部的零；本方法不猜"到哪儿为止"。
        要直接拿到载荷走 :meth:`payload`。
        """
        return self._pack.read_span(self._span)

    def payload(self) -> bytes:
        """读出这一段里的**载荷**：跳过记录头，按总长切掉格尾补零。

        适合"顺扫到某条记录、要它装的是什么"这一个动作；要连记录头一起看走 :meth:`read`。

        Raises:
            RecordFormatError: 记录头不完整、总长或格数与实际对不上，或校验和不符。
        """
        return self._pack.read_payload(self._span)

    def __contains__(self, index: int) -> bool:
        """这个格号在不在本段里。"""
        return self.first <= index <= self.last

    def __repr__(self) -> str:
        """诊断用：看得出它在哪个载体的哪几格，不必读盘。"""
        return f"Slot(pack={self._pack.name!r}, first={self.first}, last={self.last})"


__all__ = [
    "DEFAULT_SLOT_BYTES",
    "Slot",
    "SlotRange",
    "offset_of",
    "span_of",
]

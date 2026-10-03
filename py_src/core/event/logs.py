# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""基于事件引擎的日志记录与反馈.

事件是内核的咽喉:写路径先发通知,故"发生过什么"能在这一处收齐.本模块做的是
**一次订阅,按类型分流**,去向有三路:

- **诊断**:折成一行交给记录器 `cairn.events`;级别由分流表给,说不说话由
  `core.log.level` 那族的级别决定;
- **落盘**:折成一行 JSON(JSON Lines)追加到调用方给的文件;**不给落点就不建文件**;
- **反馈**:交给注册进来的回调(边车把内核到壳的通知帧接在这一路).

四条判据:

1. **分流表与事件目录同源**:`ROUTES` 的键集等于 `catalog.ALL`,由测试拦下;
   加了事件而漏登记,属"记漏了却不报错"那一类故障.
2. **日志层绝不回流**:本模块的任何失败只写诊断,不抛回发布者,**也不发事件**——
   发事件会让"失败 → 记日志 → 再失败"自激.总线另有一层异常隔离,两层各管一段.
3. **订阅建在目录上,按表分流**:表里没有的类型走 `DEFAULT_ROUTE`,故漏登记退化成
   一条照常记录的事件,而不是静默丢弃.
4. **同步写,一行一条,不轮转**:事件在写路径里同步触发,故落盘也同步;轮转与上限
   尚无调用方,不预埋.

事件处理器抛错(总线的失败钩子)也接在这里:它是**通知层自己的故障**,只进诊断,
不进落盘与反馈——落盘那份记录只装"发生过的事实".
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from core.event import catalog
from core.event.events import Event

if TYPE_CHECKING:
    from collections.abc import Mapping

    from core.event.bus import Bus, ErrorHook, Handler

LOGGER_NAME = "cairn.events"
"""事件日志的记录器名：与内核其余记录器同在 `cairn` 这族，故级别旋钮管得到它。"""

LOG_VERSION = 1
"""记录格式的版本：**第一天就有**，改格式之后不必猜旧行是哪一版。"""


class Sink(Enum):
    """一条事件可以去的落点.

    **分流的是去向**,不是级别:级别词表已经有 `logging` 那一套,再造一份必然分叉.
    """

    LOGGER = "logger"
    FILE = "file"
    FEEDBACK = "feedback"


@dataclass(frozen=True, slots=True)
class Route:
    """一种事件类型的分流:诊断记到什么级别,去哪些落点.

    Attributes:
        level: 诊断那一路的级别(`logging` 的常量).
        sinks: 这条事件去哪些落点.
    """

    level: int
    sinks: frozenset[Sink]


DEFAULT_ROUTE = Route(level=logging.INFO, sinks=frozenset(Sink))
"""分流表里没有的类型走这一条：目录与表由测试对齐，故它只在表漏登记时生效。"""


class EventLog:
    """事件日志:一次订阅,按分流表把事件送到三处落点.

    订阅在构造时成立,在 :meth:`close` 时撤掉——与内核那根线同口径:装配即接上,
    关掉就解开.落盘是**追加写**:一份文件记一条进程的流水,不在装配时清空.

    Args:
        bus: 要订阅的总线.
        path: 落盘的落点;不给即不落盘(**不建文件**,故只读库不会凭空多出一份).
    """

    def __init__(self, bus: Bus, *, path: str | Path | None = None) -> None:
        self._logger = logging.getLogger(LOGGER_NAME)
        self._file: TextIO | None = None if path is None else _open(path)
        self._feedbacks: list[Feedback] = []
        self._subscriptions = tuple(
            bus.subscribe(event_type, self._on_event) for event_type in catalog.ALL
        )

    def add_feedback(self, sink: Feedback) -> None:
        """接一路反馈:分流表里带了 `FEEDBACK` 的事件会推给它.

        同一个回调不重复接(与总线判重同口径:按对象相等性判).
        """
        if sink not in self._feedbacks:
            self._feedbacks.append(sink)

    def remove_feedback(self, sink: Feedback) -> bool:
        """撤掉一路反馈;没接过即返回 ``False``."""
        if sink not in self._feedbacks:
            return False
        self._feedbacks.remove(sink)
        return True

    def close(self) -> None:
        """撤掉订阅,关掉落盘的文件;**幂等**,关第二次不出错."""
        for subscription in self._subscriptions:
            subscription.cancel()
        self._subscriptions = ()
        handle, self._file = self._file, None
        if handle is not None:
            with contextlib.suppress(OSError):
                handle.close()

    def _on_event(self, event: Event) -> None:
        """一条事件按分流表走一遍:任一路失败都只写诊断,不回流给发布者."""
        route = route_of(event.type)
        for sink in _SINK_ORDER:
            if sink not in route.sinks:
                continue
            try:
                self._deliver(sink, event, route.level)
            except Exception as error:  # noqa: BLE001 — 日志层不得把异常回流给发布者
                self._complain(sink, event, error)

    def _deliver(self, sink: Sink, event: Event, level: int) -> None:
        """把一条事件送到一个落点."""
        if sink is Sink.LOGGER:
            self._logger.log(level, "%s", _line(event))
        elif sink is Sink.FILE:
            self._append(event)
        elif sink is Sink.FEEDBACK:
            self._push(event)
        else:  # pragma: no cover — 三路都接在这一处,加一路落点必须在这里也接上
            raise AssertionError(f"没有这一路落点: {sink}")

    def _append(self, event: Event) -> None:
        """把一条事件写成一行 JSON;没给落点即什么也不做."""
        handle = self._file
        if handle is None:
            return
        handle.write(json.dumps(_record(event), ensure_ascii=False, default=repr) + "\n")

    def _push(self, event: Event) -> None:
        """把一条事件推给每一路反馈;某一路抛错不中断其余(与总线同口径)."""
        for sink in tuple(self._feedbacks):
            try:
                sink(event)
            except Exception as error:  # noqa: BLE001 — 单路反馈的异常同样不回流
                self._complain(Sink.FEEDBACK, event, error)

    def _complain(self, sink: Sink, event: Event, error: Exception) -> None:
        """记一句诊断:日志层自己不因任何异常回流给发布者."""
        with contextlib.suppress(Exception):
            self._logger.warning(
                "事件日志的 %s 落点失败，已忽略：type=%s subject=%s error=%r",
                sink.value,
                event.type,
                event.subject,
                error,
            )


Feedback = Callable[[Event], None]
"""反馈去向：收到一条事件即往外推；返回值不被使用（通知语义，不取回执）。"""

#: 一条事件内部的去向次序:**定死**,不靠 `set` 的迭代序——那会跨次运行漂移,
#: 而"落盘先于反馈"这类先后关系是能拿来推理的(反馈那一侧读文件即读到刚落的那一行).
_SINK_ORDER: tuple[Sink, ...] = (Sink.LOGGER, Sink.FILE, Sink.FEEDBACK)

#: 当前两条写路径事件的分流:诊断 + 落盘 + 反馈,级别取 INFO.
#: 两条都是"库被改了"这一级的事实,故把 `core.log.level` 调到 INFO 即能在终端看到;
#: 默认的 WARNING 只让故障说话.新加事件时在下面那张表里各写一行.
_ROUTE_RECORDED = Route(
    level=logging.INFO,
    sinks=frozenset({Sink.LOGGER, Sink.FILE, Sink.FEEDBACK}),
)

ROUTES: Mapping[str, Route] = {
    catalog.OBJECT_PUT: _ROUTE_RECORDED,
    catalog.OBJECT_DELETED: _ROUTE_RECORDED,
}
"""事件类型 → 分流。**它是唯一的登记处**：加事件在这张表里加一行（测试与目录对齐）。"""


def route_of(event_type: str) -> Route:
    """一条事件类型该走哪一路:表里没有即 :data:`DEFAULT_ROUTE`,不静默丢弃."""
    return ROUTES.get(event_type, DEFAULT_ROUTE)


def failure_hook(logger: logging.Logger) -> ErrorHook:
    """造一个总线的失败钩子:订阅者抛错只写诊断,不进落盘与反馈.

    它是"通知层自己的故障",不是"发生过的事实",故不落盘,也不推给反馈那一侧;
    钩子自身抛错由总线兜住(那边同样不回流写路径).
    """

    def report(event: Event, handler: Handler, error: Exception) -> None:
        """记一句:哪个事件,哪个订阅者,抛了什么."""
        with contextlib.suppress(Exception):
            logger.warning(
                "事件处理器抛错，已隔离：type=%s subject=%s handler=%s error=%r",
                event.type,
                event.subject,
                getattr(handler, "__qualname__", handler),
                error,
            )

    return report


def _open(path: str | Path) -> TextIO:
    r"""开落盘的文件:追加,行缓冲,父目录不在即建.

    行缓冲是刻意的:日志的价值在"事后还能读到",故一行写完即 flush 给系统,不攒在
    缓冲区里等进程退出.**不做 `fsync`**:崩在最后几行上是可以接受的代价,而每条事件
    一次同步落盘会把写路径拖慢.文本模式一律 `\n`,故换行不随平台变.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target.open("a", encoding="utf-8", buffering=1, newline="\n")


def _record(event: Event) -> dict[str, object]:
    """一条事件折成一行 JSON 的字段:**版本 + 事件自己的六项**.

    `data` 必须是能进 JSON 域的值(加事件的门槛,见 `catalog`);真遇到编不出去的,
    落盘写 `repr` 兜底——记下一行不完美的记录,强过在写路径上抛一个异常.
    """
    return {
        "v": LOG_VERSION,
        "id": event.id,
        "time": event.time,
        "type": event.type,
        "source": event.source,
        "subject": event.subject,
        "data": event.data,
    }


def _line(event: Event) -> str:
    """一条事件折成给人看的一行:类型,对象与载荷."""
    return f"事件 {event.type} subject={event.subject!r} data={event.data!r}"


__all__ = [
    "DEFAULT_ROUTE",
    "LOGGER_NAME",
    "LOG_VERSION",
    "ROUTES",
    "EventLog",
    "Feedback",
    "Route",
    "Sink",
    "failure_hook",
    "route_of",
]

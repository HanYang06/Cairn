# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""事件总线：订阅、按注册顺序投递、异常隔离。

本层只做**扇出通知**，不做决策：解析事件包、决定做什么、执行动作属 ``parser`` 的职责。
三条行为契约是刻意钉死的：

1. **投递顺序 = 注册先后**（同一事件类型内）。这一点由本实现自己给出，不建立在
   任何第三方"顺序未定义"的行为之上。
2. **异常隔离**：某个订阅者抛错不中断其余订阅者，失败清单由 :meth:`Bus.emit` 交回调用方；
   通知路径**绝不**把异常抛回写路径——写成功就是写成功。
3. **订阅生命周期显式**：句柄 :meth:`Subscription.cancel` 或作上下文管理器撤订；
   不做弱引用自动摘除——弱引用会让闭包与局部函数静默失效，"发了没人收到"是最难查的一类故障。

并发：本层不加锁。内核约定写路径单线程；跨线程投递（例如回投 UI 主线程）由适配层排队。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Self

from .events import Event

if TYPE_CHECKING:
    from types import TracebackType

Handler = Callable[[Event], Any]
"""订阅者：收到一个事件，返回值**不被使用**（通知语义，不取回执）。"""

ErrorHook = Callable[[Event, Handler, Exception], None]
"""失败钩子：某个订阅者抛错时按序调用；日志引擎接在这里。"""


@dataclass(frozen=True, slots=True)
class HandlerError:
    """一次投递失败：哪个事件、哪个订阅者、抛出什么。

    Attributes:
        event: 正在投递的事件。
        handler: 抛错的订阅者。
        error: 它抛出的异常。
    """

    event: Event
    handler: Handler
    error: Exception


@dataclass(slots=True)
class Subscription:
    """订阅句柄：撤销这一份订阅，或作为上下文管理器在退出时自动撤销。

    Attributes:
        event_type: 订阅的事件类型。
        handler: 订阅者。
    """

    handler: Handler
    event_type: str
    _bus: Bus = field(repr=False)

    def cancel(self) -> bool:
        """撤销订阅；返回是否确实撤掉一份（重复撤销返回 ``False``）。"""
        return self._bus.unsubscribe(self.event_type, self.handler)

    def __enter__(self) -> Self:
        """进入 ``with``：订阅保持有效。"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """退出 ``with``：无论是否异常都撤销订阅。"""
        self.cancel()


class Bus:
    """事件总线：一张"事件类型 → 订阅者"的有序表加一次同步投递。

    同一处理器重复订阅同一类型只算一份（按对象相等性判重，绑定方法也适用）；
    订阅生命周期与总线一致，不做垃圾回收联动。
    """

    def __init__(self, *, on_error: ErrorHook | None = None) -> None:
        """建立总线。

        Args:
            on_error: 失败钩子；不传则失败只记进 :meth:`emit` 的返回值。
        """
        self._on_error = on_error
        self._handlers: dict[str, dict[Handler, Subscription]] = {}

    def subscribe(self, event_type: str, handler: Handler) -> Subscription:
        """订阅事件类型，返回撤销句柄。

        重复订阅返回同一份句柄，不会造成重复投递。
        """
        handlers = self._handlers.setdefault(event_type, {})
        existing = handlers.get(handler)
        if existing is not None:
            return existing
        subscription = Subscription(handler=handler, event_type=event_type, _bus=self)
        handlers[handler] = subscription
        return subscription

    def unsubscribe(self, event_type: str, handler: Handler) -> bool:
        """按类型与处理器撤销订阅；没订过则返回 ``False``。"""
        handlers = self._handlers.get(event_type)
        if handlers is None or handler not in handlers:
            return False
        del handlers[handler]
        if not handlers:
            del self._handlers[event_type]
        return True

    def emit(self, event: Event) -> tuple[HandlerError, ...]:
        """按注册顺序通知该类型的全部订阅者，返回失败清单（可能为空元组）。

        投递前对订阅表取快照：订阅者在处理过程中自行增删订阅，只影响下一次投递。
        任何订阅者抛错都只记入返回值并调用失败钩子，不中断其余订阅者、不向调用方抛出。
        """
        handlers = self._handlers.get(event.type)
        if not handlers:
            return ()
        failures: list[HandlerError] = []
        for handler in tuple(handlers):
            try:
                handler(event)
            except Exception as error:  # noqa: BLE001 — 通知路径的异常隔离就是本方法的本职
                failures.append(HandlerError(event=event, handler=handler, error=error))
                if self._on_error is not None:
                    self._on_error(event, handler, error)
        return tuple(failures)

    def receivers(self, event_type: str) -> int:
        """该事件类型当前的订阅数（诊断与测试用）。"""
        return len(self._handlers.get(event_type, {}))


__all__ = ["Bus", "ErrorHook", "Handler", "HandlerError", "Subscription"]

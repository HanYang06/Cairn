# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""事件对象声明.

字段命名借 CloudEvents 的口径(``id`` / ``source`` / ``type`` / ``time`` / ``subject`` /
``data``),**不代表实现该规范**:本层没有 ``specversion``,``datacontenttype`` 一类的约束,
也不做传输绑定;借名只为让日志格式与将来的网络侧少一次字段翻译.

事件是**瞬时通知**:不进存储,不承载业务流转.流过去的事件由 `core/event/logs.py` 记成
一份文本记录(可选的落盘,不算进存储);要追溯的**业务语义**则是领域活动日志(另一套,
属领域层).投递顺序与异常策略由总线给出(见 ``bus``),事件对象自身只负责说清发生了什么.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


def _event_id() -> str:
    """事件自身的标识(32 位十六进制):供日志串联,将来供网络侧判重."""
    return uuid4().hex


def _now_ms() -> int:
    """事件产生时间(unix 毫秒)."""
    return time.time_ns() // 1_000_000


@dataclass(frozen=True, slots=True)
class Event:
    """事件对象:一次已经发生的事的不可变描述.

    冻结是刻意的:通知发出去之后不得再被改写,否则先收到的订阅者与后收到的
    (顺序不保证)会看到两份不同的事实.

    Attributes:
        type: 事件类型,如 ``object.put``;订阅与路由都以它为键.
        source: 发出者的可读标识,如 ``core.storage``.
        subject: 事件针对的对象标识(ID 的唯一标识形态);无对象的事件留空.
        data: 载荷;结构由 ``type`` 决定,内核不解释.
        id: 事件自身标识.
        time: 事件产生时间(unix 毫秒).与 ID 的 ``birth_time``(纳秒)不是同一用途.
    """

    type: str
    source: str = ""
    subject: str = ""
    data: Any = None
    id: str = field(default_factory=_event_id)
    time: int = field(default_factory=_now_ms)


__all__ = ["Event"]

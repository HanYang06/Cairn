# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""时钟:内核内部时间只有两个口径,都从这里出.

**内部时间统一 unix 毫秒整数**(全库口径:索引列,事件 `time`,落盘时刻);
唯一的例外是 ID 的 `birth_time`,用纳秒——那是作者的口径,它随身份进索引库那一行,
不随载体走.两处若各写各的 `time.time()`,迟早出现"同一个时刻两种精度"的漂移.
"""

from __future__ import annotations

import time


def now_ms() -> int:
    """当前时间(unix 毫秒):索引列,事件与落盘时刻都用它."""
    return time.time_ns() // 1_000_000


def now_ns() -> int:
    """当前时间(unix 纳秒):只有 ID 的 `birth_time` 用它."""
    return time.time_ns()


__all__ = ["now_ms", "now_ns"]

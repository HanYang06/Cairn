# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""事件目录：内核当前会发出的事件类型。

事件是**瞬时通知**（不进存储、不承载业务流转）。每加一种事件在**这里**登记，
发布方与订阅方都引常量、不写裸字符串——两处字面量一旦分叉，就是"发了没人收到"
那类最难查的故障。

目录当前只有两条，都来自存储的写路径（`core/storage/engine.py`）。加事件的门槛：
先问"是不是一次通知"，再问"有没有人订"；只为了"多发一条"的事件，不加。加事件时
**两处一并改**：这里是类型常量，`core/event/logs.py` 的分流表加一行（用例保证两处对齐）。

**事件的 `data` 必须是能进 JSON 域的值**：事件日志要把它写成一行 JSON（`logs.py`），
将来的网络侧也要它；编不出去的载荷不进事件的 `data`。
"""

from __future__ import annotations

OBJECT_PUT = "object.put"
"""块落盘之后发出的通知：`subject` 是块身份，`data` 里带表名与内容地点。

**一条块记录落成一次**：同一个块改了字段再存一次，是同一身份上的又一次落盘，
故再发一条——订阅方按 `subject` 归并即可，内核不做去重。
"""

OBJECT_DELETED = "object.deleted"
"""块被摘掉之后发出的通知：`subject` 是块身份。内容面不动，等 GC 回收。"""

ALL: tuple[str, ...] = (OBJECT_PUT, OBJECT_DELETED)
"""目录里**全部**事件类型。

订阅"全都要"的一方用它，而不是自己列一串：加事件时只改目录这一处，漏不掉。
"""

__all__ = ["ALL", "OBJECT_DELETED", "OBJECT_PUT"]

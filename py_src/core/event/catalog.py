# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""事件目录：内核当前会发出的事件类型。

事件是**瞬时通知**（不进存储、不承载业务流转）。每加一种事件在**这里**登记，
发布方与订阅方都引常量、不写裸字符串——两处字面量一旦分叉，就是"发了没人收到"
那类最难查的故障。

目录当前只有两条，都来自存储的写路径。加事件的门槛：先问"是不是一次通知"，
再问"有没有人订"；只是为了"顺手发一条"的事件，不加。
"""

from __future__ import annotations

OBJECT_PUT = "object.put"
"""块落盘之后发出的通知：`subject` 是块身份，`data` 里带 body 地址与类型。"""

OBJECT_DELETED = "object.deleted"
"""块被摘掉之后发出的通知：`subject` 是块身份。内容面不动，等压实回收。"""

__all__ = ["OBJECT_DELETED", "OBJECT_PUT"]

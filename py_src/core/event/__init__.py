# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""事件引擎：事件对象、目录与总线。

事件是**瞬时通知**：不进存储、不承载业务流转。本层只做**扇出通知**——按注册顺序投递、
异常隔离，没有解析器也没有中介者（判据见 `catalog.py` 的门槛与
`.agents/skills/memory/references/decisions/内核.md`）。写路径发的那两条事件在
`core/storage/engine.py`，订阅与装配在 `core/init.py`。
"""

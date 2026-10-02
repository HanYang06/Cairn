# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""内核自己那组配置声明。

**各管各的**：谁要用配置，谁在自己包里声明——这个模块只声明内核自身的键
（日志级别这类），存储那组在 `core/storage/conf.py`。

声明即事实：这里的默认值只写这一份，值文件由引擎展开；改值改 `config/settings.json`，
改默认值改这里。`type=` 与默认值不符会被引擎在声明期拦下。
"""

from __future__ import annotations

from core.conf import conf

conf("core.log.level", "WARNING", type=str, doc="内核日志级别：导入内核时设到 cairn 这族记录器")

__all__: list[str] = []

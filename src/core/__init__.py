# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""核心层：**内核**（配置引擎 + 信号引擎 + 存储 + 类型地基）。

对外：

- `core.core.Core`：内核本体（单例；两张对象表 + 引擎挂载点 + 最小 API）
- `core.signal.Signal`：信号与事件处理引擎
- `core.storage`：存储实现（桶 / 块 / 目录）与它的引擎角色
- `core.conf`：配置引擎（声明即事实，两个投影落盘；各模块的配置写在自己的声明模块里）
- `core.types`：类型地基（错误 / 标识符 / 类型表 / 标注 / 事件数据结构）

导入本包即**按配置上好日志级别**（`core.log.level`，管 ``core.*`` 这一族的 logger；
处理器仍由应用自己配，库不劫持 root）。
"""

from __future__ import annotations

import logging

from .conf import ConfEngine, ConfigError
from .conf.params import conf as _kernel_conf
from .core import Core, Managed
from .signal import Signal
from .types import (
    CairnError,
    CorruptObjectError,
    ObjectInfo,
    ObjectNotFoundError,
)


def _kernel_log_level() -> int:
    """`core.log.level` → 日志级别整数。

    ``setLevel`` 对级别名**大小写敏感**（``"warning"`` 会抛 ``ValueError``），
    故先归一为大写再查；认不出时退回 ``INFO``。

    读这一条会经引擎：键缺失时引擎会**一并补写**配置文件的默认值（引擎的既有口径），
    若部署在只读目录，补写会抛 ``OSError``——那也不该让 ``import core`` 失败，
    故与配置错误一并兜住。**导入期不该因一条配置值而崩**。
    """
    try:
        declared = str(_kernel_conf.log_level)
    except (ConfigError, OSError):
        return logging.INFO
    return logging.getLevelNamesMapping().get(declared.strip().upper(), logging.INFO)


logging.getLogger("core").setLevel(_kernel_log_level())

__all__ = [
    "CairnError",
    "ConfEngine",
    "Core",
    "CorruptObjectError",
    "Managed",
    "ObjectInfo",
    "ObjectNotFoundError",
    "Signal",
]

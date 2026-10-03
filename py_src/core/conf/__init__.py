# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""配置引擎包.

用法就一句:``from core.conf import conf``,然后哪儿都能用
    conf("storage.pack.slot_bytes", 65536, type=int, doc="槽长")  # 声明
    slot = conf("storage.pack.slot_bytes")                        # 取值

形状与注意事项见 :mod:`core.conf.registry` 的模块说明.
"""

from __future__ import annotations

from core.conf.registry import (
    CONFIG_DIRNAME,
    ROOT_ENV,
    SCHEMA_DIRNAME,
    VALUE_FILENAME,
    CallSite,
    Config,
    Declared,
    SyncResult,
    conf,
)

__all__ = [
    "CONFIG_DIRNAME",
    "ROOT_ENV",
    "SCHEMA_DIRNAME",
    "VALUE_FILENAME",
    "CallSite",
    "Config",
    "Declared",
    "SyncResult",
    "conf",
]

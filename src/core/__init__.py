# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""Cairn 内核包。

导入本包即声明内核自己那组配置、并把 `core.log.level` 设到 `core.*` 这族记录器上
（见 `core/conf/params.py`）。**不劫持 root**：只动自己这一族，别人的日志级别不受影响；
级别名认不出来（或只读部署下取不到值）就退回默认，不因此让导入失败。
"""

from __future__ import annotations

import logging

import core.conf.params  # noqa: F401 — 导入即声明内核自己那组配置（声明是事实源）
from core.conf import conf

_DEFAULT_LEVEL = logging.WARNING
"""级别取不出来时的退路：与 `core.log.level` 的声明默认值同口径。"""


def _apply_log_level() -> None:
    """把配置里的级别名设到 `core.*` 这族记录器；认不出来就退回默认并记一句。"""
    try:
        name = str(conf("core.log.level"))
    except Exception:  # noqa: BLE001 — 导入期不因配置出错而失败（含只读部署与坏文件）
        logging.getLogger(__name__).debug("读不到 core.log.level，退回默认级别")
        level = _DEFAULT_LEVEL
    else:
        level = logging.getLevelNamesMapping().get(name.upper(), _DEFAULT_LEVEL)
    logging.getLogger("core").setLevel(level)


_apply_log_level()

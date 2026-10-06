# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""Cairn 内核包.

导入本包即声明内核自己那组配置,并把 `core.log.level` 设到 `cairn` 这族记录器上
(见 `core/params.py`).**不劫持 root**:只动自己这一族,别人的日志级别不受影响;
级别名认不出来(或只读部署下取不到值)就退回默认,不因此让导入失败.
"""

from __future__ import annotations

import logging

import core.params  # noqa: F401 — 导入即声明内核自己那组配置(声明是事实源)
from core.conf import conf

_FAMILY = "cairn"
"""内核日志记录器的族根：`cairn.kernel` / `cairn.conf` / `cairn.events` / `cairn.sidecar`
都在它下面，故级别设在这一处，整族一起动。"""

_DEFAULT_LEVEL = logging.WARNING
"""级别取不出来时的退路：与 `core.log.level` 的声明默认值同口径。"""

_LOGGER = logging.getLogger("cairn.core")
"""本模块自己的记录器：与其余内核记录器同族，故级别旋钮管得到它。"""


def _apply_log_level() -> None:
    """把配置里的级别名设到 `cairn` 这族记录器;认不出来就退回默认并记一句."""
    try:
        name = str(conf("core.log.level"))
    except Exception:  # noqa: BLE001 — 导入期不因配置出错而失败(含只读部署与坏文件)
        _LOGGER.debug("读不到 core.log.level，退回默认级别")
        level = _DEFAULT_LEVEL
    else:
        level = logging.getLevelNamesMapping().get(name.strip().upper(), _DEFAULT_LEVEL)
    logging.getLogger(_FAMILY).setLevel(level)


_apply_log_level()

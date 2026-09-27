# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""测试根的共享装配。

内核是**单例**（作者定的工程约束），所以测试不能"每例一个新内核"；
存储与引擎是**可替换挂件**，每例挂一份临时库即可互不串味。

域与数据类的类型登记**不需要在这里做**：域服务继承 `Managed` 时父类已替它登记
（`__init_subclass__` → `Core.register_type`），数据类由 `Block` 那条链登记。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core.core import Core
from core.storage import Storage
from feature import Note, Project

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = ["make_kernel"]


def make_kernel(tmp_path: Path) -> Core:
    """装一个连到临时库的内核：挂引擎 + 挂存储 + 建域服务。"""
    core = Core()
    core.mount("storage", Storage.open(tmp_path / "vault"))
    Note(core)
    Project(core)
    return core


@pytest.fixture
def core(tmp_path: Path) -> Iterator[Core]:
    """测试用内核：每个用例一份临时库；用例结束关库，释放上次挂上的连接与文件句柄。

    内核实例本身是单例，挂件可换；故清理只能是**关掉当前挂件**。
    """
    kernel = make_kernel(tmp_path)
    yield kernel
    kernel.close()

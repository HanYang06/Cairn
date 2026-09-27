# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from PySide6.QtWidgets import QMainWindow

from app.win import CairnApp
from app.win.backend import fmt_time
from core import CairnError
from tests.conftest import make_kernel
from ui_tools.core.qt import build_window

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.usefixtures("qapp")


def test_app_builds_window(tmp_path: Path) -> None:
    core = make_kernel(tmp_path)

    app = CairnApp(core)
    window = build_window(app)

    assert isinstance(window, QMainWindow)
    core.close()


def test_app_open_creates_then_loads(tmp_path: Path) -> None:
    root = tmp_path / "Core"

    CairnApp.open(root).close()  # 不存在 → 创建
    CairnApp.open(root).close()  # 已存在 → 加载


def test_app_open_refuses_a_library_it_does_not_know(tmp_path: Path) -> None:
    """开库遇到**不认识的库**要 fail closed，且不得掩盖成"库已存在"之类的别的话。"""
    root = tmp_path / "Core"
    root.mkdir()
    stranger = sqlite3.connect(str(root / "catalog.db"))
    stranger.execute("CREATE TABLE strangers(x INTEGER)")
    stranger.commit()
    stranger.close()

    with pytest.raises(CairnError, match="不接管"):
        CairnApp.open(root)


def test_fmt_time_tolerates_bad_values() -> None:
    assert fmt_time(0) == ""
    assert fmt_time(-5) == ""
    assert fmt_time(10**20) == ""  # 超出 datetime 范围不崩

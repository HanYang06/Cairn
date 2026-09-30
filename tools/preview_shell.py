# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""离屏把壳渲染成 PNG，用于自检外观（开发工具，不参与产品）。

**当前不可运行**：它依赖的 `app` 与 `ui_tools` 两层在 2026-09-29 的内核重建里被整条删除
（见 `.agents/skills/memory/progress.md`「内核重建」）。文件留着当参考，
待 UI 外壳重建后修回；`pyproject.toml` 的 mypy 覆盖里为它开了豁免，修回时请一并摘掉。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from app import Feature  # noqa: E402
from app.win import CairnApp  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from ui_tools.core.cardview import CardStageView  # noqa: E402
from ui_tools.core.qt import build_window  # noqa: E402

from core import Core  # noqa: E402

_SAMPLES: list[tuple[str, str]] = [
    ("行身份与区间样式", "一行 = 一段。样式是叠加层，行 id 稳定，所以不拆 body、也没有下标漂移。"),
    ("Cairn · 内核", "桶 / 块 / 内容池 / 版本引擎；UI 不感知存储实现。"),
    ("捕捉与专注", "写的时候眼里只有笔记；整理是主动切出去的动作。"),
    ("UI 根布局", "顶带 / 舞台 / 任务栏；笔记与项目同构，靠镜头筛选。"),
    ("版本 = 反向补丁", "补丁脱离当前块上下文即失效；压实就是永久遗忘。"),
    ("组与嵌套", "组是块，有自己的 gid；可无限嵌套，顺序即显示顺序。"),
    ("画板上的连线", "走线派生，只存图形下标 + 线型。"),
    ("内容寻址去重", "同 body 只存一份；描述进 attrs，不参与去重。"),
    ("P2P 联邦（远期）", "服务器可选、公私自决；网络是增强层，不是本体。"),
]


def main() -> int:
    """渲染卡片 / 详细两种密度各一张 PNG。"""
    app = cast("QApplication", QApplication.instance() or QApplication([]))
    app.setFont(QFont("Microsoft YaHei UI", 10))
    out = Path(__file__).resolve().parents[1] / "build" / "mockups"
    out.mkdir(parents=True, exist_ok=True)

    root = out / "preview_vault"
    core = Core()
    core.open(root)
    notes = Feature(core).Note
    if not notes.list_notes():
        for title, body in _SAMPLES:
            notes.create(body, title=title)

    cairn = CairnApp(core)
    cairn.theme.apply(app)
    window = build_window(cairn)
    window.resize(1200, 780)
    window.grab()
    window.grab().save(str(out / "shell_cards.png"))

    stage = window.findChild(CardStageView, "stage")
    if stage is not None:
        stage.set_dense(dense=True)
        window.grab().save(str(out / "shell_details.png"))

    core.close()
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

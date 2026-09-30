# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""词表的一份硬契约：**只认得部分的进程，不该把整份词表削成它认得的那几条**。

这是实测过的坑：一份只导入 `core` 的进程退出时，会把 `storage.*` 那几条从
`config/schema/settings.json` 里抹掉——"我没加载到"被当成了"这条配置没有了"。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from core.conf import Config

if TYPE_CHECKING:
    from pathlib import Path


def _vocabulary(root: Path) -> dict[str, object]:
    """读盘上那份词表。"""
    raw = (root / "schema" / "settings.json").read_text(encoding="utf-8")
    parsed: dict[str, object] = json.loads(raw)
    return parsed


def test_a_partial_process_does_not_shrink_the_vocabulary(tmp_path: Path):
    """两份声明各写一半，先全后少：词表该是两者的并集，不是后者的那份。"""
    root = tmp_path / "config"

    full = Config(root=root)
    full("a.one", 1, type=int, doc="第一条")
    full("a.two", 2, type=int, doc="第二条")
    full.sync()

    partial = Config(root=root)
    partial("a.one", 1, type=int, doc="第一条")
    partial.sync()

    properties = _vocabulary(root)["properties"]

    assert isinstance(properties, dict)
    assert set(properties) == {"a.one", "a.two"}, "只认得一半的进程不该把另一半抹掉"


def test_a_newer_declaration_still_wins(tmp_path: Path):
    """同一条键的说明变了：新算的顶掉旧条目，合并不能让词表停在旧版上。"""
    root = tmp_path / "config"

    before = Config(root=root)
    before("a.one", 1, type=int, doc="旧说明")
    before.sync()

    after = Config(root=root)
    after("a.one", 1, type=int, doc="新说明")
    after.sync()

    properties = _vocabulary(root)["properties"]

    assert isinstance(properties, dict)
    assert properties["a.one"]["description"] == "新说明"

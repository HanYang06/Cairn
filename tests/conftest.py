# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""全局夹具：把测试的写盘面挡在仓外。

**为什么必须挡**：装配内核时那份表声明文件会**由代码写出来**（设计篇 §8.2.1）——
路径问的是**配置根**，不给就落在仓根下的 `config/`。于是任何一个用到
`Kernel.create()` / `Kernel.open()` 的用例都会去写仓库里那份入库产物：
跑一次测试，工作区就多一行"测试类型"的表，而且**它随用例里定义了什么而变**。
这种污染不报错、只是慢慢把入库产物改花，最难发现。

故这里在每个用例开始前把**表声明文件的位置**改到一个临时目录（每个用例一份），
于是"改名 → 写文件 → 建库"整条链照跑，但落在仓外。

**只改这一个位置，不动配置根**：值文件与词表的路径（`config/settings.json` 与
`config/schema/settings.json`）是入库产物，`test_conf_projection.py` 要按**真实路径**
比对它们与声明是否分叉——把整个配置根搬走会把这组用例的判据一起搬空。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.storage.registry import TABLES_FILENAME


def repo_root() -> Path:
    """仓根：本文件在 `<仓根>/tests/` 下。"""
    return Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_tables_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把表声明文件落在临时目录里：测试不再写仓库那份入库产物。

    Returns:
        本用例的声明文件路径（还不存在；`sync` 建它，也可以先写好再让 `sync` 补）。
    """
    target = tmp_path / "tables.yaml"
    monkeypatch.setattr("core.storage.tables.tables_path", lambda: target)
    return target


@pytest.fixture
def shipped_tables_path() -> Path:
    """**入库的那份**声明文件：只读，供"入库产物与代码是否分叉"这类用例使用。

    上一条夹具把 `tables_path()` 指到临时目录（防污染），故要摸真文件就得显式要它。
    """
    return repo_root() / "config" / TABLES_FILENAME

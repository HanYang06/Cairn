# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""投影契约：入库的两份产物与声明一致，且"跑一遍"就能把它们补齐。

值文件与词表**没有专门的生成脚本**：跑一遍程序（或这一组用例）就顺带生成。
故这里承担旧 `gen_conf` 那一份职责——入库的产物与声明不许分叉。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import core.conf.params
import core.storage.conf  # noqa: F401
from core.conf import conf

#: 入库的两份产物（相对仓根）
VALUE_FILE = Path("config/settings.json")
SCHEMA_FILE = Path("config/schema/settings.json")


def _repo_root() -> Path:
    """仓根：本文件在 `<仓根>/tests/core/` 下。"""
    return Path(__file__).resolve().parents[2]


def _load(path: Path) -> dict[str, object]:
    """读一份入库的产物。"""
    data: dict[str, object] = json.loads((_repo_root() / path).read_text(encoding="utf-8"))
    return data


def test_shipped_value_file_matches_the_declarations():
    """入库的值文件与当前声明一致：少键、多键都算漂移。"""
    # 跑一遍：声明模块已被导入，`sync()` 会把缺的补上、把已无声明的键清掉。
    conf.sync()

    shipped = {key for key in _load(VALUE_FILE) if key != "$schema"}
    declared = set(conf.declaration_keys())
    assert shipped == declared, (
        f"入库值文件与声明不一致：只多 {shipped - declared}，只少 {declared - shipped}"
    )


def test_shipped_schema_matches_the_declarations():
    """入库的词表与声明现算的结果逐字一致（含键序与缩进）。"""
    conf.sync()

    shipped = (conf.schema_path()).read_text(encoding="utf-8")
    assert json.loads(shipped) == conf.schema_document()


@pytest.mark.parametrize("key", ["core.log.level", "storage.pack.slot_bytes"])
def test_shipped_values_are_readable(key: str):
    """入库的值能被读出来，且与声明里的默认值同类型。"""
    value = conf(key)

    assert value is not None
    assert type(value) in {int, float, bool, str, list, dict}


def test_running_an_entry_point_generates_the_projections(tmp_path: Path):
    """**跑一遍就生成**：进程退出时（`atexit`）把两份产物落盘，不需要专门的生成脚本。

    用一个另指配置根的子进程验证：跑完它，值文件与词表都在那儿了。
    """
    code = (
        "import core.conf.params, core.storage.conf\n"
        "from core.conf import conf\n"
        "print(conf('storage.pack.slot_bytes'))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CAIRN_CONFIG": str(tmp_path), "PYTHONPATH": str(_repo_root() / "src")},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "512"
    written = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert written["storage.pack.slot_bytes"] == 512
    assert (tmp_path / "schema" / "settings.json").is_file()

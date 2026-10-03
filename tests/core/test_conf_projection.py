# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""投影契约:入库的两份产物与声明一致,且"跑一遍"就能把它们补齐.

值文件与词表**没有专门的生成脚本**:跑一遍程序(或这一组用例)就顺带生成.
故这里承担旧 `gen_conf` 那一份职责——入库的产物与声明不许分叉.

**声明是按包收的**:内核自己那几条在 `core/conf/params.py`,存储那一层在
`core/storage/conf.py`.两份都导入之后,登记表才是完整的.
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
from core.storage.conf import body_history_depth, gc_auto_bytes

#: 入库的两份产物(相对仓根)
VALUE_FILE = Path("config/settings.json")
SCHEMA_FILE = Path("config/schema/settings.json")

#: 每一层各取一条做代表:只验一条,是因为"这条读得出来"这件事由引擎统一保证.
_SAMPLED_KEYS = ("core.log.level", "slot.max.byte.b", "pack.max.byte", "hub.default")


def _repo_root() -> Path:
    """仓根:本文件在 `<仓根>/tests/core/` 下."""
    return Path(__file__).resolve().parents[2]


def _load(path: Path) -> dict[str, object]:
    """读一份入库的产物."""
    data: dict[str, object] = json.loads((_repo_root() / path).read_text(encoding="utf-8"))
    return data


def test_shipped_value_file_matches_the_declarations():
    """入库的值文件与当前声明一致:少键,多键都算漂移."""
    conf.sync()

    shipped = {key for key in _load(VALUE_FILE) if key != "$schema"}
    declared = set(conf.declaration_keys())
    assert shipped == declared, (
        f"入库值文件与声明不一致：只多 {shipped - declared}，只少 {declared - shipped}"
    )


def test_shipped_schema_matches_the_declarations():
    """入库的词表与声明现算的结果逐字一致(含键序与缩进)."""
    conf.sync()

    shipped = (conf.schema_path()).read_text(encoding="utf-8")
    assert json.loads(shipped) == conf.schema_document()


@pytest.mark.parametrize("key", _SAMPLED_KEYS)
def test_shipped_values_are_readable(key: str):
    """入库的值能被读出来,且落在 JSON 的类型域里."""
    value = conf(key)

    assert value is not None
    assert type(value) in {int, float, bool, str, list, dict}


def test_the_ruling_added_two_policy_keys_to_the_storage_layer():
    """2026-10-02 裁定新增的两条策略键:正文保留世代数与自动回收阈值,各自读得出开箱值."""
    assert body_history_depth() == 1
    assert gc_auto_bytes() == 0


def test_running_an_entry_point_generates_the_projections(tmp_path: Path):
    """**跑一遍就生成**:进程退出时(`atexit`)把两份产物落盘,不需要专门的生成脚本.

    用一个另指配置根的子进程验证:跑完它,值文件与词表都在那儿了.
    导入路径由 `pyproject.toml` 的 `pythonpath` 给的是 `py_src`,故这里也指它——
    指错一处(`src` 那种写法)会让子进程 import 不到 `core`,而失败看起来像是配置的错.
    """
    code = (
        "import core.conf.params, core.storage.conf\n"
        "from core.conf import conf\n"
        "print(conf('slot.max.byte.b'))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "CAIRN_CONFIG": str(tmp_path),
            "PYTHONPATH": str(_repo_root() / "py_src"),
        },
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "512"
    written = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert written["slot.max.byte.b"] == 512
    assert written["hub.default"] == "main"
    assert (tmp_path / "schema" / "settings.json").is_file()

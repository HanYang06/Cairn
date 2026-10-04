# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""投影契约:入库的两份产物来自声明,且"跑一遍"就能重建它们.

值文件与词表**没有专门的生成脚本**:跑一遍程序就顺带生成.故这里承担"防漂移"那一份
职责,判据是**拿一个空目录里新生成的那一份当基准**:

- 读当前这份再跟声明比是自证——引擎在导入时就把缺的键补回去了,声明删掉一个键也看不出来;
- 从空目录重建再比,才量得到"入库的产物是不是这一版声明的样子".

比对口径:值文件按 `键 → 值` 比,词表按 `properties` 逐条等价(键 / 类型 / 说明 / 默认值).
不比字节——值文件里用户可能手动调过格式与键序,而那正是引擎刻意不动的部分.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import core.params  # 导入即声明内核自己那组配置(声明是事实源)
import core.storage.conf  # noqa: F401
from core.conf import conf
from core.storage.conf import body_history_depth, gc_auto_bytes

#: 入库的两份产物(相对仓根)
VALUE_FILE = Path("config/settings.json")
SCHEMA_FILE = Path("config/schema/settings.json")

#: 每一层各取一条做代表:只验一条,是因为"这条读得出来"这件事由引擎统一保证.
_SAMPLED_KEYS = ("core.log.level", "slot.max.byte.b", "pack.max.byte", "hub.default")

#: 值文件顶部的指令键:指向词表,不算配置项本身(与引擎的对账口径一致)
_DIRECTIVE = "$schema"

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load(path: Path) -> dict[str, object]:
    """读一份入库的产物."""
    data: dict[str, object] = json.loads((_REPO_ROOT / path).read_text(encoding="utf-8"))
    return data


def _properties(schema: dict[str, object]) -> dict[str, object]:
    """取词表里的 `properties` 一栏(没有则断言失败,不静默当成空)."""
    properties = schema.get("properties")
    assert isinstance(properties, dict), "词表里没有 properties"
    return properties


def _fresh_projection(tmp_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    """在一个**空目录**里跑一遍内核,交出它生成的值文件与词表.

    用子进程是因为引擎是单例且"起来之后不能改配置":同一个进程里换不了根,
    要拿"另一份根生成的样子"只能换一个进程.
    """
    code = (
        "import core, core.storage.conf\n"
        "from core.conf import conf\n"
        "print(conf('core.log.level'))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "CAIRN_CONFIG": str(tmp_path),
            "PYTHONPATH": str(_REPO_ROOT / "py_src"),
        },
    )
    assert result.returncode == 0, result.stderr
    values: dict[str, object] = json.loads((tmp_path / "settings.json").read_text("utf-8"))
    vocabulary: dict[str, object] = json.loads(
        (tmp_path / "schema" / "settings.json").read_text("utf-8")
    )
    return values, vocabulary


def test_the_shipped_value_file_is_what_a_fresh_run_generates(tmp_path: Path):
    """入库的值文件 == 一个空目录里跑一遍得到的那一份:少键,多键,值不同都算漂移."""
    generated, _vocabulary = _fresh_projection(tmp_path)

    shipped = _load(VALUE_FILE)

    assert {key: value for key, value in shipped.items() if key != _DIRECTIVE} == {
        key: value for key, value in generated.items() if key != _DIRECTIVE
    }, "入库的值文件已漂移：跑一次程序重新生成 config/settings.json"


def test_the_shipped_vocabulary_is_what_a_fresh_run_generates(tmp_path: Path):
    """入库的词表 == 一个空目录里跑一遍得到的那一份(键 / 类型 / 说明 / 默认值)."""
    _values, generated = _fresh_projection(tmp_path)

    shipped = _load(SCHEMA_FILE)

    assert _properties(shipped) == _properties(generated), (
        "入库的词表已漂移：跑一次程序重新生成 config/schema/settings.json"
    )


def test_shipped_values_are_readable():
    """入库的值能被读出来:每层取一条做代表."""
    for key in _SAMPLED_KEYS:
        value = conf(key)

        assert value is not None
        assert type(value) in {int, float, bool, str, list, dict}


def test_the_ruling_added_two_policy_keys_to_the_storage_layer():
    """2026-10-02 裁定新增的两条策略键:正文保留世代数与自动回收阈值,各自读得出开箱值."""
    assert body_history_depth() == 1
    assert gc_auto_bytes() == 0

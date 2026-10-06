# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""配置契约:内核只做"把引擎指到哪儿"这一件事,配置语义全部由 OnConf 承担.

故这里**不重复测 OnConf 的引擎**(它的对账,锁,后端各有自己的用例),只盯内核侧那两件
容易悄悄坏掉的事:

1. **配置根的决定权**:`CAIRN_CONFIG` 指的目录说了算,不给才是仓根下的 `config/`;
2. **引擎的日志不落终端**:OnConf 每次读都留一行,落到 stderr 会淹掉命令行与测试输出,
   故内核把它指向 `<root>/logs/config.log`.

两条都在子进程里验:引擎是**单例**且"起来之后不能改配置",同一个进程里换不了根,
要验"换根之后落在哪儿"只能换一个进程.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from core.conf import CONFIG_DIRNAME, ROOT_ENV, config_root

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PY_SRC = _REPO_ROOT / "py_src"

#: 子进程里跑的一段:导入内核(声明那一组键)后读一条,给退出时的落盘留出时机.
_RUN_KERNEL = (
    "import core, core.storage.conf\nfrom core.conf import conf\nprint(conf('core.log.level'))\n"
)


def _run(code: str, config_root_dir: Path) -> subprocess.CompletedProcess[str]:
    """在另指配置根的干净进程里跑一段代码(导入路径与 pytest 的 `pythonpath` 一致)."""
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            ROOT_ENV: str(config_root_dir),
            "PYTHONPATH": str(_PY_SRC),
        },
    )


def test_config_root_defaults_to_the_repo_config_dir(monkeypatch):
    """不给旋钮时,配置根是仓根下的 `config/`(值与事实源一起入库)."""
    monkeypatch.delenv(ROOT_ENV, raising=False)

    assert config_root() == _REPO_ROOT / CONFIG_DIRNAME


def test_config_root_follows_the_environment_knob(monkeypatch, tmp_path: Path):
    """`CAIRN_CONFIG` 是**找到配置的办法**,不是配置项:它一指,根就换过去."""
    monkeypatch.setenv(ROOT_ENV, str(tmp_path / "elsewhere"))

    assert config_root() == tmp_path / "elsewhere"


def test_a_fresh_process_generates_both_projections_at_the_knob(tmp_path: Path):
    """跑一遍就生成:值文件与词表都落在 `CAIRN_CONFIG` 指的目录里,不需要生成脚本."""
    result = _run(_RUN_KERNEL, tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "WARNING"

    values = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert values["$schema"] == "schema/settings.json"
    assert values["core.log.level"] == "WARNING"
    assert values["slot.max.byte.b"] == 512
    assert values["hub.default"] == "main"

    vocabulary = json.loads((tmp_path / "schema" / "settings.json").read_text(encoding="utf-8"))
    assert "core.log.level" in vocabulary["properties"]


def test_the_engines_log_goes_to_a_file_not_the_terminal(tmp_path: Path):
    """引擎每次读都留一行,故内核把它指向 `<root>/logs/config.log`,终端保持干净.

    这一条是回归:默认 `log="stderr"` 时,一次导入就会往 stderr 倒十几行记录,
    命令行与 pytest 的输出都被它淹掉.
    """
    result = _run(_RUN_KERNEL, tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stderr == "", "引擎的日志不该出现在 stderr"
    log = tmp_path / "logs" / "config.log"
    assert log.is_file()
    assert "[Read]" in log.read_text(encoding="utf-8")


def test_a_key_nobody_declared_is_cleaned_at_exit(tmp_path: Path):
    """值文件里**没被声明过**的键会在退出时被清掉:库的键空间由声明定,不由文件定.

    OnConf 的规则 1(事实有,期望没有 ⇒ 清理)在**提交点**执行,而进程退出就是提交点.
    这条与旧引擎相反(旧口径是"用户自加的键留着"),是换引擎时最该记住的一处语义变化:
    `config/settings.json` 不是"用户想写什么就写什么"的地方,往那里加自己的键留不住.
    """
    (tmp_path / "settings.json").write_text(
        json.dumps(
            {
                "$schema": "schema/settings.json",
                "core.log.level": "WARNING",
                "ghost.key": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run(_RUN_KERNEL, tmp_path)

    assert result.returncode == 0, result.stderr
    values = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert "ghost.key" not in values, "没声明过的键不该在提交点之后还留在值文件里"
    assert values["core.log.level"] == "WARNING", "声明过的键与它的值原样留着"

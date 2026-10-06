# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""标点门禁的守卫:**解析不了的文件不许被当成"干净"**.

这一条是补一个实测踩过的坑:文件已经坏了(AST 或 tokenize 过不去),而门禁照样报绿——
因为 `_scan` 解析失败就 `return []`,"我没法判断"被当成了"没有命中".坏文件从门禁底下
溜过去,而门禁恰恰是最该在那个时候拦住它的地方.

三件事分开验:检查模式**失败**,报告模式**只提醒**,`--fix` **一个字节都不动**坏文件.
测法沿用 `test_magic.py` 的先例:把 `scripts/` 下的脚本当模块装进来直接调 `main`
(它不是包,故走 `spec_from_file_location`),输出用 `capsys` 取——不另起进程.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    """把 `scripts/punct.py` 当模块装进来(它不是包,故走 `spec_from_file_location`)."""
    path = REPO_ROOT / "scripts" / "punct.py"
    spec = importlib.util.spec_from_file_location("punct_gate", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["punct_gate"] = module
    spec.loader.exec_module(module)
    return module


PUNCT = _load()

#: 探针文件放仓内的源码根下:本工具**只扫仓内**路径(仓外一律跳过),
#: 而 pytest 的 `--basetemp` 默认在系统临时目录里,故不用它.
_BROKEN = "py_src/_punct_probe_broken.py"
_BROKEN_WITH_TYPO = "py_src/_punct_probe_typo.py"


@pytest.fixture
def probes():
    """在本仓内造探针文件,用例结束删掉."""
    written: list[Path] = []

    def make(relative: str, body: str) -> Path:
        target = REPO_ROOT / relative
        target.write_text(body, encoding="utf-8")
        written.append(target)
        return target

    yield make
    for target in written:
        target.unlink(missing_ok=True)


def test_a_file_that_does_not_parse_fails_the_gate(probes, capsys: pytest.CaptureFixture[str]):
    """AST 解析不了的文件:检查模式必须失败,并把那个文件报出来."""
    probes(_BROKEN, "def broken(\n")

    assert PUNCT.main([_BROKEN]) == 1, "解析不了的文件不该让门禁报绿"
    captured = capsys.readouterr().out
    assert _BROKEN in captured
    assert "解析不了" in captured


def test_the_report_mode_mentions_it_without_blocking(probes, capsys: pytest.CaptureFixture[str]):
    """报告模式是过渡档:有命中都不阻断,解析失败更不该升成失败——但必须打出来."""
    probes(_BROKEN, "def broken(\n")

    assert PUNCT.main([_BROKEN, "--report"]) == 0
    captured = capsys.readouterr().out
    assert _BROKEN in captured
    assert "不阻断" in captured


def test_fix_leaves_a_file_it_cannot_parse_untouched(probes):
    """`--fix` 只动有命中的文件:解析不了的那个连一个字节都不碰.

    探针的构造要点:AST 过得去(字符串被当成一个表达式语句),而 tokenize 过不去
    (未闭合的三引号),于是它既有"待换的全角标点",又落进"解析不了"那一边——
    正好验"不碰".
    """
    body = '"""开头（全角括号）\n\n没有收尾的三引号\n'
    target = probes(_BROKEN_WITH_TYPO, body)

    assert PUNCT.main([_BROKEN_WITH_TYPO, "--fix"]) == 0
    assert target.read_text(encoding="utf-8") == body, "解析不了的文件不该被就地改写"

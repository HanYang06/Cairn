# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""魔法门禁的契约:**豁免表说了算,比例只用来防涨**.

本文件钉四件事:

- **表里没有的 dunder 一律算越界**(含看起来无害的 `__getattr__`);
- **`__init__` 不算魔法**:它是正常写法,算进去只会把比例搅成噪音;
- **同名重载只算一次**:`__get__` 有三个签名(两个 `@overload`),那还是一个方法;
- **比例按类数算**,且只在超过上限时才失败.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    """把 `scripts/magic.py` 当模块装进来(它不是包,故走 `spec_from_file_location`)."""
    path = REPO_ROOT / "scripts" / "magic.py"
    spec = importlib.util.spec_from_file_location("magic_gate", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["magic_gate"] = module
    spec.loader.exec_module(module)
    return module


MAGIC = _load()


def _write(tmp_path: Path, body: str) -> Path:
    """往临时目录里写一个模块,返回它的路径."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "sample.py"
    target.write_text(body, encoding="utf-8")
    return target


def test_a_dunder_outside_the_table_is_reported(tmp_path: Path):
    """表里没有的 dunder 算越界——`__getattr__` 也不行."""
    root = _write(
        tmp_path,
        "class A:\n"
        "    def __getattr__(self, name: str) -> object:\n"
        "        raise AttributeError(name)\n",
    )

    findings, classes, using = MAGIC.scan((str(root.parent),))

    assert classes == 1
    assert using == 1, "它确实算「用了魔法」"
    assert [f.method for f in findings] == ["__getattr__"]


def test_a_dunder_in_the_table_passes(tmp_path: Path):
    """豁免表里的那些不报错:`__repr__` 这类是给人读的."""
    root = _write(
        tmp_path,
        "class A:\n    def __repr__(self) -> str:\n        return 'A'\n",
    )

    findings, _classes, using = MAGIC.scan((str(root.parent),))

    assert findings == []
    assert using == 1, "它仍然算「用了魔法」——只是被豁免了"


def test_init_does_not_count_as_magic(tmp_path: Path):
    """`__init__` 不算魔法:几乎每个类都有,算进去就没法看比例了."""
    root = _write(
        tmp_path,
        "class A:\n    def __init__(self) -> None:\n        self.x = 1\n",
    )

    findings, classes, using = MAGIC.scan((str(root.parent),))

    assert classes == 1
    assert using == 0
    assert findings == []


def test_overloads_of_one_dunder_count_once(tmp_path: Path):
    """同名重载只算一次:`__get__` 写了三个签名,那还是一个方法."""
    root = _write(
        tmp_path,
        "from typing import overload\n\n\n"
        "class A:\n"
        "    @overload\n"
        "    def __get__(self, instance: None, owner: type | None = ...) -> int: ...\n\n"
        "    @overload\n"
        "    def __get__(self, instance: object, owner: type | None = ...) -> str: ...\n\n"
        "    def __get__(self, instance: object | None, owner: type | None = None) -> object:\n"
        "        return 1\n",
    )

    findings, _classes, _using = MAGIC.scan((str(root.parent),))

    assert findings == [], "豁免表里有 __get__，故不该报"


def test_the_ratio_is_classes_using_magic_over_all_classes(tmp_path: Path):
    """比例按**类数**算:两个类里一个用了魔法,就是 0.50."""
    root = _write(
        tmp_path,
        "class A:\n"
        "    def __repr__(self) -> str:\n"
        "        return 'A'\n\n\n"
        "class B:\n"
        "    def __init__(self) -> None:\n"
        "        self.x = 1\n",
    )

    _findings, classes, using = MAGIC.scan((str(root.parent),))

    assert classes == 2
    assert using == 1
    assert using / classes == 0.5


def test_the_shipped_tree_stays_within_budget():
    """**本仓现状必须在预算内**:这是门禁真正要保的那条."""
    findings, classes, using = MAGIC.scan(MAGIC.SCAN_ROOTS)

    assert classes > 0, "扫不到类说明扫错了目录"
    assert findings == [], f"有越界的魔法：{[str(f) for f in findings]}"
    assert using / classes <= MAGIC.MAX_RATIO

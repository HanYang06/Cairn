# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""魔法用量门禁：**扫类上的 dunder，超范围即失败**。

口径见 `rules/references/quality.md` 的「魔法：少用、不滥用」。门禁做两件事：

1. **逐个方法名比对豁免表**（:data:`ALLOWED`）：表里没有的 dunder 一律失败——
   这是主要的那道闸，因为它挡的是"新写法"，而新写法不可能恰好落进豁免表；
2. **算比例并卡上限**（:data:`MAX_RATIO`）：用魔法的类占全部类的比例。

`__init__` **不算魔法**：它是正常写法（几乎每个类都有），算进去会把比例搅成噪音。

用法::

    uv run python scripts/magic.py --check      # 门禁（CI 与 pre-commit 用）
    uv run python scripts/magic.py --report     # 只报告，不判失败（看现状用）
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

SCAN_ROOTS = ("py_src",)
"""扫哪些源码根。"""

NORMAL_DUNDERS = frozenset({"__init__"})
"""**不算魔法**的那些：正常写法，不参与比例，也不进豁免表。"""

ALLOWED: dict[str, str] = {
    "__repr__": "诊断输出：排查时看得见对象是什么，可解释",
    "__len__": "一到 N 的窄语义（有几格、占几格）；比自造 `size()` 更好读",
    "__contains__": "`x in slot` 是 Python 的读法，自造 `has()` 反而绕",
    "__enter__": "`with` 上下文；进出成对可读，比手写 close 不易漏",
    "__exit__": "同上",
    "__set_name__": "描述符记自己的名字（PEP 487），不靠它就得反查 cls.__dict__",
    "__get__": '描述符协议：`title: str = Attr("")` 要同时给声明与裸值',
    "__set__": "同上",
    "__post_init__": "dataclass 的钩子；标准库调的，不是自造",
    "__call__": '配置面 `conf("键")` 本身就是取值动作',
    "__str__": "与 __repr__ 同类：给人看的文本",
    "__iter__": "转发迭代；`for x in body` 是正常读法",
}
"""**豁免表**：每个进门的 dunder 都要在这一行写清理由。

不在这里面的一律失败——包括看起来无害的 `__getattr__` / `__setattr__`。
要加，就在这儿加一行并写明理由；**那一步就是评审点**。
"""

MAX_RATIO = 0.30
"""用魔法的类 / 全部类的上限（`__init__` 不计）。

当前实测约 0.18，留出余量；它的作用是**防涨**，不是逼着现在去砍。
真要砍就砍到 0.15 再把这个数改小——门禁数字只许往下走。
"""


@dataclass(frozen=True, slots=True)
class Finding:
    """一处不该有的魔法。"""

    path: str
    owner: str
    method: str

    def __str__(self) -> str:
        """给人看的一行。"""
        return f"{self.path}:{self.owner}.{self.method}"


def scan(paths: tuple[str, ...]) -> tuple[list[Finding], int, int]:
    """扫一遍：返回（越界的魔法，类的总数，用到魔法的类数）。

    Args:
        paths: 要扫的源码根。

    Returns:
        三元组：越界清单、类的总数、用到魔法的类数（都按文件去重）。
    """
    findings: list[Finding] = []
    classes = 0
    using = 0
    for path in _python_files(paths):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            classes += 1
            names = _dunders(node)
            if names - NORMAL_DUNDERS:
                using += 1
            exceeded = sorted(names - NORMAL_DUNDERS - ALLOWED.keys())
            findings.extend(
                Finding(path=str(path), owner=node.name, method=method) for method in exceeded
            )
    return findings, classes, using


def main(argv: list[str]) -> int:
    """跑一次扫描；`--check` 判失败，`--report` 只报告。"""
    check = "--check" in argv
    findings, classes, using = scan(SCAN_ROOTS)
    ratio = using / classes if classes else 0.0
    print(
        f"[magic] 扫 {classes} 个类，{using} 个用到魔法（比例 {ratio:.2f}，上限 {MAX_RATIO:.2f}）"
    )
    if findings:
        print(f"越界的魔法 {len(findings)} 处（不在豁免表里）：")
        for finding in findings:
            print(f"  {finding}")
    if not check:
        print("（报告模式：不判失败）")
        return 0
    failed = False
    if findings:
        print("→ 失败：把理由补进 scripts/magic.py 的 ALLOWED，或改用正常写法。")
        failed = True
    if ratio > MAX_RATIO:
        print("→ 失败：用魔法的类太多，见 rules/references/quality.md「魔法」一节。")
        failed = True
    return 1 if failed else 0


def _python_files(paths: tuple[str, ...]) -> list[Path]:
    """源码根下全部 `.py` 文件，按路径排序。"""
    return sorted(path for root in paths for path in Path(root).rglob("*.py"))


def _dunders(node: ast.ClassDef) -> set[str]:
    """一个类里出现的全部 dunder **方法名**（同名重载只算一次）。"""
    names: set[str] = set()
    for item in node.body:
        if not isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if item.name.startswith("__") and item.name.endswith("__") and len(item.name) > 4:
            names.add(item.name)
    return names


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

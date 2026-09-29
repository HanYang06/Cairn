# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""配置投影的工程工具：扫声明、比投影、必要时写盘。

**声明是唯一事实来源**，这个工具只做三件事：

- **扫**：用 `ast` 找全仓的 ``conf("…")`` 调用点——只认字面量键，不执行任何模块。
  这也是"全仓只扫一个词"那条口径的落地：谁在用什么配置，扫一遍就有确定答案；
- **比**：`--check` 报出三处不齐——值文件里少了已声明的键、多了已无声明的键、词表没跟上；
- **写**：不带参数（或 `--write`）按扫描结果把**词表**重新投影一遍；值文件则由声明模块
  自己被 import 时补缺（引擎的默认通路），用户改过的值与用户自己加的键都不动。

用法::

    uv run python tools/gen_conf.py --check    # 防漂移门禁（CI 用）
    uv run python tools/gen_conf.py --write    # 重新投影词表
    uv run python tools/gen_conf.py            # 同上（写盘意图显式化）

未知参数一律报错退出：拼错成 `-check` 之类的写法若被当成"默认写盘"，就与"只看一眼"的意图对不上。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # 直接跑脚本时，`tools` 未必在导入路径上
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

# 导入即登记：**每加一个带配置的模块，在这里补一行**（声明写在各模块自己的 conf / params 里）。
# 扫描能发现新键，但发现不了默认值与说明——那份事实只有跑一遍声明才拿得到。
import core.conf.params  # noqa: E402
import core.storage.conf  # noqa: E402,F401
from core.conf import conf  # noqa: E402
from tools._iosafe import _say  # noqa: E402 — 仓根在 sys.path[0] 后即可导入

SCAN_ROOTS = ("src",)
"""扫描范围只含产品代码：测试与工具里的 `conf(...)` 运行时照用，但不进分发的词表。"""

_CALL_NAME = "conf"


def scan_keys(root: Path) -> dict[str, str]:
    """扫全仓的 ``conf("…")`` 调用点，返回「键 → 模块名」；不执行任何代码。

    只认**字面量**键：拼出来的键（`conf(prefix + ".level", …)`）扫不到，它由导入期登记兜住。
    这也意味着扫描"不全但不会错"——宁可漏报，也不猜。
    """
    found: dict[str, str] = {}
    for folder in SCAN_ROOTS:
        for source in sorted((root / folder).rglob("*.py")):
            if "__pycache__" in source.parts:
                continue
            try:
                tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            module = source.relative_to(root).with_suffix("").as_posix().replace("/", ".")
            for node in ast.walk(tree):
                key = _literal_key(node)
                if key is not None:
                    found.setdefault(key, module)
    return found


def _literal_key(node: ast.AST) -> str | None:
    """一个调用点是不是 ``conf("字面量")``；是就交出那个键，否则交出 `None`。"""
    if not isinstance(node, ast.Call) or not node.args:
        return None
    func = node.func
    if not (isinstance(func, ast.Name) and func.id == _CALL_NAME):
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def main(argv: list[str]) -> int:
    """`--check` 防漂移 / 写盘；未知参数报错退出。"""
    unknown = [arg for arg in argv if arg not in {"--check", "--write"}]
    if unknown:
        _say(f"未知参数 {unknown}：用法 `gen_conf.py [--check|--write]`（不带参数=写盘）")
        return 1
    scanned = scan_keys(ROOT)
    conf.reduce(scanned)
    declared = sorted(conf.declaration_keys())
    if not declared:
        _say('没有扫到任何配置声明：检查 `conf("…")` 的写法，或 SCAN_ROOTS 是否覆盖了那个目录')
        return 1
    elsewhere = sorted(entry.path for entry in conf.entries() if entry.path not in set(declared))

    known = conf.loaded_keys()
    missing = [path for path in declared if path not in known]
    stale = [path for path in sorted(known) if path not in declared and path not in set(elsewhere)]

    if "--check" in argv:
        problems = bool(missing or stale)
        for path in missing:
            _say(f"  值文件里少了已声明的键：{path}")
        for path in sorted(stale):
            reason = "扫不到它的声明（键是拼出来的？）" if path not in scanned else "已经没有声明了"
            _say(f"  值文件里多了键：{path}（{reason}）")
        if not conf.schema_path().is_file():
            problems = True
            _say(f"  词表不在：{conf.schema_path().relative_to(ROOT)}（跑 --write 生成）")
        if problems:
            _say("配置投影与声明不一致：跑 `uv run python tools/gen_conf.py --write` 重新投影")
            return 1
        _say(f"[gen_conf] {len(declared)} 个键：值文件与词表都与声明一致。")
        return 0

    result = conf.sync()
    _say(f"[gen_conf] 已投影 {len(declared)} 个键（扫描另见 {len(elsewhere)} 个未加载的声明）。")
    _say(f"[gen_conf] 值文件 {result.value_path.relative_to(ROOT)}：补 {len(result.added)} 处。")
    _say(f"[gen_conf] 词表 {result.schema_path.relative_to(ROOT)}：本轮重算。")
    for path in missing:
        _say(f"  待程序跑一次才会补上默认值：{path}")
    for path in sorted(stale):
        _say(f"  值文件里留着、声明已没有的键：{path}")
    for path in elsewhere:
        _say(f"  扫描到但本轮未加载的声明（其默认值不在词表里）：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

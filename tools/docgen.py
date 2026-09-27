# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""文档生成器：把**机器已有的单一事实源**投影成文档（开发工具，不参与产品）。

分工原则（见 `rules/references/docs.md`）：

- **能算的就不写**：配置参考页从 `schema/settings.json`（配置引擎的生成物）生成，不手抄；
- **能查的就不写**：docstring 覆盖率从 AST 直接量，进 CI 当门禁，防止以后悄悄烂掉。

用法：

    uv run python tools/docgen.py --write      # 重新生成 docs/reference/config.md
    uv run python tools/docgen.py --check      # 防漂移门禁（页面与词表不一致即失败）
    uv run python tools/docgen.py --coverage   # 只打印 docstring 覆盖率报告（报告模式）
    uv run python tools/docgen.py --coverage --gate   # 同上，并低于阈值即非零退出（门禁模式）

生成的文件自己带 SPDX 头与"勿手改"声明；正文**没有一句是手写的**——表来自词表，
说明文字来自本文件的模板常量（改口径改这里，不改正生成物）。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # 直接跑脚本时，`tools` 未必在导入路径上
    sys.path.insert(0, str(ROOT))

from tools._iosafe import _say  # noqa: E402 — 见上：先补路径再导入

#: 配置词表的单一事实源（配置引擎生成，勿手改）
SETTINGS_SCHEMA = ROOT / "schema" / "settings.json"

#: 生成出来的参考页
CONFIG_PAGE = ROOT / "docs" / "reference" / "config.md"

#: 公共 API 的 docstring 覆盖阈值（`--coverage` 用它给出达标 / 未达标判定；达标后接 CI）
DOCSTRING_MIN = 0.95

#: 覆盖率统计只看这四层（与 API 参考页一致）
DOCSTRING_ROOTS = ("core", "feature", "ui_tools", "app")

#: 不参与统计的模块（占位包 / 生成物）
_SKIPPED = ("app/linux",)

_PAGE_HEAD = """\
<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 配置项参考

!!! danger "本页由工具生成，请勿手改"

    由 `uv run python tools/docgen.py --write` 生成，表来自 **`schema/settings.json`**
    （配置引擎的生成物）。改口径请改生成器，改配置请改声明类；
    `--check` 已进 CI，漂移即失败。**手改这一页会在下一次生成时被抹掉。**

## 怎么读这张表

- **键** = 点分路径，写进 `config/<hub>/…` 的值文件里（用户改过的值永不覆写）。
- **归属** = 该键由哪个声明类定义（`x-cairn-owner`）——**谁用配置谁在自己包里声明**。
- **默认值** = 声明里给的默认；`—` 表示没有默认值（这时键丢了就报错，见下）。

## 取值三条（不猜、不自动修）

| 情形 | 行为 |
|---|---|
| 键在、值空 | **报错** |
| 键丢、有默认值 | **补回来**（只补缺失的键） |
| 键丢、没默认值 | **报错** |

## 全部配置项（{count} 条）

"""

_PAGE_TAIL = """
## 另见

- 用法契约与两个投影的由来：[配置引擎](../architecture/config.md)
- 值文件与词表分别落在 `config/<hub>/…` 与 `schema/<hub>/…`；总词表是 `schema/settings.json`。
- 格式常量（载体魔数、文件头长度、记录头布局这类改了会坏库的）**故意不进配置**，留在实现处。
- 想加一条配置：在**用到它的那个包**里声明（例：`src/core/storage/conf.py`），
  然后跑 `uv run python tools/gen_conf.py` 与 `uv run python tools/docgen.py --write`。
"""

Residue = tuple[str, int, int]


def read_settings() -> dict[str, Any]:
    """读总词表；缺文件直接报错（宁可失败，也不静默出一张空表）。"""
    if not SETTINGS_SCHEMA.is_file():
        raise FileNotFoundError(
            f"找不到配置词表 {SETTINGS_SCHEMA.relative_to(ROOT)}："
            "先跑 `uv run python tools/gen_conf.py` 重新生成投影"
        )
    data: dict[str, Any] = json.loads(SETTINGS_SCHEMA.read_text(encoding="utf-8"))
    return data


def _cell(value: Any) -> str:
    """把值渲染成一个 Markdown 单元格（`None` → `—`）。"""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "`true`" if value else "`false`"
    return f"`{value}`"


def _text(value: Any) -> str:
    """自由文本进单元格前的转义：`|` 会截断表格、换行会断开整张表。"""
    return str(value).replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def config_table(settings: dict[str, Any] | None = None) -> str:
    """由总词表渲染配置表（键 / 类型 / 默认值 / 说明 / 归属）。"""
    data = settings if settings is not None else read_settings()
    properties: dict[str, Any] = data.get("properties", {})
    lines = ["| 键 | 类型 | 默认值 | 说明 | 归属 |", "|---|---|---|---|---|"]
    for key in sorted(properties):
        spec: dict[str, Any] = properties[key] or {}
        lines.append(
            f"| `{key}` | `{spec.get('type', '—')}` | {_cell(spec.get('default'))} "
            f"| {_text(spec.get('description', '—'))} | `{_text(spec.get('x-cairn-owner', '—'))}` |"
        )
    return "\n".join(lines)


def render_page(settings: dict[str, Any] | None = None) -> str:
    """整页内容（含 SPDX 头）：模板 + 现算的表。"""
    data = settings if settings is not None else read_settings()
    count = len(data.get("properties", {}))
    return _PAGE_HEAD.format(count=count) + config_table(data) + "\n" + _PAGE_TAIL


def current_page() -> str:
    """磁盘上那一页的内容；不存在算空。"""
    return CONFIG_PAGE.read_text(encoding="utf-8") if CONFIG_PAGE.is_file() else ""


def _public_defs(source: Path) -> list[ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef]:
    """模块**顶层**与**类体内**的公共类 / 函数（`_` 开头的不算，与 API 参考的过滤一致）。

    **不递归进函数体**：`ast.walk` 会把函数内部的局部 `def` 也算作公共成员，
    而文档站（mkdocstrings 的 `show_if_no_docstring: false`）只渲染顶层与类成员——
    局部定义进分母只会把覆盖率稀释掉，缺口因此更难被发现。
    """
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    found: list[ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef] = []

    def collect(nodes: Iterable[ast.stmt]) -> None:
        for node in nodes:
            if isinstance(node, ast.ClassDef):
                if not node.name.startswith("_"):
                    found.append(node)
                collect(node.body)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and not (
                node.name.startswith("_")
            ):
                found.append(node)

    collect(tree.body)
    return found


def docstring_stats() -> tuple[int, int, list[Residue]]:
    """量公共 API 的 docstring 覆盖：返回 `(有 docstring, 总数, 缺口清单)`。"""
    documented = 0
    total = 0
    holes: list[Residue] = []
    for root in DOCSTRING_ROOTS:
        for source in sorted((ROOT / "src" / root).rglob("*.py")):
            rel = source.relative_to(ROOT / "src").as_posix()
            if any(rel.startswith(skip) for skip in _SKIPPED):
                continue
            count = missing = 0
            for node in _public_defs(source):
                count += 1
                if ast.get_docstring(node):
                    documented += 1
                else:
                    missing += 1
            total += count
            if missing:
                holes.append((rel, missing, count))
    return documented, total, holes


def coverage_ratio() -> float:
    """公共类 / 函数的 docstring 覆盖率（`--coverage --gate` 的判据）。"""
    documented, total, _holes = docstring_stats()
    return documented / total if total else 1.0


def coverage_report() -> str:
    """docstring 覆盖率报告（含缺口清单与阈值判定），供人看。"""
    documented, total, holes = docstring_stats()
    ratio = documented / total if total else 1.0
    verdict = "达标" if ratio >= DOCSTRING_MIN else f"未达阈值 {DOCSTRING_MIN:.0%}"
    lines = [
        f"[docgen] 公共类 / 函数 docstring 覆盖：{documented}/{total}（{ratio:.1%}，{verdict}）",
        (
            f"[docgen] 文档站里 {total - documented} 个公共成员因缺 docstring 被隐藏"
            "（mkdocstrings 的 `show_if_no_docstring: false`）。"
        ),
        "",
        "缺口最大的模块（未写 / 总数）：",
    ]
    for rel, missing, count in sorted(holes, key=lambda item: -item[1])[:15]:
        lines.append(f"  {rel}: {missing}/{count}")
    return "\n".join(lines)


def _gate() -> int:
    """防漂移门禁：生成物与词表不一致即失败。"""
    expected = render_page()
    actual = current_page()
    if expected == actual:
        _say(f"[docgen] {CONFIG_PAGE.relative_to(ROOT)} 与 schema/settings.json 一致。")
        return 0
    _say(f"[docgen] {CONFIG_PAGE.relative_to(ROOT)} 已漂移（与 schema/settings.json 不一致）。")
    _say("         跑 `uv run python tools/docgen.py --write` 重新生成。")
    return 1


def _write() -> int:
    """重新生成参考页；内容未变化时不改写文件，避免无谓的时间戳变更。"""
    expected = render_page()
    if expected == current_page():
        _say(f"[docgen] {CONFIG_PAGE.relative_to(ROOT)} 已是最新。")
        return 0
    CONFIG_PAGE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PAGE.write_text(expected, encoding="utf-8", newline="\n")
    _say(f"[docgen] 已生成 {CONFIG_PAGE.relative_to(ROOT)}")
    return 0


def main(argv: list[str]) -> int:
    """`--write` 生成 / `--check` 防漂移 / `--coverage` 报告（`--gate` 时按阈值判退出码）。

    未知参数一律报错退出（与 `tools/gen_conf.py` 同口径）：拼错成 `--chek` 之类的写法
    若静默落进默认的防漂移门禁，本意写盘的人只会看到"检查通过"，意图与行为对不上。
    """
    unknown = [arg for arg in argv if arg not in {"--write", "--check", "--coverage", "--gate"}]
    if unknown:
        _say(f"未知参数 {unknown}：用法 `docgen.py [--write|--check|--coverage [--gate]]`")
        return 1
    if "--write" in argv:
        return _write()
    if "--coverage" in argv:
        _say(coverage_report())
        if "--gate" in argv and coverage_ratio() < DOCSTRING_MIN:
            _say(f"[docgen] docstring 覆盖率低于阈值 {DOCSTRING_MIN:.0%}：门禁模式下失败。")
            return 1
        return 0
    return _gate()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""文档生成器：把**机器已有的单一事实源**投影成文档（开发工具，不参与产品）。

分工原则（见 `rules/references/docs.md`）：

- **能算的就不写**：配置参考页从**声明现算**（`core/conf` 的词表投影），不读入库的那份副本；
- **能查的就不写**：docstring 覆盖率从 AST 直接量，进 CI 当门禁，防止以后悄悄烂掉。

用法：

    uv run python scripts/docgen.py --write      # 重新生成 docs/reference/config.md
    uv run python scripts/docgen.py --check      # 防漂移门禁（页面与声明不一致即失败）
    uv run python scripts/docgen.py --coverage   # 只打印 docstring 覆盖率报告（报告模式）
    uv run python scripts/docgen.py --coverage --gate   # 同上，并低于阈值即非零退出（门禁模式）

生成的文件自己带 SPDX 头与"勿手改"声明；正文**没有一句是手写的**——表来自声明，
说明文字来自本文件的模板常量（改口径改这里，不改正生成物）。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # 直接跑脚本时，`tools` 未必在导入路径上
    sys.path.insert(0, str(ROOT))

#: Python 源码根：一个地方写死，免得各处散着 `ROOT / "…"`（改名时漏一处就静默跑偏）。
PY_ROOT = ROOT / "py_src"
if str(PY_ROOT) not in sys.path:
    sys.path.insert(0, str(PY_ROOT))

# 导入即登记：**每加一个带配置的模块，在这里补一行**——参考页的取材就是这些声明现算出来的。
import core.conf.params  # noqa: E402
import core.storage.conf  # noqa: E402,F401
from core.conf import conf  # noqa: E402
from tools._iosafe import _say  # noqa: E402 — 见上：先补路径再导入

#: 生成出来的参考页
CONFIG_PAGE = ROOT / "docs" / "reference" / "config.md"

#: 公共 API 的 docstring 覆盖阈值（`--coverage` 用它给出达标 / 未达标判定；达标后接 CI）
DOCSTRING_MIN = 0.95

#: 覆盖率统计只列**当前真实存在的层**（`feature` / `ui_tools` / `app` 在 2026-09-29 的重建里
#: 已删除；把它们留在名单里会让覆盖率数字量的是"以为存在的那套"，判据因此失效）。
DOCSTRING_ROOTS = ("core",)

#: 不参与统计的模块（占位包 / 生成物）；当前没有，占位留空。
_SKIPPED: tuple[str, ...] = ()

_PAGE_HEAD = """\
<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 配置项参考

!!! danger "本页由工具生成，请勿手改"

    由 `uv run python scripts/docgen.py --write` 生成，表来自 **配置声明现算**（`core/conf` 的
    词表投影，副本落在 `config/schema/settings.json`）。改口径请改生成器，改配置请改声明的
    那个 `conf(...)` 调用点；`--check` 已进 CI，漂移即失败。**手改这一页会在下一次生成时被抹掉。**

## 怎么读这张表

- **键** = 点分路径，也是 `config/settings.json` 里的属性名（不展开成嵌套对象）。
- **默认值** = 声明里给的默认；`—` 表示没有默认值（那种键的值必须由文件给，丢了即报错）。
- **取值** = `conf("键")`；**声明** = `conf("键", 默认值, type=…, doc=…)`——同一个调用形，
  差别只在给不给参数。写入方向是单向的：改值改 `config/settings.json`，除非显式 `force=True`。

## 全部配置项（{count} 条）

"""

_PAGE_TAIL = """
## 另见

- 用法契约与形状由来：[配置引擎](../architecture/config.md)
- 值文件 `config/settings.json`、词表 `config/schema/settings.json`——**跑一遍程序就生成**
  （引擎退出时落盘，不需要专门的生成脚本）。
- 格式常量（载体魔数、文件头长度、记录头布局这类改了会坏库的）**故意不进配置**，留在实现处。
- 想加一条配置：在**用到它的那个包**里声明（例：`py_src/core/storage/conf.py`），
  再跑一次 `uv run python scripts/docgen.py --write` 把这一页更新。
"""

Residue = tuple[str, int, int]


def read_settings() -> dict[str, Any]:
    """词表（**声明现算**，不读入库副本）：声明一份都不在就直接失败，不静默出空表。"""
    document = conf.schema_document()
    if not document.get("properties"):
        raise RuntimeError("没有算到任何配置声明：检查上方 import 清单是否漏了声明模块")
    return document


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
    """由词表渲染配置表（键 / 类型 / 默认值 / 说明 / 出处）。"""
    data = settings if settings is not None else read_settings()
    properties: dict[str, Any] = data.get("properties", {})
    lines = ["| 键 | 类型 | 默认值 | 说明 | 声明处 |", "|---|---|---|---|---|"]
    for key in sorted(properties):
        spec: dict[str, Any] = properties[key] or {}
        lines.append(
            f"| `{key}` | `{spec.get('type', '—')}` | {_cell(spec.get('default'))} "
            f"| {_text(spec.get('description', '—'))} | `{_text(spec.get('x-cairn-site', '—'))}` |"
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
        for source in sorted((PY_ROOT / root).rglob("*.py")):
            rel = source.relative_to(PY_ROOT).as_posix()
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
    """防漂移门禁：生成物与声明现算的结果不一致即失败。"""
    expected = render_page()
    actual = current_page()
    if expected == actual:
        _say(f"[docgen] {CONFIG_PAGE.relative_to(ROOT)} 与声明一致。")
        return 0
    _say(f"[docgen] {CONFIG_PAGE.relative_to(ROOT)} 已漂移（与声明现算的结果不一致）。")
    _say("         跑 `uv run python scripts/docgen.py --write` 重新生成。")
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

    未知参数一律报错退出（与其余工程工具同口径）：拼错成 `--chek` 之类的写法
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

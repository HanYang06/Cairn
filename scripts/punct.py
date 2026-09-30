# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""标点门禁：把源码**注释与 docstring**里的中文标点换成半角 ASCII（开发工具，不参与产品）。

口径（作者 2026-09-30 定）：中英混排时用半角标点——全角标点是等宽字，与代码、标识符
混在一行里既不对齐也难读；纯中文的正文（`docs/` 的散文）不受此限。

三条边界：

- **只碰注释与 docstring**：字符串字面量里的标点属于**行为**（错误消息、日志文案、用户可见文本），
  换掉等于改了输出，不属于排版；
- **只收一对一映射**：`，` → `,` 之类。`——` 破折号与 `……` 省略号是排版符号，且长度不是一对一，
  一律不动；
- **第三方技能目录不扫**：`.agents/skills/git-commit/` 与 `skill-creator/` 保持上游原样；
- **行内豁免**：说明映射表本身的那几行以 `punct-ignore` 结尾。 <!-- 该标记只在同一行生效 -->

用法：

    uv run python scripts/punct.py            # 全仓检查（退出码 1 = 有命中）
    uv run python scripts/punct.py py_src     # 只查指定目录 / 文件
    uv run python scripts/punct.py --report   # 报告模式：有命中也不阻断（门禁接线初期用）
    uv run python scripts/punct.py --fix      # 就地替换（一对一映射，位置安全）
    uv run python scripts/punct.py --list     # 打印映射表
"""

from __future__ import annotations

import ast
import io
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]

#: 行内豁免标记：该行用于**说明映射表本身**时使用（只在同一行生效，不提供文件级豁免）。
IGNORE = "punct-ignore"

#: 映射表：中文标点 → 半角 ASCII。**只收一对一映射**，见模块 docstring 的口径。
_MAP: dict[str, str] = {
    "，": ",",
    "。": ".",
    "、": ",",
    "；": ";",
    "：": ":",
    "？": "?",
    "！": "!",
    "（": "(",
    "）": ")",
    "【": "[",
    "】": "]",
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "％": "%",
    "＋": "+",
    "＝": "=",
    "／": "/",
    "＿": "_",
}

#: 扫描范围：入库的手写源码。
_SUFFIXES = frozenset({".py"})

#: 不扫的路径前缀（第三方技能保持上游原样）。
_SKIP_PREFIXES = (
    ".agents/skills/git-commit/",
    ".agents/skills/skill-creator/",
)

_SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "node_modules",
        "target",
        "site",
        "build",
        "dist",
        ".mypy_cache",
        ".ruff_cache",
    }
)


@dataclass(frozen=True)
class Hit:
    """一处命中：位置、字符与它该换成的 ASCII。

    Attributes:
        path: 仓库相对路径。
        line: 行号（1 起）。
        column: 列号（1 起）。
        char: 命中的中文标点。
        replacement: 应换成的半角字符。
    """

    path: str
    line: int
    column: int
    char: str
    replacement: str


def _say(message: str) -> None:
    """打印一行：一律按 UTF-8 写，避免 CI 的 Windows 控制台按活动代码页编码而抛错。"""
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        print(message)
        return
    stream.write((message + "\n").encode("utf-8"))
    stream.flush()


def _docstring_spans(tree: ast.AST) -> list[tuple[int, int, int, int]]:
    """取出全部 docstring 的**位置范围**（头行、头列、末行、末列，行 1 起、列 0 起）。

    只认真正的文档字符串：模块、类、函数体里的第一条表达式语句且为字符串常量。
    普通字符串（错误消息、日志文案）不在此列——它们属于行为，不归排版管。
    """
    spans: list[tuple[int, int, int, int]] = []
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, holders):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if not isinstance(first, ast.Expr):
            continue
        value = first.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        spans.append(
            (value.lineno, value.col_offset, value.end_lineno or 0, value.end_col_offset or 0)
        )
    return spans


def _inside(span: tuple[int, int, int, int], line: int, column: int) -> bool:
    """点 `(line, column)` 是否落在 docstring 范围里（列号按 tokenize 的 0 起口径）。"""
    start_line, start_col, end_line, end_col = span
    if line < start_line or line > end_line:
        return False
    if line == start_line and column < start_col:
        return False
    return not (line == end_line and column >= end_col)


def _scan(path: Path) -> list[Hit]:
    """扫一个 `.py` 文件：只报注释与 docstring 里的中文标点。"""
    text = path.read_text(encoding="utf-8")
    relative = path.relative_to(ROOT).as_posix()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    spans = _docstring_spans(tree)
    lines = text.splitlines()
    hits: list[Hit] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except tokenize.TokenError:
        return []
    for token in tokens:
        in_comment = token.type == tokenize.COMMENT
        in_docstring = token.type == tokenize.STRING and any(
            _inside(span, token.start[0], token.start[1]) for span in spans
        )
        if not (in_comment or in_docstring):
            continue
        body = token.string
        start_line, start_col = token.start
        for offset, char in enumerate(body):
            replacement = _MAP.get(char)
            if replacement is None:
                continue
            line = start_line + body[:offset].count("\n")
            if line == start_line:
                column = start_col + offset
            else:
                column = offset - body[:offset].rfind("\n") - 1
            if IGNORE in (lines[line - 1] if line <= len(lines) else ""):
                continue
            hits.append(Hit(relative, line, column + 1, char, replacement))
    return hits


def _skip_relative(relative: str) -> bool:
    """按仓库相对路径判断是否排除。"""
    if any(part in _SKIP_DIRS for part in PurePosixPath(relative).parts):
        return True
    return any(relative.startswith(prefix) for prefix in _SKIP_PREFIXES)


def _absolute(item: str) -> Path:
    """把命令行条目折成绝对路径。"""
    candidate = Path(item)
    return candidate.resolve() if candidate.is_absolute() else (Path.cwd() / candidate).resolve()


def _targets(argv: list[str]) -> tuple[list[Path], list[str]]:
    """展开待检文件；仓库外的路径跳过并显式列出。"""
    given = [arg for arg in argv if not arg.startswith("--")]
    roots = [_absolute(item) for item in given] if given else [ROOT]
    found: list[Path] = []
    skipped: list[str] = []
    for root in roots:
        if not root.is_relative_to(ROOT):
            skipped.append(root.as_posix())
            continue
        if root.is_file():
            if root.suffix in _SUFFIXES and not _skip_relative(root.relative_to(ROOT).as_posix()):
                found.append(root)
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in _SUFFIXES:
                continue
            if _skip_relative(path.relative_to(ROOT).as_posix()):
                continue
            found.append(path)
    return found, skipped


def _fix(path: Path, hits: list[Hit]) -> int:
    """就地替换一个文件里的命中；返回替换处数。

    只做一对一映射，故按位置替换即可，不触碰行长度以外的任何东西。
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    by_line: dict[int, list[Hit]] = {}
    for hit in hits:
        by_line.setdefault(hit.line, []).append(hit)
    for line_number, line_hits in by_line.items():
        line = lines[line_number - 1]
        chars = list(line)
        for hit in sorted(line_hits, key=lambda item: item.column, reverse=True):
            index = hit.column - 1
            if chars[index] == hit.char:
                chars[index] = hit.replacement
        lines[line_number - 1] = "".join(chars)
    path.write_text("".join(lines), encoding="utf-8")
    return sum(len(items) for items in by_line.values())


def _print_map() -> None:
    """打印映射表（`--list`）。"""
    for char, replacement in _MAP.items():
        _say(f"{char}\t{replacement}")


def _apply(hits: list[Hit]) -> None:
    """按文件分组就地替换（`--fix`）。"""
    by_path: dict[str, list[Hit]] = {}
    for hit in hits:
        by_path.setdefault(hit.path, []).append(hit)
    for relative, items in by_path.items():
        changed = _fix(ROOT / relative, items)
        _say(f"[punct] 已换 {changed} 处：{relative}")


def _report(files: list[Path], hits: list[Hit], skipped: list[str]) -> None:
    """打印跳过项、按文件计数与命中明细。"""
    for item in skipped:
        _say(f"[punct] 跳过（不在本仓库内）：{item}")
    by_file: dict[str, int] = {}
    for hit in hits:
        by_file[hit.path] = by_file.get(hit.path, 0) + 1
    for shown, count in sorted(by_file.items(), key=lambda item: (-item[1], item[0])):
        _say(f"{count:>4}  {shown}")
    _say(f"\n[punct] 扫描 {len(files)} 个文件，命中 {len(hits)} 处。")
    if not hits:
        return
    _say("明细（最多 40 条）：")
    for hit in hits[:40]:
        _say(f"  {hit.path}:{hit.line}:{hit.column}  「{hit.char}」→「{hit.replacement}」")
    if len(hits) > 40:
        _say(f"  …… 其余 {len(hits) - 40} 处")


def main(argv: list[str]) -> int:
    """检查、报告或替换；返回退出码。

    默认有命中即返回 1；`--report` 为报告模式，有命中仍返回 0。
    """
    if "--list" in argv:
        _print_map()
        return 0

    fix = "--fix" in argv
    report_only = "--report" in argv
    files, skipped = _targets(argv)
    hits: list[Hit] = []
    for path in files:
        hits.extend(_scan(path))
    _report(files, hits, skipped)

    if fix:
        _apply(hits)
        return 0
    if report_only:
        return 0
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

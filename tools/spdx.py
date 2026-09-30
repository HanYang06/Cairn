# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""SPDX 头：检查 / 补插（开发工具，不参与产品）。

规则见 `.agents/skills/rules/references/spdx.md`。入库文件分三类：

1. **能内联头**（`_COMMENT_STYLES` 认得的扩展名）→ 顶部必须有那两行，缺了 `--fix` 补上；
2. **`SKILL.md`** → YAML frontmatter 必须占最顶，故 SPDX 头紧随其后，且 frontmatter 要写
   `license: Apache-2.0`；
3. **装不下头的**（图片 / JSON / 锁文件 / 生成物 / 法律文书 / 第三方 vendored）→ 由仓库根的
   `REUSE.toml` 集中声明。`--check` 顺带保证**没有文件是无主的**。

用法：

    uv run python tools/spdx.py --check                     # 门禁（默认行为）
    uv run python tools/spdx.py --fix                       # 补插；改动了就非零退出
    uv run python tools/spdx.py --check README.md README2.md  # 只看指定文件
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # 直接跑脚本时，`tools` 未必在导入路径上
    sys.path.insert(0, str(ROOT))

from tools._iosafe import _say  # noqa: E402 — 见上：先补路径再导入

MANIFEST = "REUSE.toml"
COPYRIGHT = "SPDX-FileCopyrightText: 2026 HanYang06"
LICENSE_ID = "SPDX-License-Identifier: Apache-2.0"
SKILL_LICENSE = "license: Apache-2.0"
SKILL_NAME = "SKILL.md"


_HASH = "hash"
_BLOCK = "block"
_SEMI = "semi"
_SLASH = "slash"
_CSTYLE = "cstyle"

# 扩展名（小写含点）→ 注释风格。装不下注释的格式（.json / 图片 / 锁文件）**故意不收**，
# 它们必须去 REUSE.toml 报到。
_COMMENT_STYLES: dict[str, str] = {
    ".py": _HASH,
    ".pyi": _HASH,
    ".spec": _HASH,  # PyInstaller 的 spec 就是 Python 脚本
    ".toml": _HASH,
    ".yaml": _HASH,
    ".yml": _HASH,
    ".sh": _HASH,
    ".ps1": _HASH,
    ".js": _HASH,
    ".mjs": _HASH,
    ".cjs": _HASH,
    ".ts": _HASH,
    ".sql": _HASH,
    ".cfg": _HASH,
    ".ini": _HASH,
    ".md": _BLOCK,
    ".html": _BLOCK,
    ".svg": _BLOCK,
    ".iss": _SEMI,  # Inno Setup 的注释是分号
    ".rs": _SLASH,
    ".tsx": _SLASH,  # 前端 TSX；`.ts` 已在上面
    ".jsx": _SLASH,
    ".css": _CSTYLE,
}

_FENCE = "---"
_HEAD_WINDOW = 8  # 头允许落在顶部这几行内（SKILL.md 要越过 frontmatter）

# 没有扩展名、但能写 `#` 注释的文件：按文件名认领
_NAMED_STYLES: dict[str, str] = {
    ".editorconfig": _HASH,
    ".gitignore": _HASH,
    ".gitattributes": _HASH,
    "Makefile": _HASH,
    "Dockerfile": _HASH,
    # 停用态的 workflow（靠非 `.yml` 后缀让 GitHub 不自动跑），内容仍是 yml
    "ocr-review.yml.on-run": _HASH,
}


# ---- 头的形状 ----
def _comment(style: str, text: str) -> str:
    """按注释风格包一行。"""
    if style == _BLOCK:
        return f"<!-- {text} -->"
    if style == _SEMI:
        return f"; {text}"
    if style == _SLASH:
        return f"// {text}"
    if style == _CSTYLE:
        return f"/* {text} */"
    return f"# {text}"


def _header_lines(style: str) -> list[str]:
    """该风格下的 SPDX 头两行。"""
    return [_comment(style, line) for line in (COPYRIGHT, LICENSE_ID)]


def _style_of(path: str) -> str | None:
    """取注释风格：先按文件名认领（`.gitignore` 这类），再按扩展名；装不下头的返回 None。"""
    ref = PurePosixPath(path)
    if ref.name in _NAMED_STYLES:
        return _NAMED_STYLES[ref.name]
    return _COMMENT_STYLES.get(ref.suffix.lower())


def _relative(path: str) -> str | None:
    """把命令行给的路径折成仓库相对路径；不在仓库内返回 None。

    绝对路径直接用；相对路径按当前工作目录解析。`../` 这类可以越过仓库根的
    相对路径同样过 `relative_to` 校验，越界返回 None，不留读写通路。
    """
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    try:
        return candidate.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return None


# ---- 文件清单与集中清单 ----
def _tracked() -> list[str]:
    """`git ls-files`：只认入库文件（自动躲开 vault/、.venv/、构建产物）。"""
    git = shutil.which("git")
    if git is None:
        raise SystemExit("找不到 git：本工具用 `git ls-files` 取文件清单")
    done = subprocess.run(
        # core.quotepath=false：否则中文路径会被转义成 `"\345..."` 带引号，
        # 下游按扩展名认注释风格时会认不出 `.md`
        [git, "-c", "core.quotepath=false", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="surrogateescape",
        check=True,
    )
    return [line for line in done.stdout.splitlines() if line]


def _manifest_patterns(text: str) -> list[str]:
    """读 REUSE.toml 里所有 annotations.path。"""
    data = tomllib.loads(text)
    patterns: list[str] = []
    for block in data.get("annotations", []):
        declared = block.get("path")
        if isinstance(declared, str):
            patterns.append(declared)
        elif isinstance(declared, list):
            patterns.extend(str(item) for item in declared)
    return patterns


def _matches(path: str, pattern: str) -> bool:
    """路径是否命中声明；`dir/**` 按目录前缀理解，其余交给 PurePosixPath。"""
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return path == prefix or path.startswith(f"{prefix}/")
    return PurePosixPath(path).match(pattern)


def _covered(path: str, patterns: list[str]) -> bool:
    """该文件是否已由 REUSE.toml 集中声明。"""
    return any(_matches(path, pattern) for pattern in patterns)


# ---- frontmatter ----
def _frontmatter_end(lines: list[str]) -> int | None:
    """frontmatter 闭合行的下标（0 起）；没有 frontmatter 返回 None。"""
    if not lines or lines[0].strip() != _FENCE:
        return None
    for index in range(1, len(lines)):
        if lines[index].strip() == _FENCE:
            return index
    return None


def _header_region(path: str, lines: list[str]) -> tuple[int, int]:
    """期望 SPDX 头出现的行区间 `[start, stop)`。"""
    if PurePosixPath(path).name != SKILL_NAME:
        return 0, _HEAD_WINDOW
    end = _frontmatter_end(lines)
    if end is None:
        return 0, 0
    return end + 1, end + 1 + _HEAD_WINDOW


# ---- 检查 ----
def _violations(path: str, text: str) -> list[str]:
    """这个文件的 SPDX 问题清单（空 = 合规）。"""
    lines = text.splitlines()
    start, stop = _header_region(path, lines)
    region = lines[start:stop]
    problems: list[str] = []
    for marker, label in ((COPYRIGHT, "版权行"), (LICENSE_ID, "许可行")):
        if any(marker in line for line in region):
            continue
        field = marker.split(":")[0]
        if any(field in line for line in region):
            problems.append(f"{label}内容不符（应为 `{marker}`）")
        else:
            problems.append(f"缺{label} `{marker}`")
    if PurePosixPath(path).name == SKILL_NAME:
        end = _frontmatter_end(lines)
        if end is None:
            problems.append("SKILL.md 缺 YAML frontmatter")
        elif not any(SKILL_LICENSE in line for line in lines[1:end]):
            problems.append(f"frontmatter 缺 `{SKILL_LICENSE}`")
    return problems


# ---- 补插 ----
def _eol(raw: list[str]) -> str:
    """文件的行尾风格（CRLF 文件保持原样）。"""
    return "\r\n" if any(line.endswith("\r\n") for line in raw) else "\n"


def _insert_header(path: str, style: str, raw: list[str]) -> list[str]:
    """把 SPDX 头插到正确位置（shebang 之后 / frontmatter 之后）。"""
    insert_at = 1 if raw and raw[0].startswith("#!") else 0
    if PurePosixPath(path).name == SKILL_NAME:
        end = _frontmatter_end(raw)
        if end is not None:
            insert_at = end + 1
    block = [f"{line}{_eol(raw)}" for line in _header_lines(style)]
    rest = raw[insert_at:]
    while rest and rest[0].strip() == "":  # 空行统一由头之后那一个提供
        rest = rest[1:]
    return [*raw[:insert_at], *block, _eol(raw), *rest]


def _insert_skill_license(raw: list[str]) -> list[str]:
    """SKILL.md：frontmatter 里补 `license: Apache-2.0`（已有 license 键则不动）。"""
    plain = [line.rstrip("\r\n") for line in raw]
    end = _frontmatter_end(plain)
    if end is None or any(line.strip().startswith("license:") for line in plain[1:end]):
        return raw
    return [*raw[:end], f"{SKILL_LICENSE}{_eol(raw)}", *raw[end:]]


def _has_spdx_field(region: list[str]) -> bool:
    """区间内是否已出现任一 SPDX 字段名（不要求内容正确）。"""
    fields = {marker.split(":")[0] for marker in (COPYRIGHT, LICENSE_ID)}
    return any(field in line for field in fields for line in region)


def _fix(path: str, style: str, text: str) -> bool:
    """补头（SKILL.md 连带补 frontmatter 的 license 行）；返回是否改动。

    **已存在的头绝不重复插入**——否则每次提交都会叠一层。判定不看内容是否相符，
    只看区间内是否已有 SPDX 字段名：形似而内容不符的头（例如版权年份写错）同样
    算「已存在」，此时不插入、返回 False，由 `_process` 报成 problem 交人工处理。
    缺 frontmatter 的 SKILL.md 属结构问题，同样不猜。
    """
    raw = text.splitlines(keepends=True)
    is_skill = PurePosixPath(path).name == SKILL_NAME
    if is_skill and _frontmatter_end(raw) is None:
        return False
    region = [line.rstrip("\r\n") for line in raw[slice(*_header_region(path, raw))]]
    if not _has_spdx_field(region):
        raw = _insert_header(path, style, raw)
    if is_skill:
        raw = _insert_skill_license(raw)
    updated = "".join(raw)
    if updated == text:
        return False
    with (ROOT / path).open("w", encoding="utf-8", newline="") as handle:
        handle.write(updated)
    return True


# ---- 入口 ----
_OK = "ok"
_FIXED = "fixed"
_PROBLEM = "problem"


def _patterns() -> list[str]:
    """读集中清单里的路径声明；没有清单就当空。"""
    manifest = ROOT / MANIFEST
    if not manifest.is_file():
        return []
    return _manifest_patterns(manifest.read_text(encoding="utf-8"))


def _resolve_targets(targets: list[str]) -> list[str]:
    """把命令行给的目标折成仓库相对路径；没给目标就扫全部入库文件。"""
    if not targets:
        return _tracked()
    paths: list[str] = []
    for target in targets:
        rel = _relative(target)
        if rel is None:
            _say(f"[SPDX] 跳过（不在本仓库内）：{target}")
        else:
            paths.append(rel)
    return paths


def _process(path: str, patterns: list[str], *, fix: bool) -> tuple[str, str]:
    """处理一个文件 → `(状态, 说明)`；状态取 `ok` / `fixed` / `problem`。"""
    if _covered(path, patterns):
        return _OK, ""
    style = _style_of(path)
    if style is None:
        return _PROBLEM, f"{path}: 装不下内联头，且未在 {MANIFEST} 声明"
    file = ROOT / path
    if not file.is_file():  # 已删除但仍在清单里
        return _OK, ""
    with file.open(encoding="utf-8", newline="") as handle:  # newline="" 保留原行尾
        text = handle.read()
    issues = _violations(path, text)
    if not issues:
        return _OK, ""
    if fix and _fix(path, style, text):
        return _FIXED, path
    return _PROBLEM, f"{path}: {'；'.join(issues)}"


def _report(changed: list[str], problems: list[str], total: int) -> int:
    """打印结论并给出退出码：有改动或有真问题都算失败。"""
    for path in changed:
        _say(f"已补 SPDX 头：{path}")
    if changed:
        _say(f"\n共补 {len(changed)} 个文件，请重新 `git add` 后再提交。")
    for problem in problems:
        _say(f"[SPDX] {problem}")
    if not changed and not problems:
        _say(f"[SPDX] {total} 个文件全部合规。")
    return 1 if changed or problems else 0


def main(argv: list[str]) -> int:
    """检查或补插；返回进程退出码。"""
    fix = "--fix" in argv
    targets = [arg for arg in argv if not arg.startswith("--")]
    patterns = _patterns()
    paths = _resolve_targets(targets)

    changed: list[str] = []
    problems: list[str] = []
    for path in paths:
        status, note = _process(path, patterns, fix=fix)
        if status == _FIXED:
            changed.append(note)
        elif status == _PROBLEM:
            problems.append(note)
    return _report(changed, problems, len(paths))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

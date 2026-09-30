# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""提交信息门禁：校验 Conventional Commits（开发工具，不参与产品）。

规矩来源：`AGENTS.md` 的硬性约定与 `.agents/skills/rules/references/commit.md`——
提交信息用中文写、格式取 Conventional Commits。

校验的是**首行**（`type(scope): 描述`）：

- `type` 取约定集合；`scope` 可省；`!` 表示破坏性变更；
- 描述必须非空，首行长度不超过 `_MAX_HEADER`；
- 合并提交（`Merge …`）与回退提交（`Revert …`）由 git 生成，予以放行；
- 正文（首行之后）不校验：那里是给人读的说明。

用法（git 的 `commit-msg` 钩子把消息文件路径作为第一个参数传入）：

    uv run python scripts/commitmsg.py .git/COMMIT_EDITMSG
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

#: 允许的类型：Conventional Commits 的约定集合。
_TYPES = (
    "feat",
    "fix",
    "docs",
    "style",
    "refactor",
    "perf",
    "test",
    "build",
    "ci",
    "chore",
    "revert",
)

#: 首行形状：`type(scope)!: 描述`。scope 用半角标识符，描述必填。
_PATTERN = re.compile(
    r"^(?P<type>" + "|".join(_TYPES) + r")(?:\((?P<scope>[a-z0-9._/-]+)\))?!?: (?P<subject>.+)$"
)

#: 首行长度上限（字符数）。中文一字按一字符计，故留出比 72 更宽的余量。
_MAX_HEADER = 100

#: 由 git 自己生成的提交：格式不归本工具管。
_GENERATED = ("Merge ", "Revert ", "fixup! ", "squash! ")


def _say(message: str) -> None:
    """打印一行：一律按 UTF-8 写，避免 CI 的 Windows 控制台按活动代码页编码而抛错。"""
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        print(message)
        return
    stream.write((message + "\n").encode("utf-8"))
    stream.flush()


def first_line(text: str) -> str:
    """取提交信息的第一行有效内容：跳过空行与 `#` 注释行。"""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        return line
    return ""


def check(header: str) -> str | None:
    """校验首行；通过返回 ``None``，否则返回一句人话说明为什么不通过。"""
    if not header:
        return "提交信息是空的：首行要写成 `type(scope): 描述`。"
    if header.startswith(_GENERATED):
        return None
    if len(header) > _MAX_HEADER:
        return f"首行 {len(header)} 字符，超过上限 {_MAX_HEADER}：请把细节移到正文。"
    matched = _PATTERN.match(header)
    if matched is None:
        allowed = " / ".join(_TYPES)
        return (
            f"首行不符合 Conventional Commits：`{header}`\n"
            f"        允许的类型：{allowed}\n"
            f"        形状：`type(scope): 描述`，例如 `feat(note): 笔记的落盘形状`"
        )
    return None


def main(argv: list[str]) -> int:
    """校验消息文件或直接给出的首行；返回退出码。"""
    if not argv:
        _say("[commitmsg] 缺少参数：需要一个提交信息文件路径。")
        return 1
    target = Path(argv[0])
    text = target.read_text(encoding="utf-8") if target.is_file() else argv[0]
    header = first_line(text) if "\n" in text else text.strip()
    problem = check(header)
    if problem is not None:
        _say(f"[commitmsg] {problem}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

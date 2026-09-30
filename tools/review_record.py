# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""评审记录生成器：按 PR 组织，一个 PR 一个文件，所有问题列在一起。

用法（参数按需续行）：

    # 添加问题
    uv run python tools/review_record.py --pr 25 --add --file <路径> --line <行号> \
        --severity <critical|high|medium|low> --desc "<问题描述>"

    # 标记问题为已修复
    uv run python tools/review_record.py --pr 25 --fix --file <路径> --line <行号>

    # 标记问题为假问题
    uv run python tools/review_record.py --pr 25 --reject --file <路径> --line <行号>

    # 生成修复记录
    uv run python tools/review_record.py --pr 25 --fix-record --file <路径> --line <行号> \
        --before "<修复前代码>" --after "<修复后代码>" --reason "<修复理由>"
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTE_DIR = ROOT / ".agents" / "skills" / "memory" / "note"
FIX_DIR = ROOT / ".agents" / "skills" / "memory" / "fix"


def _note_path(pr: str) -> Path:
    return NOTE_DIR / f"{pr}.md"


def _fix_path(pr: str) -> Path:
    return FIX_DIR / f"{pr}.md"


def add_issue(pr: str, file: str, line: int, severity: str, description: str) -> Path:
    """向 PR 记录中添加问题。"""
    NOTE_DIR.mkdir(parents=True, exist_ok=True)
    path = _note_path(pr)

    existing = ""
    if path.is_file():
        existing = path.read_text(encoding="utf-8")

    # 生成新问题条目
    entry = f"""### {file}:{line}

- **严重性**: {severity}
- **状态**: 待修复
- **描述**: {description}

"""

    if not existing:
        header = f"""<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 问题记录：PR #{pr}

- **PR**: #{pr}
- **日期**: {datetime.now(UTC).strftime("%Y-%m-%d")}
- **问题数**: 1

---

"""
        existing = header
    else:
        # 更新问题数
        lines = existing.split("\n")
        for i, line_text in enumerate(lines):
            if line_text.startswith("- **问题数**:"):
                count = int(line_text.split(":")[1].strip())
                lines[i] = f"- **问题数**: {count + 1}"
                break
        existing = "\n".join(lines)

    content = existing.rstrip() + "\n\n" + entry
    path.write_text(content, encoding="utf-8")
    return path


def mark_fixed(pr: str, file: str, line: int) -> Path:
    """标记问题为已修复。"""
    path = _note_path(pr)
    if not path.is_file():
        print(f"错误：文件不存在 {path}", file=sys.stderr)
        return path

    content = path.read_text(encoding="utf-8")
    lines = content.split("\n")
    for i, line_text in enumerate(lines):
        if f"### {file}:{line}" in line_text:
            for j in range(i, min(i + 5, len(lines))):
                if "**状态**: 待修复" in lines[j]:
                    lines[j] = lines[j].replace("**状态**: 待修复", "**状态**: 已修复")
                    break
            break

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def mark_rejected(pr: str, file: str, line: int) -> Path:
    """标记问题为假问题。"""
    path = _note_path(pr)
    if not path.is_file():
        print(f"错误：文件不存在 {path}", file=sys.stderr)
        return path

    content = path.read_text(encoding="utf-8")
    lines = content.split("\n")
    for i, line_text in enumerate(lines):
        if f"### {file}:{line}" in line_text:
            for j in range(i, min(i + 5, len(lines))):
                if "**状态**: 待修复" in lines[j]:
                    lines[j] = lines[j].replace("**状态**: 待修复", "**状态**: 已确认（假问题）")
                    break
            break

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def add_fix_record(  # noqa: PLR0913 — 修复前 / 修复后 / 理由分三段传入
    pr: str, file: str, line: int, *, before: str, after: str, reason: str
) -> Path:
    """添加修复记录。"""
    FIX_DIR.mkdir(parents=True, exist_ok=True)
    path = _fix_path(pr)

    existing = ""
    if path.is_file():
        existing = path.read_text(encoding="utf-8")

    entry = f"""### 修复 {file}:{line}

#### 修复前

```python
{before}
```

#### 修复后

```python
{after}
```

#### 修复理由

{reason}

#### 验证

- [ ] 测试通过
- [ ] 门禁通过

---

"""

    if not existing:
        header = f"""<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 修复记录：PR #{pr}

- **PR**: #{pr}
- **日期**: {datetime.now(UTC).strftime("%Y-%m-%d")}

---

"""
        existing = header

    content = existing.rstrip() + "\n\n" + entry
    path.write_text(content, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="评审记录生成器（按 PR 组织）")
    parser.add_argument("--pr", required=True, help="PR 编号")
    parser.add_argument("--add", action="store_true", help="添加问题")
    parser.add_argument("--file", help="问题文件路径")
    parser.add_argument("--line", type=int, help="问题行号")
    parser.add_argument("--severity", help="严重性（critical/high/medium/low）")
    parser.add_argument("--desc", help="问题描述")
    parser.add_argument("--fix", action="store_true", help="标记问题为已修复")
    parser.add_argument("--reject", action="store_true", help="标记问题为假问题")
    parser.add_argument("--fix-record", action="store_true", help="添加修复记录")
    parser.add_argument("--before", help="修复前代码")
    parser.add_argument("--after", help="修复后代码")
    parser.add_argument("--reason", help="修复理由")

    args = parser.parse_args()

    if args.add:
        if not all([args.file, args.line, args.severity, args.desc]):
            print("错误：添加问题需要 --file、--line、--severity、--desc", file=sys.stderr)
            return 1
        path = add_issue(args.pr, args.file, args.line, args.severity, args.desc)
        print(f"已添加问题：{path.relative_to(ROOT)}")

    elif args.fix:
        if not all([args.file, args.line]):
            print("错误：标记修复需要 --file、--line", file=sys.stderr)
            return 1
        path = mark_fixed(args.pr, args.file, args.line)
        print(f"已标记修复：{path.relative_to(ROOT)}")

    elif args.reject:
        if not all([args.file, args.line]):
            print("错误：标记假问题需要 --file、--line", file=sys.stderr)
            return 1
        path = mark_rejected(args.pr, args.file, args.line)
        print(f"已标记假问题：{path.relative_to(ROOT)}")

    elif args.fix_record:
        if not all([args.file, args.line, args.before, args.after, args.reason]):
            print("错误：修复记录需要 --file、--line、--before、--after、--reason", file=sys.stderr)
            return 1
        path = add_fix_record(
            args.pr,
            args.file,
            args.line,
            before=args.before,
            after=args.after,
            reason=args.reason,
        )
        print(f"已添加修复记录：{path.relative_to(ROOT)}")

    else:
        print("错误：请指定操作（--add / --fix / --reject / --fix-record）", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

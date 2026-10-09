# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""量尺:数出"将来真要送进翻译 API 的字符量".

这不是门禁,是**预算工具**——翻译服务按字符计费,故先得知道要送多少字符.
口径必须与将来 `translate.py` 的送译范围一致,否则算出来的钱是假的:

1. **逐行跳过**:围栏代码块(``` / ~~~)整块,缩进四格的代码块;
2. **行内剔除**:行内代码 `` `…` ``,HTML 注释,Markdown 链接的 URL 部分,
   裸 URL,图片语法,ATX 标题的 `#`,表格分隔行,frontmatter;
3. **只数正文**:剩下的整行算作送译内容(含它自己的标点与空格——API 就是按这个计费).

用法:

    uv run python scripts/translate_chars.py            # 逐页 + 合计
    uv run python scripts/translate_chars.py --csv      # 便于贴进表格
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

#: 围栏代码块的起始标记(``` 或 ~~~,允许带语言名与缩进)
_FENCE = re.compile(r"^\s*(?:```|~~~)")
#: 行内代码
_INLINE_CODE = re.compile(r"`[^`]*`")
#: HTML 注释(含 SPDX 头).用 `[\s\S]` 而不是 `.`:后者默认不吃换行,
#: 跨行注释会只匹配掉第一行,剩下的正文被当成要送译的内容(CodeQL `py/bad-tag-filter`
#: 命中的正是这个形状,按其建议改成"任意字符含换行").
_HTML_COMMENT = re.compile(r"<!--[\s\S]*?-->")
#: Markdown 链接与图片的 URL 部分:保留链接文字,去掉 `(…)`
_LINK_URL = re.compile(r"\]\([^)]*\)")
#: 裸 URL
_BARE_URL = re.compile(r"<?https?://\S+>?")
#: 表格分隔行(|---|---|)
_TABLE_RULE = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")
#: ATX 标题记号
_HEADING = re.compile(r"^\s*#{1,6}\s+")
#: 列表记号
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
#: 引用记号
_QUOTE = re.compile(r"^\s*>\s?")


@dataclass
class Count:
    """一页的字符账."""

    page: str
    raw: int
    send: int


def _strip_inline(line: str) -> str:
    """剔除行内不该送译的片段,返回剩下的正文."""
    for pattern in (_HTML_COMMENT, _INLINE_CODE, _LINK_URL, _BARE_URL):
        line = pattern.sub("", line)
    return line


def count_page(path: Path) -> Count:
    """数一页:原始字符与预计送译字符."""
    text = path.read_text(encoding="utf-8")
    raw = len(text)
    sending: list[str] = []
    in_fence = False
    for raw_line in text.splitlines():
        if _FENCE.match(raw_line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if raw_line.startswith("    ") and raw_line.strip():  # 缩进代码块
            continue
        if _TABLE_RULE.match(raw_line):
            continue
        line = _strip_inline(raw_line)
        line = _HEADING.sub("", line)
        line = _BULLET.sub("", line)
        line = _QUOTE.sub("", line)
        if line.strip():
            sending.append(line)
    # 每行末尾的换行也算一个字符:送译时行是按段拼的,API 就是这个量.
    return Count(
        page=path.relative_to(ROOT).as_posix(),
        raw=raw,
        send=sum(len(x) for x in sending) + len(sending),
    )


def main(argv: list[str]) -> int:
    """打印逐页与合计字符量."""
    pages = sorted(p for p in DOCS.rglob("*.md") if not p.name.endswith(".en.md"))
    counts = [count_page(p) for p in pages]
    as_csv = "--csv" in argv
    rows = [(c.page, c.raw, c.send) for c in counts]
    if as_csv:
        print("page,raw_chars,send_chars")
        for page, raw, send in rows:
            print(f"{page},{raw},{send}")
    else:
        width = max(len(page) for page, _, _ in rows)
        print(f"{'page'.ljust(width)}  {'raw':>7}  {'send':>7}")
        for page, raw, send in rows:
            print(f"{page.ljust(width)}  {raw:>7}  {send:>7}")
    total_raw = sum(c.raw for c in counts)
    total_send = sum(c.send for c in counts)
    print(f"\npages={len(rows)}  raw={total_raw}  send={total_send}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

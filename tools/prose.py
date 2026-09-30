# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""文档口语门禁：书面语词典 + 检查器（开发工具，不参与产品）。

标准：**所有文档一律非口语化**（`.agents/skills/rules/references/prose.md`）。
适用范围为文档、代码注释、docstring、提交信息；日常讨论不受此限，
但所有进入仓库的文本均须符合技术文档语体。

本工具按 `_LEXICON` 报出**歧义为零**的口语标记及其位置，并给出文件级与仓库级计数。
工具**不重写**文本，替换由作者完成。

用法：

    uv run python tools/prose.py            # 全仓检查（退出码 1 = 有命中）
    uv run python tools/prose.py docs src   # 只查指定目录 / 文件
    uv run python tools/prose.py --report   # 报告模式：有命中也不阻断
    uv run python tools/prose.py --list     # 打印词典
"""

from __future__ import annotations

import ast
import contextlib
import re
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]

#: 行内豁免标记：该行用于**说明禁用形式本身**（规则表、生成器模板）时使用。
#: 仅豁免本行，且必须在同一行出现；不提供文件级豁免，避免整篇逃逸。
IGNORE = "prose-ignore"

#: 扫描范围：入库的手写文本（生成物、第三方、评审记录、博客除外）
_MARKDOWN_SKIP = (
    "docs/review/",
    "docs/blog/",
    ".agents/skills/skill-creator/",
    ".agents/skills/git-commit/",
)


@dataclass(frozen=True)
class Term:
    """一条口语标记：`pattern` 为已编译正则，`why` 说明它为什么不算书面语。

    `not_at_line_start` 为真时，命中若落在行首则不算——用于「重复感叹号」这类
    与 MkDocs admonition 语法（行首三叹号）冲突的规则。
    """

    pattern: re.Pattern[str]
    why: str
    not_at_line_start: bool = False


def _say(message: str) -> None:
    """打印一行：确保 UTF-8 输出。

    CI 的 Windows 控制台默认用活动代码页编码 stdout，中文输出会抛
    `UnicodeEncodeError: charmap` 而失败（本地 UTF-8 终端看不出来）。
    本工具的输出全部为中文，故一律走本助手，不用 `print`。
    """
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        print(message)
        return
    stream.write((message + "\n").encode("utf-8"))
    stream.flush()


def _term(pattern: str, why: str, *, not_at_line_start: bool = False) -> Term:
    """按词典条目建一条（统一大小写不敏感，中文无影响）。"""
    return Term(re.compile(pattern, re.IGNORECASE), why, not_at_line_start)


#: 口语词典。收录原则：仅收**歧义为零**的标记；宁可少收，不可误报。
_LEXICON: tuple[Term, ...] = (
    # —— 第二人称：技术文档用「本仓库 / 作者 / 使用者」，不写第二人称代词——
    _term(r"你", "第二人称，改为「本仓库 / 作者 / 使用者」"),
    _term(r"咱们", "口语第一人称，改为「本仓库 / 我们」"),
    # —— 语气填充词 ——
    _term(r"说白了", "口语填充词，删除"),
    _term(r"其实", "口语填充词，删除或改「事实上」"),
    _term(r"反正", "口语填充词，删除"),
    _term(r"回头(再|补|做)", "口语时间副词，删除"),
    _term(r"顺手", "口语副词，改为「一并」"),
    _term(r"随手", "口语副词，改为「一并」"),
    _term(r"踩坑", "口语，改为「已遇问题 / 注意事项」"),
    _term(r"搞得", "口语，改为「导致 / 使得」"),
    _term(r"搞定", "口语，改为「完成 / 解决」"),
    _term(r"弄(好|完|错)", "口语动词，改为「完成 / 处理」"),
    _term(r"搞(不|清)", "口语动词，改为「无法 / 不明」"),
    _term(r"捋", "口语动词，改为「整理」"),
    _term(r"折腾", "口语，改为「反复调整」"),
    _term(r"啰嗦|罗嗦", "口语，改为「冗长」"),
    _term(r"瞎", "口语，改为「随意 / 无依据」"),
    _term(r"家伙", "口语名词，删除"),
    _term(r"玩意儿", "口语名词，改为「构件 / 组件」"),
    _term(r"哈(?![佛里希])", "语气词，删除"),
    _term(r"呗", "语气词，删除"),
    _term(r"嘛", "语气词，删除"),
    # —— 祈使式劝阻：文档写规则，不写劝说 ——
    _term(r"别手抄", "口语祈使，改为「不得手写」"),
    _term(r"别慌", "口语祈使，改为「不必担心」"),
    _term(r"别(忘|漏|猜|蒙|自造|手抄|据以)", "口语祈使，改为「不得 / 不要」"),
    _term(r"撒谎", "拟人化比喻，改为「与事实不符」"),
    _term(r"硬撑", "口语，删除"),
    _term(r"背锅", "口语比喻，改为「承担」"),
    _term(r"吃掉", "口语比喻，改为「占用 / 消耗」"),
    _term(r"烂掉", "口语比喻，改为「腐化 / 失效」"),
    _term(r"白改", "口语，改为「无谓修改」"),
    _term(r"白搭", "口语，改为「无效」"),
    # —— 网络腔与表情 ——
    _term(r"～", "波浪号，非正式标点"),
    _term(r"[（(](笑|逃|捂脸|摊手)[)）]", "表情文字，删除"),
    # 重复感叹号属非正式标点。行首的三叹号是 MkDocs admonition 语法，必须排除
    # （负向后顾在行首会成立，Python `re` 实测无法用于此判断，故用 `not_at_line_start`）。
    _term(r"[!！][!！]", "重复感叹号，改为单句号", not_at_line_start=True),
    _term(r"233+", "网络用语，删除"),
)

#: 不扫描的目录：按**仓库相对路径**的组成部分判定；构建产物、本地数据、依赖缓存。
#: `node_modules` 与 `target` 是前端 / Rust 的依赖与编译产物——第三方更新日志里
#: 满是词典命中项（提交短哈希会撞进数字类词条），扫它们只会制造噪音。
_SKIP_DIRS = frozenset(
    {".git", ".venv", "build", "dist", "site", "vault", "__pycache__", "node_modules", "target"}
)

#: 可扫描的文本类型
_SUFFIXES = frozenset({".md", ".py"})


@dataclass
class Hit:
    """一处命中：文件、行号、原文片段、命中的词、改写建议。"""

    path: str
    line: int
    text: str
    term: str
    why: str


def _texts(text: str, suffix: str) -> list[tuple[int, str]]:
    """取出待检文本：`.md` 取全文；`.py` 只取 docstring 与注释，不取字符串字面量。

    行号与 `str.splitlines()` 对齐，均为 1 基。
    """
    if suffix == ".md":
        return list(enumerate(text.splitlines(), start=1))
    if suffix != ".py":
        return []
    found: list[tuple[int, str]] = []
    # 语法不完整的文件（更高版本语法 / 写作中途）跳过 docstring，注释仍需检查，
    # 与下方 tokenize 的保护保持对称。
    with contextlib.suppress(SyntaxError):
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            first = node.body[0] if node.body else node
            doc = ast.get_docstring(node, clean=False)
            if not doc:
                continue
            for offset, line in enumerate(doc.splitlines()):
                found.append((first.lineno + offset, line))
    with (
        contextlib.suppress(tokenize.TokenError),  # 源码不完整时停止取注释
    ):
        found.extend(
            (token.start[0], token.string)
            for token in tokenize.generate_tokens(iter(text.splitlines(keepends=True)).__next__)
            if token.type == tokenize.COMMENT
        )
    return found


def _scan_file(path: Path) -> list[Hit]:
    """扫描单个文件，返回全部命中；带 `IGNORE` 标记的行跳过。"""
    rel = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()
    text = path.read_text(encoding="utf-8")
    hits: list[Hit] = []
    for line_no, line in _texts(text, path.suffix):
        if IGNORE in line:
            continue
        hits.extend(
            Hit(
                path=rel,
                line=line_no,
                text=line.strip()[:120],
                term=term.pattern.pattern,
                why=term.why,
            )
            for term in _LEXICON
            if _matches(term, line)
        )
    return hits


def _matches(term: Term, line: str) -> bool:
    """该行是否命中这条规则（含行首例外处理）。"""
    for match in term.pattern.finditer(line):
        if term.not_at_line_start and match.start() == 0:
            continue
        return True
    return False


def _absolute(item: str) -> Path:
    """把命令行条目折成绝对路径；相对路径按当前工作目录解析。"""
    candidate = Path(item)
    return candidate.resolve() if candidate.is_absolute() else (Path.cwd() / candidate).resolve()


def _skip_relative(rel: str, suffix: str) -> bool:
    """按**仓库相对路径**判断该路径是否排除在扫描之外。

    只认相对路径的组成部分：检出目录的祖先若名为 `build` / `dist` 等，
    不影响仓库内文件的判定。
    """
    if any(part in _SKIP_DIRS for part in PurePosixPath(rel).parts):
        return True
    if any(rel.startswith(prefix) for prefix in _MARKDOWN_SKIP):
        return True
    # API 参考页由 mkdocstrings 渲染，无自有散文
    return suffix == ".md" and rel.startswith("docs/api/")


def _targets(argv: list[str]) -> tuple[list[Path], list[str]]:
    """将命令行参数展开为待检文件；未提供参数时扫描全仓。

    返回 `(待检文件, 跳过的路径)`；仓库外的路径不进入扫描集，且显式列出。
    """
    given = [arg for arg in argv if not arg.startswith("--")]
    roots = [_absolute(item) for item in given] if given else [ROOT]
    found: list[Path] = []
    skipped: list[str] = []
    for root in roots:
        if not root.is_relative_to(ROOT):
            skipped.append(root.as_posix())
            continue
        if root.is_file():
            if root.suffix in _SUFFIXES and not _skip_relative(
                root.relative_to(ROOT).as_posix(), root.suffix
            ):
                found.append(root)
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in _SUFFIXES:
                continue
            if _skip_relative(path.relative_to(ROOT).as_posix(), path.suffix):
                continue
            found.append(path)
    return found, skipped


def main(argv: list[str]) -> int:
    """检查并报告；返回退出码。

    默认有命中即返回 1；`--report` 为报告模式，有命中仍返回 0。
    脚本自身的异常不在此处理，一律以非零退出码终止。
    """
    if "--list" in argv:
        for term in _LEXICON:
            _say(f"{term.pattern.pattern}\t{term.why}")
        return 0

    report_only = "--report" in argv
    hits: list[Hit] = []
    files, skipped = _targets(argv)
    for path in files:
        hits.extend(_scan_file(path))

    for item in skipped:
        _say(f"[prose] 跳过（不在本仓库内）：{item}")

    by_file: dict[str, int] = {}
    for hit in hits:
        by_file[hit.path] = by_file.get(hit.path, 0) + 1

    for shown, count in sorted(by_file.items(), key=lambda item: (-item[1], item[0])):
        _say(f"{count:>4}  {shown}")
    _say(f"\n[prose] 扫描 {len(files)} 个文件，命中 {len(hits)} 处。")
    if hits:
        _say("明细（最多 60 条）：")
        for hit in hits[:60]:
            _say(f"  {hit.path}:{hit.line}  [{hit.term}]  {hit.text}  （{hit.why}）")
        if len(hits) > 60:
            _say(f"  …… 其余 {len(hits) - 60} 处")
    if report_only:
        return 0
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

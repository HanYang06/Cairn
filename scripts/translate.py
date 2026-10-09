# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""英文译文生成器:把中文页送机器翻译,落成 `docs/**/*.en.md`(开发工具,不参与产品).

口径(见 `docs/reference/i18n-status.md` 与 `rules/references/docs.md`):

- **中文是事实基础**:`docs/**/*.md` 由作者写成,是原文;英文是**机器翻译的产物**.
- 译文落 `docs/**/*.en.md`;文件顶部记一条 `translation-source-hash`,那是**中文原文的摘要**,
  `--check` 靠它判"英文是否落后于中文".
- **只译正文**:围栏代码块整块保留;行内代码 / 链接 / 图片 / 裸露 URL 先摘出成占位符,
  译完原样放回(一译就断链,坏锚点);表格分隔行不动.
- **增量译,不从头来**:每次只处理"**缺英文页**"或"**英文页落后**"的那些页——
  已一致的页一个字符都不送.故译文一旦落库,后续运行只花增量.
- **手写页默认不动**:已有英文页若**没有**摘要行(即手写的),默认不覆盖;
  要让它纳入漂移追踪,用 `--stamp` 补上摘要行(只补行,不重译正文).
- 单次上限 5000 字符(阿里云文档),故按行分段;尾随空行归段落,不与正文一起送.

用法::

    uv run python scripts/translate.py --list            # 只报账:哪些页待译,多少字符
    uv run python scripts/translate.py --check           # 门禁:英文落后于中文即非零退出
    uv run python scripts/translate.py                   # 译"缺失或落后"的页
    uv run python scripts/translate.py --stamp           # 只给手写英文页补摘要行(不重译)
    uv run python scripts/translate.py --force           # 全部重译(连已一致的)
    uv run python scripts/translate.py --force 页面...   # 重译指定页

需要环境变量(CI 里由 secret 给):
``ALIBABA_CLOUD_ACCESS_KEY_ID`` 与 ``ALIBABA_CLOUD_ACCESS_KEY_SECRET``.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # 直接跑脚本时,`tools` 未必在导入路径上
    sys.path.insert(0, str(ROOT))

from tools._iosafe import _say  # noqa: E402 — 见上:先补路径再导入

DOCS = ROOT / "docs"
SUFFIX = ".en.md"

#: 阿里云机器翻译通用版的端点(国内站,杭州).
#: **不带 `RegionId` 参数**:它属公共请求参数,但 `TranslateGeneral`(2018-10-12)
#: 不认它;带上会拿到一个既非 200 码,又没有 `Data` 的响应,白花一次调用.
ENDPOINT = "mt.cn-hangzhou.aliyuncs.com"

#: 单次请求的字符上限(官方文档:5000);留余量,占位符与标点也要算进去
_MAX_CHUNK = 4000

#: 原文摘要行:插在 SPDX 头之后
_HASH_LINE = "<!-- translation-source-hash: {digest} -->"
_HASH_RE = re.compile(r"<!-- translation-source-hash: ([0-9a-f]{64}) -->")

#: 行内不该送译的片段.
#: **顺序即优先级**(一次扫描,最长匹配优先):图片要排在链接前面,否则 `!` 会留在正文里;
#: 行内代码与裸露 URL 各自独立.
_INLINE_PATTERN = re.compile(
    # 一条 alternation 就是一组正则字面量:`"|".join` 在这里比 f-string 更看得清边界.
    "|".join(  # noqa: FLY002 — 见上:这里要的是"多条正则相加",不是格式化
        (
            r"`[^`]*`",  # 行内代码
            r"!\[[^\]]*\]\([^)]*\)",  # 图片(连文字一起摘)
            r"\[[^\]]*\]\([^)]*\)",  # 链接(连文字一起摘:URL 与目标文件都不该译)
            r"<?https?://\S+>?",  # 裸露 URL
            r"<!--[\s\S]*?-->",  # HTML 注释(用 [\s\S] 而非 .:跨行注释也要整段摘掉)
        ),
    ),
)
#: 围栏代码块
_FENCE = re.compile(r"^\s*(?:```|~~~)")
#: 表格分隔行(|---|---|)
_TABLE_RULE = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")
#: 占位符.用**私有区**字符(`U+E000` 起),两个理由:
#: ① 不能用数字字形——它会被上面的行内规则当成普通文本吞进别的片段里(实测踩过);
#: ② 不能用控制字符——`\x0a` / `\x0d` / `\x1c` 这类会被 `str.splitlines()` 当换行,
#:    还原后一行会被切成两行(也实测踩过:一行里第 10 个占位符恰好是 `\x0a`).
_TOKEN_BASE = 0xE000
_PLACEHOLDER = re.compile("[\ue000-\uf8ff]")

#: 中英对应的语言码(阿里云文档:zh / en)
_LANGS = {"zh": "zh", "en": "en"}


@dataclass
class Doc:
    """一页的账."""

    path: Path
    text: str

    @property
    def source_hash(self) -> str:
        """中文原文的摘要(不含译文头那一行)."""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def rel(self) -> str:
        """仓库相对路径."""
        return self.path.relative_to(ROOT).as_posix()

    @property
    def target(self) -> Path:
        """对应的英文页路径."""
        return self.path.with_name(self.path.name[: -len(".md")] + SUFFIX)


# ---- 页面清单 ----
def _source_pages() -> list[Doc]:
    """中文页清单(不带 `.en` 后缀的那些),按路径排序."""
    pages = sorted(p for p in DOCS.rglob("*.md") if not p.name.endswith(SUFFIX))
    return [Doc(path=p, text=p.read_text(encoding="utf-8")) for p in pages]


def _existing_hash(target: Path) -> str | None:
    """英文页里记的原文摘要;没有那个头返回 None."""
    if not target.is_file():
        return None
    found = _HASH_RE.search(target.read_text(encoding="utf-8"))
    return found.group(1) if found else None


# ---- 分段:哪些行送译,哪些原样保留 ----
def _protect(line: str, store: list[str]) -> str:
    """把行内不该送译的片段换成占位符,返回可送译的那一行."""

    def swap(match: re.Match[str]) -> str:
        store.append(match.group(0))
        return _token(len(store) - 1)

    return _INLINE_PATTERN.sub(swap, line)


def _token(index: int) -> str:
    """第 `index` 个占位符的字符(私有区,从 `U+E000` 起)."""
    return chr(_TOKEN_BASE + index)


def _restore(text: str, store: list[str]) -> str:
    """把占位符换回原片段."""

    def back(match: re.Match[str]) -> str:
        index = ord(match.group(0)) - _TOKEN_BASE
        return store[index] if 0 <= index < len(store) else match.group(0)

    return _PLACEHOLDER.sub(back, text)


@dataclass
class Unit:
    """送译单位:一段可整段交给 API 的行;`keep=True` 表示原样保留,不送."""

    keep: bool
    lines: list[str]


def _units(text: str) -> list[Unit]:
    """把一页切成送译单位:围栏代码块/表格分隔行整块保留,其余成段."""
    units: list[Unit] = []
    buffer: list[str] = []
    in_fence = False

    def flush() -> None:
        if buffer:
            units.append(Unit(keep=False, lines=list(buffer)))
            buffer.clear()

    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if _FENCE.match(line):
            flush()
            block = [line]
            in_fence = not in_fence
            index += 1
            while index < len(lines):
                block.append(lines[index])
                if _FENCE.match(lines[index]):
                    in_fence = not in_fence
                    index += 1
                    break
                index += 1
            if in_fence:  # 未闭合的围栏:整块保留(不猜)
                in_fence = False
            units.append(Unit(keep=True, lines=block))
            continue
        if line.startswith("    ") and line.strip():  # 缩进代码块
            flush()
            units.append(Unit(keep=True, lines=[line]))
            index += 1
            continue
        if _TABLE_RULE.match(line):
            flush()
            units.append(Unit(keep=True, lines=[line]))
            index += 1
            continue
        if not line.strip():  # 空行:段落边界,原样保留
            flush()
            units.append(Unit(keep=True, lines=[line]))
            index += 1
            continue
        buffer.append(line)
        if sum(len(x) for x in buffer) >= _MAX_CHUNK:
            flush()
        index += 1
    flush()
    return units


# ---- 翻译 ----
# 阿里云 RPC 风格接口的签名**自己算**,不引官方 SDK:
# ① 签名算法就三步(HMAC-SHA1 + RFC3986 百分号编码),官方给了纯标准库的示例;
# ② SDK 会拖进三十来个传递依赖,而这里只需要"一个 HTTPS GET";
# ③ 引了它还得在 deptry / mypy 上开豁免(dev 依赖被产品代码 import,tea 是传递依赖),
#    而那两条规则本来是对的——不该为了让一个开发脚本进来就放宽它们.
# 算法依据:https://help.aliyun.com/zh/ocr/developer-reference/signature-method


def _percent_encode(value: str) -> str:
    """RFC3986 百分号编码:空格编 `%20`(不是 `+`),`~` 不编."""
    return quote(value, safe="~")


def _signature(params: dict[str, str], secret: str, method: str = "GET") -> str:
    """按阿里云 RPC 规则算签名(参数名与值各编一次,再整体编一次).

    这里用 HMAC-SHA1 **是接口规范规定的,不是可选的强度选择**:`SignatureMethod`
    只支持 `HMAC-SHA1`,换 SHA-256 会被服务端拒签;而且它是**消息认证码**,
    不是拿哈希保护明文或口令. CodeQL 的 `py/weak-sensitive-data-hashing` 命中的是后者,
    故这条按配置式过滤排除(理由与写法见 `.github/workflows/codeql.yml`).
    """
    canonical = "&".join(
        f"{_percent_encode(k)}={_percent_encode(v)}" for k, v in sorted(params.items())
    )
    string_to_sign = f"{method}&{_percent_encode('/')}&{_percent_encode(canonical)}"
    # codeql[py/weak-sensitive-data-hashing] 协议强制 HMAC-SHA1,理由见 docstring
    digest = hmac.new(f"{secret}&".encode(), string_to_sign.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def _request(source_text: str, *, source_lang: str, target_lang: str) -> dict[str, object]:
    """调一次通用版翻译;返回解析后的 JSON."""
    key_id = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID", "")
    key_secret = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "")
    if not key_id or not key_secret:
        _say(
            "[translate] 缺凭证：需要 ALIBABA_CLOUD_ACCESS_KEY_ID 与 "
            "ALIBABA_CLOUD_ACCESS_KEY_SECRET。"
        )
        raise SystemExit(2)
    params = {
        "Action": "TranslateGeneral",
        "Version": "2018-10-12",
        "Format": "JSON",
        "AccessKeyId": key_id,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureVersion": "1.0",
        "SignatureNonce": str(uuid.uuid4()),
        "Timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "FormatType": "text",
        "Scene": "general",
        "SourceLanguage": _LANGS[source_lang],
        "TargetLanguage": _LANGS[target_lang],
        "SourceText": source_text,
    }
    params["Signature"] = _signature(params, key_secret)
    # **自己拼查询串,不走 `urlencode`**:签名里的百分号编码按 RFC3986(空格 = `%20`),
    # 而 `urlencode` 默认把空格写成 `+`.
    # 且 **`Signature` 本身不再编码**:阿里云文档给的是
    # `url += "&Signature=" + percentEncode(signature)` 之后又原样拼进链接的写法,
    # 而 SDK 的等价做法是"值不编码".实测把 `+` `/` `=` 再编码会让服务端验签失败——
    # 表现为 HTTP 200 却没有 `Data.Translated`(线上就是这么红的).
    query = "&".join(
        f"{_percent_encode(k)}={_percent_encode(v)}" for k, v in params.items() if k != "Signature"
    )
    url = f"https://{ENDPOINT}/?{query}&Signature={params['Signature']}"
    try:
        # 端点是本模块的常量(`https://mt.cn-hangzhou.aliyuncs.com/`),不由外部输入决定.
        with urlopen(url, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"翻译接口 HTTP {error.code}：{detail}") from error
    except URLError as error:
        raise RuntimeError(f"翻译接口连不上：{error.reason}") from error
    try:
        payload: dict[str, object] = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"翻译接口返回的不是 JSON：{raw[:300]}") from error
    return payload


def _succeeded(payload: dict[str, object]) -> bool:
    """这个响应算不算成功.

    **`Code` 要按字符串比**:本接口把 `Code` 当字符串返回(实测 `"Code": "200"`,
    不是整数 `200`),而 `Data.WordCount` 也是字符串.按整数比会把成功的响应当成失败
    ——探针与 `_translate` 都踩在同一处,线上表现为"探针里译文都拿到了却仍退出 1".
    先归一成字符串再比,整数写法与字符串写法都认,免得接口哪天改回去时又坏一次.
    """
    code = payload.get("Code")
    return str(code) == "200"


def _translate(source: str, *, source_lang: str, target_lang: str) -> str:
    """调一次通用版翻译;返回译文.失败即抛,由调用方决定怎么报."""
    payload = _request(source, source_lang=source_lang, target_lang=target_lang)
    if not _succeeded(payload):
        raise RuntimeError(f"翻译接口返回异常：{_brief(payload)}")
    data = payload.get("Data")
    if not isinstance(data, dict) or not data.get("Translated"):
        raise RuntimeError(f"翻译接口返回异常：{_brief(payload)}")
    return str(data["Translated"])


def _brief(payload: dict[str, object]) -> str:
    """把响应压成一行便于看日志(完整 JSON 可能很长,且含不了什么机密)."""
    return json.dumps(payload, ensure_ascii=False)[:500]


def _translate_page(text: str, *, sent: list[int]) -> str:
    """把一页的正文译成英文,结构原样保留."""
    out: list[str] = []
    for unit in _units(text):
        if unit.keep:
            out.extend(unit.lines)
            continue
        store: list[str] = []
        prepared = [_protect(line, store) for line in unit.lines]
        payload = "\n".join(prepared)
        sent.append(len(payload))
        translated = _translate(payload, source_lang="zh", target_lang="en")
        out.extend(_restore(line, store) for line in translated.splitlines())
    return "\n".join(out) + "\n"


def _with_header(source: Doc, translated: str) -> str:
    """给译文加 SPDX 头与原文摘要行.

    译文正文里可能残留中文页的 SPDX 头(它也是正文的一部分,会被送译),
    故先把开头连续的 SPDX 注释行整段剥掉,再套上本工具自己的头.
    """
    body = translated.lstrip("\ufeff\n")
    while body.startswith("<!-- SPDX-"):
        body = body.split("\n", 1)[1] if "\n" in body else ""
        body = body.lstrip()
    head = (
        "<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->\n"
        "<!-- SPDX-License-Identifier: Apache-2.0 -->\n"
        f"{_HASH_LINE.format(digest=source.source_hash)}\n"
    )
    return head + body


# ---- 入口 ----
def needs_translation(page: Doc) -> bool:
    """这一页该不该(重新)译:**缺英文页**,或**英文页落后于中文**.

    判据与 `--check` 同一套(都是拿头部那条 `translation-source-hash` 比),
    故"门禁报落后"与"生成器会去重译"永远是同一件事.
    已有英文页但**没有摘要行**的算"手写页"——默认不动它(`--stamp` 可纳入追踪).
    """
    if not page.target.is_file():
        return True
    recorded = _existing_hash(page.target)
    return recorded is not None and recorded != page.source_hash


def _planned(pages: list[Doc], *, force: bool) -> list[Doc]:
    """该动手的页:缺失或落后的那些;`--force` 下是全部."""
    if force:
        return pages
    return [page for page in pages if needs_translation(page)]


def _stamp(pages: list[Doc]) -> int:
    """给**已有的手写英文页**补上摘要行(不重译其正文);返回补了几页."""
    count = 0
    for page in pages:
        if not page.target.is_file() or _existing_hash(page.target) is not None:
            continue
        text = page.target.read_text(encoding="utf-8")
        head = _HASH_LINE.format(digest=page.source_hash)
        lines = text.splitlines(keepends=True)
        # 插在 SPDX 头之后(与 `_with_header` 的位置一致)
        at = 0
        while at < len(lines) and lines[at].lstrip().startswith("<!-- SPDX-"):
            at += 1
        page.target.write_text("".join([*lines[:at], f"{head}\n", *lines[at:]]), encoding="utf-8")
        _say(f"[translate] 已补摘要行 {page.target.relative_to(ROOT).as_posix()}")
        count += 1
    return count


def _check(pages: list[Doc], *, strict: bool = True) -> int:
    """门禁:英文缺失或落后于中文即失败;`strict=False` 时只报账,不失败.

    `strict=False` 是给 CI 用的过渡态:译文还没补齐时,工作流**不能红**
    (`continue-on-error` 在 job 级也只改展示,不改结论,实测无效),
    故先跑非阻断的报账;等 14 页译完,把工作流那一步换成默认(strict)即成真门禁.
    """
    stale: list[str] = []
    for page in pages:
        target = page.target
        if not target.is_file():
            stale.append(f"缺英文页：{page.rel}")
            continue
        recorded = _existing_hash(target)
        if recorded is None:
            continue  # 手写的英文页没有摘要行,不参与判漂移
        if recorded != page.source_hash:
            stale.append(f"英文落后于中文：{target.relative_to(ROOT).as_posix()}")
    for item in stale:
        _say(f"[translate] {item}")
    if stale:
        tail = "跑 `uv run python scripts/translate.py`。" if strict else "（报账模式，不判失败）"
        _say(f"[translate] 共 {len(stale)} 页待译/待更新：{tail}")
        return 1 if strict else 0
    _say(f"[translate] {len(pages)} 页译文与原文一致。")
    return 0


def main(argv: list[str]) -> int:
    """按参数执行:报账 / 门禁 / 补摘要 / 翻译."""
    parser = argparse.ArgumentParser(description="英文译文生成器（阿里云机器翻译）")
    parser.add_argument("--list", action="store_true", help="只列出待译页与字符量")
    parser.add_argument("--check", action="store_true", help="门禁：英文落后于中文即非零退出")
    parser.add_argument(
        "--report",
        action="store_true",
        help="报账：与 --check 同判据，但**不判失败**（译文补齐前的过渡态用）",
    )
    parser.add_argument("--force", action="store_true", help="连已一致的英文页一起重译")
    parser.add_argument(
        "--stamp",
        action="store_true",
        help="只给已有的手写英文页补摘要行（不重译正文），让它纳入漂移追踪",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="自检：只送两个字符并打印原始响应（排查凭证 / 签名 / 端点用，几乎不耗额度）",
    )
    parser.add_argument("pages", nargs="*", help="只处理这些页（仓库相对路径，可省）")
    args = parser.parse_args(argv)

    pages = _source_pages()
    if args.pages:
        wanted = {p.replace("\\", "/") for p in args.pages}
        pages = [p for p in pages if p.rel in wanted]

    if args.check or args.report:
        return _check(_source_pages(), strict=not args.report)
    if args.stamp:
        count = _stamp(pages)
        _say(f"[translate] 共补 {count} 页摘要行。")
        return 0
    if args.probe:
        # 只送两个字符:足以验明"凭证对不对,签名认不认,端点通不通",几乎不耗额度.
        payload = _request("你好", source_lang="zh", target_lang="en")
        _say(f"[translate] 探针响应：{_brief(payload)}")
        data = payload.get("Data")
        ok = _succeeded(payload) and isinstance(data, dict) and bool(data.get("Translated"))
        return 0 if ok else 1

    planned = _planned(pages, force=args.force)
    if args.list or not planned:
        for page in planned:
            _say(f"{page.rel}  ->  {page.target.relative_to(ROOT).as_posix()}")
        _say(
            f"[translate] 待译 {len(planned)} 页，原文共 {sum(len(p.text) for p in planned)} 字符。"
        )
        return 0

    sent: list[int] = []
    for page in planned:
        translated = _translate_page(page.text, sent=sent)
        page.target.write_text(_with_header(page, translated), encoding="utf-8")
        _say(f"[translate] 已生成 {page.target.relative_to(ROOT).as_posix()}")
    _say(f"[translate] {len(planned)} 页完成，送译 {sum(sent)} 字符（免费额度 100 万/月）。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

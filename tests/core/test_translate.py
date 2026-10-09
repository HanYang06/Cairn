# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""机翻请求的线形状与判据:三处都是线上踩出来的坑,故钉住.

- **请求形状照官方 SDK**:`method='POST'`,业务参数进 `application/x-www-form-urlencoded`
  body,正文只在 body 里——曾经 GET 到查询串,最长一条请求行 17 KB;
- **`Signature` 按值编码一次**:base64 里会出现 `+` / `/` / `=`,而裸 `+` 到服务端会被
  表单式解码还原成空格,验签随即失败(`HTTP 400 ... signature is not matched`);
- **`Code` 是字符串** `"200"`:按整数比会把**已经拿到译文**的成功响应判成失败.

这些用例不联网:`urlopen` 与 `_translate` 都换成假的,验的是"发出去的那一份长什么样".
"""

from __future__ import annotations

import importlib.util
import sys
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, unquote_plus, urlsplit
from urllib.request import Request

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from contextlib import AbstractContextManager
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]

_OK_BODY = '{"Code": "200", "Data": {"WordCount": "2", "Translated": "Hello"}}'


def _load() -> ModuleType:
    """把 `scripts/translate.py` 当模块装进来(它不是包,故走 `spec_from_file_location`)."""
    path = REPO_ROOT / "scripts" / "translate.py"
    spec = importlib.util.spec_from_file_location("translate_tool", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["translate_tool"] = module
    spec.loader.exec_module(module)
    return module


TOOL = _load()


@contextmanager
def _reply(payload: str = _OK_BODY) -> Iterator[BytesIO]:
    """假响应:只满足 `urlopen` 上下文管理器与 `read()` 两件事."""
    yield BytesIO(payload.encode("utf-8"))


def _spy(monkeypatch: pytest.MonkeyPatch, seen: dict[str, str]) -> None:
    """把 `urlopen` 换掉,把收到的那一份请求记进 `seen`.

    真的 `urlopen` 也是这两个位置参数(`url` 与 `data`),故这里照原样收:
    **方法由"有没有 data"决定**,这一点交给 `Request` 自己判,不由本用例替它说.
    """

    def fake(url, data=None, **_kwargs: object) -> AbstractContextManager[BytesIO]:
        # `S310` 关掉:这里只是借 `Request` 判"算不算 POST",不发任何请求.
        request = Request(url, data=data)  # noqa: S310
        seen["method"] = request.get_method()
        seen["url"] = request.full_url
        seen["body"] = (data or b"").decode("utf-8")
        return _reply()

    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "test-id")
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "test-secret")
    monkeypatch.setattr(TOOL, "urlopen", fake)


def test_request_is_post_form_and_signature_survives_form_decoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST + 表单 body;且签名里那个 `+` 到服务端还原得回来.

    签名逐次随机(`SignatureNonce` / `Timestamp` 都参与),故抽到带 `+` 的那一次再断言
    ——那正是线上炸掉的那一个字符.
    """
    seen: dict[str, str] = {}
    _spy(monkeypatch, seen)
    text = "一行正文 a b\n`code` 与 [链接](a.md)\n"

    params: dict[str, str] = {}
    raw_signature = ""
    for _ in range(200):
        TOOL._request(text, source_lang="zh", target_lang="en")
        params = dict(parse_qsl(seen["body"]))
        raw_signature = seen["url"].split("Signature=", 1)[1]
        if "+" in unquote_plus(raw_signature):
            break
    else:  # pragma: no cover — 200 次都抽不到带 `+` 的签名,用例已失去意义
        pytest.fail("200 次都没抽到带 `+` 的签名,用例失效")

    assert seen["method"] == "POST"
    assert [key for key, _ in parse_qsl(urlsplit(seen["url"]).query)] == ["Signature"]
    assert params["SourceText"] == text, "正文要能原样从表单里解回来"
    assert "SourceText" not in seen["url"], "正文不许进 URL"
    # 服务端拿到的是"表单解码后的值",它必须与我们签的那一份逐字相同
    assert unquote_plus(raw_signature) == TOOL._signature(params, "test-secret")


def test_succeeded_accepts_string_code() -> None:
    """`Code` 是字符串 `"200"`;判据两种写法都认,别的都不认."""
    assert TOOL._succeeded({"Code": "200"}) is True
    assert TOOL._succeeded({"Code": 200}) is True
    assert TOOL._succeeded({"Code": "400"}) is False
    assert TOOL._succeeded({"Code": None}) is False
    assert TOOL._succeeded({"Code": ""}) is False


def test_translate_page_roundtrip_keeps_structure(monkeypatch: pytest.MonkeyPatch) -> None:
    """恒等翻译下整页往返逐字节一致:分段,占位符,围栏都不许改到正文以外的东西."""
    monkeypatch.setattr(TOOL, "_translate", lambda text, **_kwargs: text)
    text = (
        "# 标题\n\n"
        "正文里有 `code` 与 [链接](a.md),还有 https://example.com/x?a=b\n\n"
        "```\n不译的围栏\n```\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n"
    )
    assert TOOL._translate_page(text, sent=[]) == text

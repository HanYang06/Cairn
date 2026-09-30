# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""边车契约：帧怎么读写、循环怎么转、出错怎么回。

帧协议那几条在这里钉死：长度按**字节**算、读不满即报、坏帧收工不硬撑。
"""

from __future__ import annotations

import base64
import io
import json
from typing import TYPE_CHECKING

import pytest

from app.sidecar import FrameError, answer, main, read_frame, serve, write_frame
from core.api import Api
from core.exc import CairnError
from core.init import Kernel

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Api]:
    """一个接了临时库的命令面。"""
    with Kernel.create(tmp_path / "vault") as kernel:
        yield Api(kernel)


def _frame(payload: object) -> bytes:
    """把一条消息编成帧字节（测试里当"对面发来的东西"）。"""
    stream = io.BytesIO()
    write_frame(stream, payload)
    return stream.getvalue()


def _b64(text: str) -> str:
    """把一段文本编成 base64（命令面里二进制的写法）。"""
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


# ---- 帧的读写 ----


def test_frame_roundtrip():
    """写一帧再读回来：内容一字不差。"""
    stream = io.BytesIO(_frame({"id": 1, "method": "blocks"}))

    assert read_frame(stream) == {"id": 1, "method": "blocks"}
    assert read_frame(stream) is None, "读完就该到流尾"


def test_frame_length_counts_bytes_not_characters():
    """长度写的是字节数：中文不会被算少。"""
    payload = {"id": 1, "method": "store", "params": {"data": "中文正文"}}
    raw = _frame(payload)

    head = raw.split(b"\r\n\r\n", 1)[0]
    declared = int(head.split(b":", 1)[1])

    assert declared == len(raw.split(b"\r\n\r\n", 1)[1]), "声明的是字节数"
    assert read_frame(io.BytesIO(raw)) == payload


def test_two_frames_in_one_stream():
    """两条帧连着发：读方按长度切得开，不会把两条粘成一条。"""
    stream = io.BytesIO(_frame({"id": 1}) + _frame({"id": 2}))

    assert read_frame(stream) == {"id": 1}
    assert read_frame(stream) == {"id": 2}


def test_missing_length_is_refused():
    """头里没有长度：报错，不猜。"""
    stream = io.BytesIO(b"X-Other: 1\r\n\r\n{}")

    with pytest.raises(FrameError, match="没有 Content-Length"):
        read_frame(stream)


def test_truncated_body_is_refused():
    """正文读不满：报错，不把半条当成一条。"""
    stream = io.BytesIO(b"Content-Length: 100\r\n\r\n{}")

    with pytest.raises(FrameError, match="读不满"):
        read_frame(stream)


def test_non_object_body_is_refused():
    """正文必须是 JSON 对象：顶层是数组不算。"""
    body = json.dumps([1, 2]).encode("utf-8")
    stream = io.BytesIO(b"Content-Length: %d\r\n\r\n%s" % (len(body), body))

    with pytest.raises(FrameError, match="JSON 对象"):
        read_frame(stream)


# ---- 派发与回答 ----


def test_answer_pairs_the_identifier(api: Api):
    """回答带回来时的 `id`：对面靠它配对。"""
    reply = answer(api, {"id": 7, "method": "blocks"})

    assert reply["id"] == 7
    assert reply["ok"] is True


def test_answer_reports_a_bad_request(api: Api):
    """方法名不是字符串：回失败帧，不抛。"""
    reply = answer(api, {"id": 1, "method": 7})

    assert reply["ok"] is False
    assert _kind(reply) == "InvalidRequest"


def test_answer_reports_a_kernel_error(api: Api):
    """内核抛的错折成失败帧，带异常类名——界面按它分流。"""
    reply = answer(api, {"id": 1, "method": "load", "params": {"uuid": "没有"}})

    assert reply["ok"] is False
    assert _kind(reply) == "ObjectNotFoundError"


def test_answer_reports_an_unexpected_error(api: Api, monkeypatch: pytest.MonkeyPatch):
    """没料到的错也回帧：边车不能为一个 bug 当场死掉。"""

    def boom(_method: str, _params: object = None) -> object:
        raise RuntimeError("没料到")

    monkeypatch.setattr(api, "call", boom)

    reply = answer(api, {"id": 1, "method": "blocks"})

    assert reply["ok"] is False
    assert _kind(reply) == "InternalError"


# ---- 服务循环 ----


def test_serve_answers_every_request(api: Api):
    """喂两条请求，收回两条回答；流到尾即收工。"""
    stream = _frame({"id": 1, "method": "blocks"}) + _frame({"id": 2, "method": "survey"})
    stdout = io.BytesIO()

    handled = serve(api, stdin=io.BytesIO(stream), stdout=stdout)

    replies = _replies(stdout.getvalue())
    assert handled == 2
    assert [reply["id"] for reply in replies] == [1, 2]
    assert all(reply["ok"] for reply in replies)


def test_serve_ends_on_a_broken_frame_without_answering(api: Api):
    """帧读不出来就收工：那时流已经不能保证对齐，再写只会更乱。"""
    stdout = io.BytesIO()

    handled = serve(api, stdin=io.BytesIO(b"Content-Length: 99\r\n\r\n{}"), stdout=stdout)

    assert handled == 0
    assert stdout.getvalue() == b""


def test_serve_keeps_going_after_a_failed_call(api: Api):
    """一次调用失败不影响后面的：错误是回答，不是终止。"""
    stream = _frame({"id": 1, "method": "load", "params": {"uuid": "没有"}}) + _frame(
        {"id": 2, "method": "blocks"}
    )
    stdout = io.BytesIO()

    handled = serve(api, stdin=io.BytesIO(stream), stdout=stdout)

    replies = _replies(stdout.getvalue())
    assert handled == 2
    assert [reply["ok"] for reply in replies] == [False, True]


# ---- 入口 ----


def test_main_needs_exactly_one_argument(capsys: pytest.CaptureFixture[str]):
    """库根必须显式给：内核没有库旋钮，路径约定只在 core 里定。"""
    assert main([]) == 2
    assert main(["a", "b"]) == 2
    assert "用法" in capsys.readouterr().err


def test_serve_pushes_events_as_notification_frames(api: Api):
    """存一条会触发事件：**回答之前**先来一条通知帧，而且它没有 `id`。"""
    request = _frame({"id": 1, "method": "store", "params": {"data": _b64("x")}})
    stdout = io.BytesIO()

    serve(api, stdin=io.BytesIO(request), stdout=stdout)

    frames = _replies(stdout.getvalue())
    notices = [frame for frame in frames if "event" in frame]
    replies = [frame for frame in frames if "id" in frame]

    assert [_event_type(notice) for notice in notices] == ["object.put"]
    assert len(replies) == 1
    assert replies[0]["ok"] is True


def test_notifications_can_be_turned_off(api: Api):
    """关掉推送就只剩回答：给"只想一问一答"的调用方留个口子。"""
    request = _frame({"id": 1, "method": "store", "params": {"data": _b64("x")}})
    stdout = io.BytesIO()

    serve(api, stdin=io.BytesIO(request), stdout=stdout, notify=False)

    assert all("event" not in frame for frame in _replies(stdout.getvalue()))


def _event_type(frame: Mapping[str, object]) -> object:
    """取一条通知帧里的类型名。"""
    event = frame["event"]
    assert isinstance(event, dict)
    return event["type"]


def _replies(raw: bytes) -> list[Mapping[str, object]]:
    """把一段输出切成帧解回来。"""
    stream = io.BytesIO(raw)
    found: list[Mapping[str, object]] = []
    while True:
        frame = read_frame(stream)
        if frame is None:
            return found
        found.append(frame)


def _kind(reply: Mapping[str, object]) -> object:
    """取失败帧里那个"是哪一类错"的字段。"""
    error = reply["error"]
    assert isinstance(error, dict)
    return error["kind"]


def test_cairn_error_is_the_base_of_frame_error():
    """帧异常挂在内核兜底异常下：调用方一句 `except CairnError` 就能兜住全部。"""
    assert issubclass(FrameError, CairnError)

# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
r"""边车：把命令面接到 stdio 上的一条帧协议。

壳把 Python 当**子进程**起，两边走标准输入输出收发帧。协议与 LSP 同款：

    Content-Length: 123\\r\\n\\r\\n{"id": 7, "method": "store", "params": {...}}

**为什么要长度头**：stdin/stdout 是字节流、没有消息边界，一次读到的可能是半条、也可能是
两条半。头里的长度是**字节数**（不是字符数），故中文不会算错。

**为什么不用 HTTP**：本地两个进程之间不需要网络栈；开端口还要处理端口冲突、防火墙与
"谁能连上这个端口"的安全面。stdio 另有一个天然好处——**生命周期绑死**：边车死了管道即断，
壳当场就知道，不必靠心跳去猜。

**日志绝不写 stdout**：那条流是帧的通道，掺一行日志就会让对面解析失败。日志走 stderr。

**方向**：请求 → 回答是**配对**的（带 `id`）；内核 → 壳是**单向推送**的通知帧，
由 `serve` 把事件日志的**反馈那一路**接成帧，循环收工即撤掉——订阅本身只发生在
`core.event.logs` 那一处。
"""

from __future__ import annotations

import json
import logging
import sys
from typing import TYPE_CHECKING

from core.api import Api
from core.exc import CairnError
from core.init import Kernel

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from typing import BinaryIO

    from core.event.events import Event

FRAME_HEADER = "Content-Length"
"""帧头的字段名：与 LSP 同款。"""

_LENGTH_HEADER = b"content-length"
_HEADER_END = (b"\r\n", b"\n")

_LOGGER = logging.getLogger("cairn.sidecar")


class FrameError(CairnError):
    """帧不成形：头里没有长度、正文读不满，或正文不是 JSON 对象。

    它是**协议层**的错，故不放进 `core.exc`：内核不认识帧，也就不该有帧的异常。
    """


def read_frame(stream: BinaryIO) -> dict[str, object] | None:
    """读一帧；流到尾即 `None`（对面关了管道）。

    Raises:
        FrameError: 头里没有长度、正文读不满，或正文不是 JSON 对象。
    """
    length: int | None = None
    while True:
        line = stream.readline()
        if not line:
            return None
        if line in _HEADER_END:
            break
        name, _, value = line.partition(b":")
        if name.strip().lower() == _LENGTH_HEADER:
            try:
                length = int(value.strip())
            except ValueError as error:
                raise FrameError(f"帧头的长度不是整数: {value!r}") from error
    if length is None:
        raise FrameError(f"帧头里没有 {FRAME_HEADER}")
    body = stream.read(length)
    if len(body) != length:
        raise FrameError(f"正文读不满: 要 {length} 字节，只读到 {len(body)}")
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as error:
        raise FrameError(f"正文不是 JSON: {error}") from error
    if not isinstance(decoded, dict):
        raise FrameError(f"正文必须是 JSON 对象: 收到 {type(decoded).__name__}")
    return decoded


def write_frame(stream: BinaryIO, payload: object) -> None:
    """写一帧。长度写的是**字节数**，故中文照算不错。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    head = f"{FRAME_HEADER}: {len(body)}\r\n\r\n".encode("ascii")
    stream.write(head)
    stream.write(body)
    stream.flush()


def serve(api: Api, *, stdin: BinaryIO, stdout: BinaryIO, notify: bool = True) -> int:
    """读帧 → 派发 → 回帧，直到流尾；返回处理过多少帧。

    每一帧都回一条 `{"id": …, "ok": …}`，**失败也回**（带异常类名）——让边车为一个参数
    错误当场崩掉，对使用者更糟。但**帧本身读不出来**时不回：那时流已经没法保证对齐，
    再写只会让对面更困惑，直接收工更诚实。

    `notify` 为真（默认）时把事件接成通知帧——那是这条链的**另一个方向**：请求 → 回答
    是配对的，内核 → 壳是单向推送，对面按"有没有 `id`"把两者分开。**反馈只在这一趟循环
    里有效**：收工即撤掉，不再往一条已经结束的流上写。

    事件在写路径里**同步**触发，而这一层是单线程的一问一答，故一条通知只会排在"它引发的
    那条回答"**之前**，不会与别的帧交错——那是"不引异步"换来的一个便宜。
    """
    sink = _notifier(stdout) if notify else None
    if sink is not None:
        api.kernel.event_log.add_feedback(sink)
    try:
        count = 0
        while True:
            try:
                request = read_frame(stdin)
            except FrameError:
                _LOGGER.exception("帧读不出来，收工")
                return count
            if request is None:
                return count
            write_frame(stdout, answer(api, request))
            count += 1
    finally:
        if sink is not None:
            api.kernel.event_log.remove_feedback(sink)


def _notifier(stdout: BinaryIO) -> Callable[[Event], None]:
    """造一个只认这条流的反馈去向：事件来了就写一条通知帧。"""

    def notify(event: Event) -> None:
        write_frame(stdout, _notification(event))

    return notify


def _notification(event: Event) -> dict[str, object]:
    """一条通知帧：**没有 `id`**，对面按这一条与"回答"区分开。"""
    return {"event": {"type": event.type, "subject": event.subject, "data": event.data}}


def answer(api: Api, request: Mapping[str, object]) -> dict[str, object]:
    """把一条请求派成一条回答：**永远回**，不把异常抛出去。"""
    identifier = request.get("id")
    method = request.get("method")
    if not isinstance(method, str):
        return _failed(identifier, "InvalidRequest", "method 必须是字符串")
    params = request.get("params")
    if params is not None and not isinstance(params, dict):
        return _failed(identifier, "InvalidRequest", "params 必须是映射或省略")
    try:
        result = api.call(method, params)
    except CairnError as error:
        return _failed(identifier, type(error).__name__, str(error))
    except Exception as error:  # 边车不能因为一个没料到的错就当场死掉
        _LOGGER.exception("命令抛了没料到的错: %s", method)
        return _failed(identifier, "InternalError", str(error))
    return {"id": identifier, "ok": True, "result": result}


def main(argv: Sequence[str] | None = None) -> int:
    """边车入口：``python -m app.sidecar <库根>``。

    库根由调用方显式给出——**内核没有库旋钮**，路径约定只在 `core/init.py` 定。
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        sys.stderr.write("用法: python -m app.sidecar <库根>\n")
        return 2
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    with Kernel.create(arguments[0]) as kernel:
        handled = serve(Api(kernel), stdin=sys.stdin.buffer, stdout=sys.stdout.buffer)
    _LOGGER.info("边车收工，处理了 %d 帧", handled)
    return 0


def _failed(identifier: object, kind: str, message: str) -> dict[str, object]:
    """一条失败的回答：`kind` 是异常类名，界面按它分流。"""
    return {"id": identifier, "ok": False, "error": {"kind": kind, "message": message}}


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["FRAME_HEADER", "FrameError", "answer", "main", "read_frame", "serve", "write_frame"]

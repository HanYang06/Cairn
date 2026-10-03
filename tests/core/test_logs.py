# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""事件日志契约:一次订阅,按表分流,三处落点各不回流.

这里的每一条都是行为契约:换一版实现时,这些用例必须照样通过.判据集中在四处——
**表与目录同源**,**落盘是 JSON Lines**,**失败只写诊断**,**装配即接上,关掉就解开**.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from core.event import catalog, logs
from core.event.bus import Bus
from core.event.events import Event
from core.event.logs import (
    DEFAULT_ROUTE,
    LOG_VERSION,
    LOGGER_NAME,
    ROUTES,
    EventLog,
    Route,
    Sink,
    failure_hook,
    route_of,
)
from core.init import Kernel
from core.storage.db.id import ID
from core.storage.engine import Block
from core.storage.types import Attr

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class Memo(Block):
    """用例用的最小块:一个可索引属性就够了."""

    title: str = Attr("")  # type: ignore[assignment]


class BrokenFile:
    """只用来验证"落盘失败不回流":写一行即抛,关掉不出声."""

    def write(self, _text: str) -> int:
        """写一行即失败."""
        raise OSError("盘写不进去")

    def close(self) -> None:
        """替身没有真资源要关."""


def _event(event_type: str = catalog.OBJECT_PUT, *, data: object = None) -> Event:
    """造一条典型事件:写路径发的那两条就是这个形状."""
    payload = {"table": "notedata", "content": "死beef"} if data is None else data
    return Event(
        type=event_type,
        source="core.storage",
        subject="abc",
        data=payload,
    )


def _lines(path: Path) -> list[dict[str, object]]:
    """把落盘的文件读回成一行一条."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ---- 分流表与目录 ----


def test_every_catalog_event_has_a_route():
    """**表与目录同源**:加了事件必须在这张表里登记,否则"记漏了却不报错".

    这是目录那条"发了没人收到"的镜像:两张表各写一份字面量,分叉时不报错.
    """
    assert set(ROUTES) == set(catalog.ALL)


def test_unknown_types_fall_back_to_the_default_route():
    """目录之外的类型走默认分流:漏登记退化成"照常记下",而不是静默丢弃."""
    assert route_of("future.event") is DEFAULT_ROUTE
    assert route_of(catalog.OBJECT_PUT) is not DEFAULT_ROUTE


def test_a_route_may_pick_a_subset_of_sinks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    """分流是按类型的:表里可以只给一部分去向(这一条只落盘,不回声,不推反馈)."""
    path = tmp_path / "events.jsonl"
    bus = Bus()
    log = EventLog(bus, path=path)
    pushed: list[str] = []
    log.add_feedback(lambda event: pushed.append(event.type))
    monkeypatch.setattr(
        logs,
        "ROUTES",
        {**ROUTES, catalog.OBJECT_PUT: Route(level=logging.INFO, sinks=frozenset({Sink.FILE}))},
    )

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        bus.emit(_event())
    log.close()

    assert [line["type"] for line in _lines(path)] == [catalog.OBJECT_PUT]
    assert caplog.records == []
    assert pushed == []


# ---- 诊断那一路 ----


def test_event_is_echoed_at_the_route_level(caplog: pytest.LogCaptureFixture):
    """诊断按分流表的级别写:把级别调到 INFO 就能在记录器上看到这条事件."""
    bus = Bus()
    log = EventLog(bus)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        bus.emit(_event())
    log.close()

    assert [record.levelno for record in caplog.records] == [logging.INFO]
    assert catalog.OBJECT_PUT in caplog.text


# ---- 落盘那一路 ----


def test_event_is_appended_as_one_json_line(tmp_path: Path):
    """落盘一行一条 JSON:字段是**格式版本 + 事件自己的六项**,能原样解回来."""
    path = tmp_path / "logs" / "events.jsonl"
    bus = Bus()
    log = EventLog(bus, path=path)

    bus.emit(_event())
    log.close()

    (record,) = _lines(path)
    assert record["v"] == LOG_VERSION
    assert record["type"] == catalog.OBJECT_PUT
    assert record["source"] == "core.storage"
    assert record["subject"] == "abc"
    assert record["data"] == {"table": "notedata", "content": "死beef"}
    assert record["id"]
    assert record["time"]


def test_appending_leaves_earlier_lines_alone(tmp_path: Path):
    """追加写:装配一份日志不清空已有的字节(一份文件记一条进程的流水)."""
    path = tmp_path / "events.jsonl"
    path.write_text('{"v": 1, "type": "earlier"}\n', encoding="utf-8")

    log = EventLog(Bus(), path=path)
    log.close()

    assert _lines(path)[0]["type"] == "earlier"


def test_without_a_path_nothing_is_created(tmp_path: Path):
    """**不给落点就不建文件**:只读库不会因为装了一份日志而凭空多出东西."""
    bus = Bus()
    log = EventLog(bus)

    bus.emit(_event())
    log.close()

    assert list(tmp_path.iterdir()) == []


def test_payload_outside_json_is_recorded_by_fallback(tmp_path: Path):
    """载荷编不进 JSON 时落 `repr` 兜底:记下一行不完美的记录,强过在写路径上抛错."""
    path = tmp_path / "events.jsonl"
    bus = Bus()
    log = EventLog(bus, path=path)

    bus.emit(_event(data=object()))
    log.close()

    assert isinstance(_lines(path)[0]["data"], str)


# ---- 反馈那一路 ----


def test_feedback_receives_events_and_can_be_removed():
    """反馈接一路,撤一路都显式:同一回调不重复接,撤掉之后不再收到."""
    bus = Bus()
    log = EventLog(bus)
    seen: list[Event] = []
    sink = seen.append

    log.add_feedback(sink)
    log.add_feedback(sink)
    bus.emit(_event())
    assert log.remove_feedback(sink) is True
    assert log.remove_feedback(sink) is False
    bus.emit(_event())

    assert [event.type for event in seen] == [catalog.OBJECT_PUT]


def test_one_failed_feedback_does_not_stop_the_rest(caplog: pytest.LogCaptureFixture):
    """某一路反馈抛错不中断其余,并且只写诊断(与总线的异常隔离同口径)."""
    bus = Bus()
    log = EventLog(bus)
    survived: list[str] = []

    def boom(_event: Event) -> None:
        raise RuntimeError("反馈那一侧故障")

    log.add_feedback(boom)
    log.add_feedback(lambda event: survived.append(event.type))

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        bus.emit(_event())

    assert survived == [catalog.OBJECT_PUT]
    assert "落点失败" in caplog.text


def test_file_is_written_before_feedback(tmp_path: Path):
    """去向次序定死:落盘先于反馈,故反馈读到文件时那一行已经在里面.

    不靠 `set` 的迭代序——那会跨次运行漂移(总线当初为此否掉了第三方分发库).
    """
    path = tmp_path / "events.jsonl"
    bus = Bus()
    log = EventLog(bus, path=path)
    at_feedback: list[str] = []
    log.add_feedback(lambda _event: at_feedback.append(path.read_text(encoding="utf-8")))

    bus.emit(_event())
    log.close()

    assert catalog.OBJECT_PUT in at_feedback[0]


# ---- 不回流:日志层自己的失败 ----


def test_a_broken_file_does_not_reach_the_publisher(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    """落盘失败只写诊断:发布者那边照常成功(写成功就是写成功)."""
    bus = Bus()
    log = EventLog(bus)
    # 私有替身:这里要的正是"盘坏了"这一种失败,拿真文件造不出来.
    monkeypatch.setattr(log, "_file", BrokenFile())

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        bus.emit(_event())

    assert "落点失败" in caplog.text
    log.close()


def test_failure_hook_records_subscriber_errors_without_raising(
    caplog: pytest.LogCaptureFixture,
):
    """订阅者抛错:钩子只写诊断,失败清单照旧交回调用方,不向写路径抛出."""
    bus = Bus(on_error=failure_hook(logging.getLogger(LOGGER_NAME)))

    def boom(_event: Event) -> None:
        raise RuntimeError("订阅者故障")

    bus.subscribe(catalog.OBJECT_PUT, boom)

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        failures = bus.emit(_event())

    assert len(failures) == 1
    assert "事件处理器抛错" in caplog.text


# ---- 生命周期与装配 ----


def test_close_stops_delivery_and_is_idempotent(tmp_path: Path):
    """关掉即撤订,再关不出错,且此后不再往文件里写."""
    path = tmp_path / "events.jsonl"
    bus = Bus()
    log = EventLog(bus, path=path)

    log.close()
    log.close()
    bus.emit(_event())

    assert path.read_text(encoding="utf-8") == ""


def test_kernel_subscribes_each_catalog_event_once(tmp_path: Path):
    """装配即接上:目录里每一类事件各有一份订阅(订阅只在这一处发生)."""
    with Kernel.create(tmp_path / "vault") as kernel:
        assert all(kernel.bus.receivers(event_type) == 1 for event_type in catalog.ALL)


def test_kernel_writes_the_event_log_when_a_sink_is_given(tmp_path: Path):
    """给了落点就落盘:写路径发的那两条事件各记一行,按发生次序."""
    path = tmp_path / "logs" / "events.jsonl"

    with Kernel.create(tmp_path / "vault", event_log=path):
        memo = Memo(ID(Memo))
        memo.title = "标题"
        memo.save()
        memo.delete()

    assert [line["type"] for line in _lines(path)] == [
        catalog.OBJECT_PUT,
        catalog.OBJECT_DELETED,
    ]


def test_kernel_without_a_sink_creates_no_file(tmp_path: Path):
    """不给落点就不落盘:写同一条链,库根下不得多出日志文件."""
    root = tmp_path / "vault"

    with Kernel.create(root):
        memo = Memo(ID(Memo))
        memo.title = "标题"
        memo.save()

    assert list(root.rglob("*.jsonl")) == []

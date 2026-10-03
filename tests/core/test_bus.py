# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""事件总线契约:投递顺序,异常隔离,订阅生命周期.

这里的每一条都是行为契约,不是实现细节:换成别的分发实现时,这些用例必须照样通过.
"""

from __future__ import annotations

from core.event.bus import Bus, HandlerError
from core.event.events import Event


def _recorder(sink: list[str], name: str):
    """造一个把名字记进 sink 的订阅者."""

    def handler(_event: Event) -> None:
        sink.append(name)

    return handler


def test_delivers_in_registration_order():
    """投递顺序等于注册先后.

    这条是硬契约:第三方分发库常把顺序留作"未定义",而顺序一旦不可预期,
    多个订阅者(缓存,日志,索引)之间的因果关系就无法推理,测试也会跨次运行漂移.
    """
    bus = Bus()
    order: list[str] = []
    for name in ("first", "second", "third"):
        bus.subscribe("object.put", _recorder(order, name))

    bus.emit(Event(type="object.put"))

    assert order == ["first", "second", "third"]


def test_only_matching_type_receives():
    """订阅按事件类型分流,互不串门."""
    bus = Bus()
    puts: list[str] = []
    deletes: list[str] = []
    bus.subscribe("object.put", _recorder(puts, "put"))
    bus.subscribe("object.deleted", _recorder(deletes, "delete"))

    bus.emit(Event(type="object.put"))

    assert puts == ["put"]
    assert deletes == []


def test_payload_arrives_unchanged():
    """订阅者拿到的是同一个事件对象,载荷不做转换."""
    bus = Bus()
    seen: list[Event] = []
    bus.subscribe("object.put", seen.append)
    event = Event(type="object.put", subject="abc", data={"size": 3})

    bus.emit(event)

    assert seen == [event]
    assert seen[0].data == {"size": 3}


def test_cancel_stops_delivery():
    """句柄 cancel 之后不再收到事件."""
    bus = Bus()
    order: list[str] = []
    subscription = bus.subscribe("object.put", _recorder(order, "watcher"))

    bus.emit(Event(type="object.put"))
    assert subscription.cancel() is True
    bus.emit(Event(type="object.put"))

    assert order == ["watcher"]


def test_context_manager_cancels_on_exit():
    """作上下文管理器使用时,退出即撤订(异常退出同样撤订)."""
    bus = Bus()
    order: list[str] = []
    with bus.subscribe("object.put", _recorder(order, "watcher")):
        bus.emit(Event(type="object.put"))

    bus.emit(Event(type="object.put"))

    assert order == ["watcher"]
    assert bus.receivers("object.put") == 0


def test_duplicate_subscription_counts_once():
    """同一处理器重复订阅同一类型只算一份,不造成重复投递."""
    bus = Bus()
    order: list[str] = []
    handler = _recorder(order, "watcher")

    first = bus.subscribe("object.put", handler)
    second = bus.subscribe("object.put", handler)
    bus.emit(Event(type="object.put"))

    assert first is second
    assert bus.receivers("object.put") == 1
    assert order == ["watcher"]


def test_unsubscribe_reports_whether_anything_was_dropped():
    """撤订要能分辨"撤掉了"与"本来就没订"."""
    bus = Bus()
    handler = _recorder([], "watcher")

    assert bus.unsubscribe("object.put", handler) is False
    bus.subscribe("object.put", handler)
    assert bus.unsubscribe("object.put", handler) is True
    assert bus.unsubscribe("object.put", handler) is False


def test_unsubscribe_leaves_other_subscribers_intact():
    """撤掉其中一个订阅者不得殃及同类型的其余订阅者."""
    bus = Bus()
    order: list[str] = []
    kept = _recorder(order, "kept")
    dropped = _recorder(order, "dropped")
    bus.subscribe("object.put", kept)
    bus.subscribe("object.put", dropped)

    assert bus.unsubscribe("object.put", dropped) is True
    bus.emit(Event(type="object.put"))

    assert bus.receivers("object.put") == 1
    assert order == ["kept"]


def test_handler_error_is_isolated_and_reported():
    """订阅者抛错:其余订阅者照常收到,失败清单交回调用方,且不向调用方抛出."""
    bus = Bus()
    order: list[str] = []

    def boom(_event: Event) -> None:
        raise RuntimeError("订阅者内部故障")

    bus.subscribe("object.put", _recorder(order, "before"))
    bus.subscribe("object.put", boom)
    bus.subscribe("object.put", _recorder(order, "after"))

    failures = bus.emit(Event(type="object.put"))

    assert order == ["before", "after"]
    assert len(failures) == 1
    failure = failures[0]
    assert isinstance(failure, HandlerError)
    assert failure.handler is boom
    assert isinstance(failure.error, RuntimeError)


def test_error_hook_sees_every_failure():
    """失败钩子逐个收到失败;日志引擎将接在这里."""
    seen: list[tuple[str, str]] = []
    bus = Bus(on_error=lambda event, _handler, error: seen.append((event.type, str(error))))

    def boom_a(_event: Event) -> None:
        raise ValueError("甲")

    def boom_b(_event: Event) -> None:
        raise ValueError("乙")

    bus.subscribe("object.put", boom_a)
    bus.subscribe("object.put", boom_b)
    failures = bus.emit(Event(type="object.put"))

    assert seen == [("object.put", "甲"), ("object.put", "乙")]
    assert len(failures) == 2


def test_subscription_changes_apply_from_next_delivery():
    """投递前取订阅表快照:处理过程中撤订/加订只影响下一次投递."""
    bus = Bus()
    order: list[str] = []
    latecomer = _recorder(order, "latecomer")

    def self_removing(_event: Event) -> None:
        order.append("self_removing")
        bus.unsubscribe("object.put", self_removing)
        bus.subscribe("object.put", latecomer)

    bus.subscribe("object.put", self_removing)
    bus.emit(Event(type="object.put"))
    assert order == ["self_removing"]

    bus.emit(Event(type="object.put"))
    assert order == ["self_removing", "latecomer"]


def test_emit_without_subscribers_is_noop():
    """没人订的事件:不发火,不报错,失败清单为空."""
    bus = Bus()

    assert bus.emit(Event(type="object.put")) == ()
    assert bus.receivers("object.put") == 0

# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""事件对象契约:字段,不可变性,默认值独立性."""

from __future__ import annotations

import time
from dataclasses import FrozenInstanceError

import pytest

from core.event.events import Event


def test_event_carries_type_source_subject_and_payload():
    """事件说清四件事:什么类型,谁发的,针对谁,带了什么."""
    event = Event(
        type="object.put",
        source="core.storage",
        subject="01J8ZK4Q0RSAMPLE0000000000",
        data={"size": 12},
    )

    assert event.type == "object.put"
    assert event.source == "core.storage"
    assert event.subject == "01J8ZK4Q0RSAMPLE0000000000"
    assert event.data == {"size": 12}


def test_event_ids_are_unique():
    """两个事件不得共用标识.

    这条是回归线:dataclass 的默认值若在类定义时求值,全部事件会共用同一份 id 与时间.
    """
    assert Event(type="a").id != Event(type="a").id


def test_event_time_is_unix_milliseconds():
    """时间取 unix 毫秒,且落在当前时刻附近."""
    before = time.time_ns() // 1_000_000
    event = Event(type="a")
    after = time.time_ns() // 1_000_000

    assert before <= event.time <= after


def test_event_is_immutable():
    """事件冻结:发出之后不得再被改写."""
    event = Event(type="object.put")

    with pytest.raises(FrozenInstanceError, match="cannot assign to field"):
        event.type = "object.deleted"  # type: ignore[misc]


def test_event_optional_fields_default_to_empty():
    """可选字段的默认值:空来源,空对象,无载荷."""
    event = Event(type="a")

    assert event.source == ""
    assert event.subject == ""
    assert event.data is None

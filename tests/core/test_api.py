# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""命令面契约：方法表、参数校验，以及它与内核之间那条直通。

这一层是**传输无关**的，所以测试也不需要任何 stdio——帧协议在 `app/` 那一侧。
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

import pytest

from core.api import Api
from core.exc import InvalidParamsError, ObjectNotFoundError, UnknownMethodError
from core.init import Kernel

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def _b64(text: str) -> str:
    """把一段文本编成 base64（命令面里二进制的写法）。"""
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Api]:
    """一个接了临时库的命令面。"""
    with Kernel.create(tmp_path / "vault") as kernel:
        yield Api(kernel)


# ---- 方法表 ----


def test_methods_lists_the_surface(api: Api):
    """表上有哪些方法是可问的，且顺序确定。"""
    assert {"store", "load", "drop", "query", "compact"} <= set(api.methods)
    assert api.methods == tuple(sorted(api.methods))


def test_unknown_method_is_refused(api: Api):
    """不认识的方法名当场报错，顺带把有的报出来。"""
    with pytest.raises(UnknownMethodError, match="没有这个方法"):
        api.call("没有这个方法")


# ---- 与内核直通 ----


def test_store_then_load_roundtrips(api: Api):
    """存进去、取回来：正文经 base64 过一遍，字节不变。"""
    stored = api.call("store", {"data": _b64("正文"), "kind": "notedata"})

    assert isinstance(stored, dict)
    assert api.call("load", {"uuid": stored["uuid"]}) == {"data": _b64("正文")}


def test_stored_attributes_come_back_through_payload(api: Api):
    """属性跟着块走：存的时候给，`payload` 取回来。"""
    stored = api.call("store", {"data": _b64("body"), "attrs": {"title": "T"}})

    assert isinstance(stored, dict)
    payload = api.call("payload", {"uuid": stored["uuid"]})

    assert isinstance(payload, dict)
    assert payload["attrs"] == {"title": "T"}


def test_blocks_lists_what_is_stored(api: Api):
    """列举就是查表：存了两条就列得出两条。"""
    api.call("store", {"data": _b64("one")})
    api.call("store", {"data": _b64("two")})

    listed = api.call("blocks")

    assert isinstance(listed, dict)
    assert len(listed["blocks"]) == 2


def test_drop_reports_whether_it_hit(api: Api):
    """删除报真假：第二次删同一个就是假。"""
    stored = api.call("store", {"data": _b64("x")})

    assert isinstance(stored, dict)
    assert api.call("drop", {"uuid": stored["uuid"]}) == {"dropped": True}
    assert api.call("drop", {"uuid": stored["uuid"]}) == {"dropped": False}


def test_query_only_covers_declared_attributes(api: Api):
    """速查表只收类型声明过的属性：没声明就没有命中，也不报错。"""
    api.call("store", {"data": _b64("body"), "kind": "notedata", "attrs": {"title": "T"}})

    found = api.call("query", {"kind": "notedata", "attribute": "title", "value": "T"})

    assert isinstance(found, dict)
    assert found["uuids"] == [], "没有声明要查的属性，谁都不该命中"


def test_survey_and_compact_are_on_the_surface(api: Api):
    """整库动作也在表上：勘察给数字，整理真回收。"""
    stored = api.call("store", {"data": _b64("gone")})

    assert isinstance(stored, dict)
    api.call("drop", {"uuid": stored["uuid"]})

    plan = api.call("survey")
    assert isinstance(plan, dict)
    assert plan["worth_it"] is True

    report = api.call("compact")
    assert isinstance(report, dict)
    assert report["dropped"] >= 1
    assert report["cancelled"] is False


# ---- 参数校验：缺了、类型不对、解不出来 ----


def test_missing_parameter_is_refused(api: Api):
    with pytest.raises(InvalidParamsError, match="data"):
        api.call("store", {})


def test_wrong_type_is_refused(api: Api):
    with pytest.raises(InvalidParamsError, match="uuid"):
        api.call("load", {"uuid": 7})


def test_bad_base64_is_refused(api: Api):
    with pytest.raises(InvalidParamsError, match="base64"):
        api.call("store", {"data": "这不是 base64"})


def test_query_needs_a_value(api: Api):
    """空值也是值：不给 `value` 与给一个空值不是一回事。"""
    with pytest.raises(InvalidParamsError, match="value"):
        api.call("query", {"kind": "k", "attribute": "a"})


def test_kernel_errors_pass_through(api: Api):
    """内核自己抛的异常原样交给调用方：命令面不吞它、也不改名。"""
    with pytest.raises(ObjectNotFoundError):
        api.call("load", {"uuid": "没有这个块"})

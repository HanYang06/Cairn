# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""笔记域服务接内核：域服务受内核管辖，动作经引擎派发。

旧文件测的是已删除的"门户 / 地址树 / Topic 多播"，这里按新结构重写：

- 域服务继承 `Managed` → **继承即登记**（父类在 `__init_subclass__` 里替它收成）；
- 调用经内核 `send(Intent, Action...)`，或用 `core.call(target, method, **args)` 一行；
- 事件是**广播**（不带角色 = 谁关心谁听）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core import Core, ObjectNotFoundError
from core.core import Managed
from core.types import ValueUuid
from core.types.event import Action, Intent
from feature import Note

if TYPE_CHECKING:
    from pathlib import Path


def test_service_is_managed_by_kernel() -> None:
    """域服务继承内核的管辖基类 → 类型收成里有它。"""
    assert Core.type_of("note") is Note


def test_domain_type_is_a_managed_subclass() -> None:
    info = Core.type_of("note")
    assert info is not None
    assert isinstance(info, type)
    assert issubclass(info, Managed)


def test_action_dispatches_through_engine(core: Core) -> None:
    notes = core.role("note")
    assert isinstance(notes, Note)

    outcome = core.send(
        Intent.PUT,
        Action(
            role_obj=notes,
            call_function="create",
            call_args={"text": "hello", "title": "T"},
        ),
    )

    assert outcome.ok
    created = outcome.steps[0].result
    assert created.text == "hello"
    assert notes.list_notes()[0].title == "T"


def test_short_api_call_is_one_line(core: Core) -> None:
    """改一个对象上的东西：短 API 一行（领域方法以 data 为首参，故显式传）。"""
    notes = core.role("note")
    assert isinstance(notes, Note)
    note = notes.create("原文")
    core.call(notes, "set_text", data=note, text="改过")
    notes.save(note)
    assert notes.load(note.oid).text == "改过"


def test_unknown_role_fails_loud(core: Core) -> None:
    outcome = core.send(Intent.PUT, Action(role_name="不存在的服务", call_function="create"))
    assert not outcome.ok
    assert isinstance(outcome.failed[0].error, ObjectNotFoundError)


def test_action_error_propagates_to_outcome(core: Core) -> None:
    notes = Note(core)
    outcome = core.send(
        Intent.GET,
        Action(role_obj=notes, call_function="load", call_args={"oid": str(ValueUuid.new())}),
    )
    assert not outcome.ok
    assert isinstance(outcome.failed[0].error, ObjectNotFoundError)


def test_kernel_is_a_singleton(core: Core) -> None:
    """内核是**单例**：再构造拿到的还是它（存储是挂件，可换）。"""
    assert Core() is core


def test_two_databases_by_switching_storage(core: Core, tmp_path: Path) -> None:
    """换库 = 换存储挂件；内核本身仍是同一个。"""
    import core.storage as storage_mod  # noqa: PLC0415

    other = storage_mod.Storage.open(tmp_path / "other")
    core.mount("storage", other)
    notes = Note(core)
    notes.create("在另一个库里")
    assert len(notes.list_notes()) == 1
    other.close()  # 换下来的那份也要关：不关就是泄漏一个 sqlite 连接


def test_role_lookup_returns_the_service(core: Core) -> None:
    """按名字取服务：conftest 装配时建的 `Note(core)` 就是它。"""
    role = Core.type_of("note")
    assert role is Note
    assert isinstance(core.role("note"), Note)

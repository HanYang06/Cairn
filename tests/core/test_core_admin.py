# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""内核的库级能力：巡检 / 未实现项如实报错 / 查询应急口。

（原 `test_index_search.py` 测的检索投影随 `Vault` 解散一起移除——
检索要重做，届时另开测试，不在这里留半截。）
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core import Core  # noqa: TC001 — 运行期用作 fixture 注解
from core.storage import Block

if TYPE_CHECKING:
    from pathlib import Path


def test_verify_reports_healthy(core: Core) -> None:
    core.put(Block(body=b"data " * 10_000))

    report = core.verify()

    assert report.ok
    assert report.objects == 1


def test_unimplemented_maintenance_fails_loudly(core: Core) -> None:
    """没实现的能力**如实报错**，不静默返回 0 骗调用方。"""
    with pytest.raises(NotImplementedError):
        core.gc()
    with pytest.raises(NotImplementedError):
        core.verify(deep=True)


def test_query_and_execute_go_through_storage(core: Core) -> None:
    core.put(Block(body=b"x", type="blob"))

    rows = core.query("SELECT value_uuid FROM record WHERE kind = ?", ("blob",))
    assert len(rows) == 1  # 内容记录的类型为空，故按类型筛只剩块记录

    changed = core.execute("UPDATE record SET updated = 0 WHERE kind = ?", ("blob",))
    assert changed == 1


def test_close_then_reopen_keeps_objects(core: Core, tmp_path: Path) -> None:
    block = core.put(Block(body=b"kept"))
    core.close()

    reopened = core.open(tmp_path / "vault")
    assert reopened.read(block.id) == b"kept"

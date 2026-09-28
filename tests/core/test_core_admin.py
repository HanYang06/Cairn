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
from core.storage import Block, Storage

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


def test_mount_keeps_the_kernel_usable_when_the_old_widget_cannot_close(
    core: Core, tmp_path: Path
) -> None:
    """换挂件时旧件关不掉：只记告警、照旧换新。

    若先摘净再关，`close()` 一抛就留下"这个名字没有任何挂件"的半损坏态——
    内核还在、``storage`` 却查不到了。漏一个连接比让内核失能轻。
    """

    class Stubborn:
        """关不掉的假挂件。"""

        name = "storage"
        id = "storage"

        def close(self) -> None:
            raise OSError("文件系统不给关")

    core.mount("storage", Stubborn())
    replaced = core.mount("storage", Storage.open(tmp_path / "vault"))

    assert core.storage is replaced  # 换新照旧完成


def test_close_then_reopen_keeps_objects(core: Core, tmp_path: Path) -> None:
    block = core.put(Block(body=b"kept"))
    core.close()

    reopened = core.open(tmp_path / "vault")
    assert reopened.read(block.id) == b"kept"

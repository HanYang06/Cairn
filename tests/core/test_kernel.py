# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""内核契约：库的开关（open 不建、create 才建）、两个引擎的装配、维护入口、日志联动。"""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING

import pytest

from core.event.catalog import OBJECT_PUT
from core.exc import IndexNotFoundError
from core.init import CATALOG_FILENAME, LOGGER_NAME, Kernel
from core.storage.carrier import Carrier
from core.storage.format.id import ID
from core.storage.format.record import encode
from core.storage.hub import Hub, PackPolicy
from core.storage.patrol import FindKind
from core.storage.tables import Declaration, TableSpec, kernel_tables

if TYPE_CHECKING:
    from pathlib import Path

    from core.event.events import Event

_SLOT = 512
_HUGE = 1 << 40


# ---- 库的开关 ----


def test_create_builds_a_vault(tmp_path: Path):
    """建库：库根、索引库与内核表一次到位。"""
    with Kernel.create(tmp_path / "vault") as kernel:
        assert kernel.catalog_path.exists()
        assert kernel.catalog_path.name == CATALOG_FILENAME
        assert kernel.index.tables() == ("block", "body", "edge", "hub", "meta")
        assert kernel.policy == PackPolicy()


def test_open_refuses_a_missing_vault_without_creating_it(tmp_path: Path):
    """**读路径不建东西**：库不在就报错，且不留空目录。"""
    missing = tmp_path / "nope"

    with pytest.raises(IndexNotFoundError):
        Kernel.open(missing)

    assert not missing.exists()


def test_context_manager_closes_the_database(tmp_path: Path):
    """退出 with 即关库。"""
    with Kernel.create(tmp_path / "vault") as kernel:
        pass

    with pytest.raises(sqlite3.ProgrammingError):
        kernel.index.tables()


# ---- 两个引擎的装配 ----


def test_store_and_load_through_the_kernel(tmp_path: Path):
    """内核短面：存进去拿到身份，按身份读回来。"""
    with Kernel.create(tmp_path / "vault") as kernel:
        block = kernel.store(b"through the kernel", kind="notedata")

        assert isinstance(block, ID)
        assert kernel.load(block.value_uuid) == b"through the kernel"
        row = kernel.locate(block.value_uuid)
        assert row is not None
        assert row.hub == "main"
        assert row.kind == "notedata"
        assert kernel.patrol().clean


def test_named_hub_is_created_and_registered(tmp_path: Path):
    """写进别的 hub：目录、登记、行三样一起到位。"""
    with Kernel.create(tmp_path / "vault") as kernel:
        block = kernel.store(b"side", hub="side")

        assert (kernel.root / "side" / "packs").is_dir()
        assert kernel.index.rows.hub("side") is not None
        row = kernel.locate(block.value_uuid)
        assert row is not None
        assert row.hub == "side"
        assert kernel.patrol().clean


def test_events_flow_through_the_kernel_bus(tmp_path: Path):
    """落盘后的事件由内核自己的总线发出。"""
    seen: list[str] = []

    def handler(event: Event) -> None:
        seen.append(event.subject)

    with Kernel.create(tmp_path / "vault") as kernel:
        kernel.bus.subscribe(OBJECT_PUT, handler)

        block = kernel.store(b"notify me")

    assert seen == [block.value_uuid]


def test_custom_policy_decides_the_slot_length(tmp_path: Path):
    """内核把载体策略传给存储引擎：新载体的槽长按它来。"""
    policy = PackPolicy(slot_bytes=256, max_bytes=_HUGE)

    with Kernel.create(tmp_path / "vault", policy=policy) as kernel:
        kernel.store(b"narrow slots")
        hub = Hub(kernel.root / "main", slot_bytes=_SLOT)
        carrier = Carrier(hub.packs_dir / hub.pack_names()[0])

        assert carrier.slot_bytes == 256
        carrier.close()


def test_custom_declaration_is_forwarded(tmp_path: Path):
    """声明集可以换：多一张领域表也照样开库。"""
    note = TableSpec.from_mapping(
        {
            "name": "note",
            "tier": "source",
            "owner": "note",
            "columns": [{"name": "id", "from": "prog", "type": "text"}],
            "primary_key": ["id"],
        }
    )
    declaration = Declaration((*kernel_tables(), note))

    with Kernel.create(tmp_path / "vault", declaration=declaration) as kernel:
        assert "note" in kernel.index.tables()


def test_drop_and_storage_face(tmp_path: Path):
    """摘块走内核短面；`storage` 给的是同一个引擎。

    这里同时钉住一条**当前口径**：摘块只摘行，记录仍留在载体里（追加写不动旧字节），
    故巡检会报"盘上有记录、库里没有行"。这一条要等压实回收落地才会消失（未来项）；
    在那之前，处置会把这一行补回来——等于撤销这次摘块。见 `progress.md` 的未来项与
    `references/decisions/` 的挂账。
    """
    with Kernel.create(tmp_path / "vault") as kernel:
        block = kernel.store(b"droppable")

        assert kernel.storage.load(block.value_uuid) == b"droppable"
        assert kernel.drop(block.value_uuid) is True
        assert kernel.drop(block.value_uuid) is False
        assert kernel.locate(block.value_uuid) is None
        assert {item.kind for item in kernel.patrol().finds} == {FindKind.MISSING_ROW}


# ---- 日志联动 ----


def test_handler_failure_is_logged_and_does_not_break_the_write(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    """处理器抛错只进日志：写入不受影响（通知层不该影响写路径）。"""

    def boom(_event: object) -> None:
        raise RuntimeError("处理器炸了")

    with Kernel.create(tmp_path / "vault") as kernel:
        kernel.bus.subscribe(OBJECT_PUT, boom)

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            block = kernel.store(b"write survives")

        assert kernel.load(block.value_uuid) == b"write survives"

    assert any("已隔离" in record.getMessage() for record in caplog.records)


def test_custom_logger_is_used(tmp_path: Path):
    """日志器可以换：内核不写死自己的那一个。"""
    logger = logging.getLogger("cairn.test.kernel")

    with Kernel.create(tmp_path / "vault", logger=logger) as kernel:
        assert kernel.logger is logger


# ---- 维护入口 ----


def test_patrol_and_repair_through_the_kernel(tmp_path: Path):
    """巡检与处置从内核进：它们是整库动作，不是某一次写入。"""
    with Kernel.create(tmp_path / "vault") as kernel:
        hub = Hub.create(kernel.root / "adopted", slot_bytes=_SLOT)
        hub.append(encode(ID.of(b"orphan"), b"orphan"))

        report = kernel.patrol()

        assert {item.kind for item in report.finds} == {
            FindKind.MISSING_ROW,
            FindKind.UNREGISTERED_HUB,
        }
        result = kernel.repair(report)

        assert len(result.applied) == 2
        assert kernel.patrol().clean

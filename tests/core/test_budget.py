# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""配额与体积上限契约：写路径按类型声明选 hub、按配额处置、按上限拦下。

这一组要真建库——三件事都发生在 `Storage.store` 里，不是纯函数能验的。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from core.event.catalog import BUDGET_EXHAUSTED
from core.exc import BlockTooLargeError, BudgetExhaustedError
from core.init import Kernel
from core.storage.carrier import owner_digest
from core.storage.format.block import Block, Body, register_type
from core.storage.hub import Hub, PackPolicy
from core.storage.registry import REGISTRY, OverBudget

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_KIB = 1024

_POLICY = PackPolicy(slot_bytes=512, max_bytes=600)
"""一条像样的记录就能让它封口：于是"要新开一份"在一条记录之内就发生。"""

_BIG = b"x" * 700
"""装进两格（约 1024 字节）的载荷：写完这一条，载体即达封口线。"""


@pytest.fixture(autouse=True)
def clean_registry() -> Iterator[None]:
    """每个用例一份干净的登记，**用完还原**（与 `test_attr.py` 同一套）。"""
    REGISTRY.clear()
    register_type(Body)
    register_type(Block)
    yield
    REGISTRY.clear()
    register_type(Body)
    register_type(Block)


# ---- hub 归属 ----


def test_own_hub_name_comes_from_the_table(tmp_path: Path):
    """独占 hub：名字取表名，不必手填。"""

    @dataclass(slots=True)
    class Indexed(Block[None]):
        """独占一个 hub 的测试类型。"""

        __table__ = "indexed"
        __own_hub__ = True

    with Kernel.create(tmp_path) as kernel:
        kernel.store(b"body", kind="indexed")

        assert (kernel.root / "indexed" / "packs").is_dir()


def test_named_hub_is_created_on_demand(tmp_path: Path):
    """指定 hub：不存在就建，写进去；不该另开一个同名的。"""

    @dataclass(slots=True)
    class Named(Block[None]):
        """指定写进 idx 的测试类型。"""

        __table__ = "named"
        __hub__ = "idx"

    with Kernel.create(tmp_path) as kernel:
        kernel.store(b"body", kind="named")

        assert (kernel.root / "idx" / "packs").is_dir()
        assert not (kernel.root / "named").exists()


def test_undeclared_kind_still_lands_in_the_default_hub(tmp_path: Path):
    """没有声明的 kind 照旧进默认 hub——既有行为不变。"""
    with Kernel.create(tmp_path) as kernel:
        kernel.store(b"body")

        assert (kernel.root / "main" / "packs").is_dir()


def test_new_pack_is_marked_with_its_owner(tmp_path: Path):
    """新开的载体在文件头里标注归属：那是它自己的事实，不靠索引库记得。"""

    @dataclass(slots=True)
    class Named(Block[None]):
        """指定 hub 的测试类型。"""

        __table__ = "named"
        __hub__ = "idx"

    with Kernel.create(tmp_path) as kernel:
        kernel.store(b"body", kind="named")

        hub = Hub(kernel.root / "idx")
        names = hub.pack_names()
        assert names
        for name in names:
            with hub.carrier(name) as carrier:
                assert carrier.owner == owner_digest("named")


# ---- 配额：三档 ----


def test_deny_refuses_when_a_new_pack_would_be_needed(tmp_path: Path):
    """配额一份 + 档位为拒绝：第一份封口后再要写就抛。"""

    @dataclass(slots=True)
    class Tight(Block[None]):
        """配额一份、满了就拒绝的测试类型。"""

        __table__ = "tight"
        __pack_budget__ = 1
        __over_budget__ = OverBudget.DENY

    with Kernel.create(tmp_path, policy=_POLICY) as kernel, pytest.raises(BudgetExhaustedError):
        kernel.store(_BIG, kind="tight")


def test_extend_opens_the_next_pack_silently(tmp_path: Path):
    """默认档位续一份：配额满了照样写下去，第二份载体由此诞生。"""

    @dataclass(slots=True)
    class Loose(Block[None]):
        """配额一份、满了就续的测试类型。"""

        __table__ = "loose"
        __pack_budget__ = 1

    with Kernel.create(tmp_path, policy=_POLICY) as kernel:
        kernel.store(_BIG, kind="loose")

        assert len(Hub(kernel.root / "main").pack_names()) == 2


def test_notify_opens_the_next_pack_and_tells(tmp_path: Path):
    """提示档位：续一份，并发一条通知——内核只说"满了"，怎么办不归它管。"""

    @dataclass(slots=True)
    class Noisy(Block[None]):
        """配额一份、满了就通知的测试类型。"""

        __table__ = "noisy"
        __pack_budget__ = 1
        __over_budget__ = OverBudget.NOTIFY

    seen: list[str] = []
    with Kernel.create(tmp_path, policy=_POLICY) as kernel:
        kernel.bus.subscribe(BUDGET_EXHAUSTED, lambda event: seen.append(event.subject))

        kernel.store(_BIG, kind="noisy")

    assert seen == ["noisy"]


def test_no_budget_means_the_old_write_discipline(tmp_path: Path):
    """没写配额就没有配额：照旧写满就换下一份，不抛也不通知。"""

    @dataclass(slots=True)
    class Free(Block[None]):
        """没有配额的测试类型。"""

        __table__ = "free"

    seen: list[str] = []
    with Kernel.create(tmp_path, policy=_POLICY) as kernel:
        kernel.bus.subscribe(BUDGET_EXHAUSTED, lambda event: seen.append(event.subject))

        kernel.store(_BIG, kind="free")

        assert len(Hub(kernel.root / "main").pack_names()) == 2
    assert seen == []


# ---- 体积上限 ----


def test_oversized_payload_is_rejected(tmp_path: Path):
    """超过类型声明的单块上限即拒写（分片尚未接线，此刻的处置只能是拒绝）。"""

    @dataclass(slots=True)
    class Small(Block[None]):
        """上限 1 KiB 的测试类型。"""

        __table__ = "small"
        __max_block_kbyte__ = 1

    with Kernel.create(tmp_path) as kernel, pytest.raises(BlockTooLargeError):
        kernel.store(b"x" * (_KIB + 1), kind="small")


def test_payload_exactly_at_the_limit_is_accepted(tmp_path: Path):
    """卡在上限上的载荷是合法的：判据是"超过"，不是"达到"。"""

    @dataclass(slots=True)
    class Small(Block[None]):
        """上限 1 KiB 的测试类型。"""

        __table__ = "small"
        __max_block_kbyte__ = 1

    with Kernel.create(tmp_path) as kernel:
        kid = kernel.store(b"x" * _KIB, kind="small")

        assert kernel.load(kid.value_uuid) == b"x" * _KIB

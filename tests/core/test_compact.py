# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""整理契约：勘察只读、处理真抹、可重复跑，且删块留下的孤儿正文也一起回收。

要真建库——整理动的是载体文件本身，纯函数验不了。

带归属的那个测试类型按新范式写在 `__init__` 里声明字段；`__table__` / `__hub__`
仍写在类体——它们描述的是**存储行为**，不是形状。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core.init import Kernel
from core.storage.carrier import owner_digest
from core.storage.format.block import Block, install_core_types, tombstone_of
from core.storage.format.id import ID
from core.storage.format.record import decode
from core.storage.hub import Hub, find_hubs
from core.storage.registry import REGISTRY

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def clean_registry() -> Iterator[None]:
    """每个用例一份干净的登记，**用完还原**（与 `test_attr.py` 同一套）。

    内核那两张表按 `install_core_types()` 重放——它们不由用户类型的构造声明而来。
    """
    REGISTRY.clear()
    install_core_types()
    yield
    REGISTRY.clear()
    install_core_types()


def _tombs(kernel: Kernel) -> int:
    """数一数盘上还剩几块墓碑。"""
    count = 0
    for hub in find_hubs(kernel.root):
        for name in hub.pack_names():
            with hub.carrier(name) as carrier:
                for _span, raw in carrier.scan():
                    if tombstone_of(decode(raw).payload) is not None:
                        count += 1
    return count


# ---- 勘察：只读 ----


def test_survey_plans_without_touching_anything(tmp_path: Path):
    """勘察只读：给出计划与数字，一个字节都不改。"""
    vault = tmp_path / "vault"
    with Kernel.create(vault) as kernel:
        keep = kernel.store(b"keep-body")
        gone = kernel.store(b"gone-body")
        kernel.drop(gone.value_uuid)
        before = sorted(pack.name for pack in (vault / "main" / "packs").iterdir())

        report = kernel.survey()

        assert report.worth_it
        assert report.dead_records >= 1
        assert report.live_records >= 1
        assert report.bytes_to_read > 0
        assert report.bytes_to_write > 0
        assert report.waste_ratio > 0
        assert report.expected_ratio < report.waste_ratio, "整理之后该更紧凑"
        assert sorted(pack.name for pack in (vault / "main" / "packs").iterdir()) == before
        assert kernel.load(keep.value_uuid) == b"keep-body"


def test_survey_says_nothing_to_do_on_a_fresh_vault(tmp_path: Path):
    """刚写完的库没什么可回收的：计划为空，不值得跑一趟。"""
    with Kernel.create(tmp_path / "vault") as kernel:
        kernel.store(b"one")

        report = kernel.survey()

        assert report.worth_it is False
        assert report.waste_ratio == pytest.approx(0.0)


# ---- 处理：真抹 ----


def test_compact_reclaims_the_bytes_of_a_deleted_block(tmp_path: Path):
    """删一个块再整理：字节真回收了，活着的照样读得出来。"""
    with Kernel.create(tmp_path / "vault") as kernel:
        keep = kernel.store(b"keep-me")
        gone = kernel.store(b"gone-me")
        assert kernel.drop(gone.value_uuid) is True

        report = kernel.compact()

        assert report.dropped >= 1
        assert report.reclaimed > 0
        assert kernel.load(keep.value_uuid) == b"keep-me"
        assert kernel.locate(gone.value_uuid) is None


def test_compact_reclaims_the_orphan_body(tmp_path: Path):
    """删块之后正文没人用了：整理把它一起回收，活的那一份照旧，行与记录两边仍对得上。"""
    with Kernel.create(tmp_path / "vault") as kernel:
        keep = kernel.store(b"keep-body")
        gone = kernel.store(b"gone-body")
        kernel.drop(gone.value_uuid)

        before = kernel.survey()
        kernel.compact()

        assert before.dead_records >= 3, "被删的块、它的正文、墓碑都该落选"
        assert kernel.load(keep.value_uuid) == b"keep-body", "活着的正文还在"
        assert kernel.survey().dead_records == 0, "整理完就没有垃圾了"
        assert kernel.patrol().clean, "行与记录两边都对得上"


def test_compact_removes_a_pack_that_is_all_garbage(tmp_path: Path):
    """整份全是垃圾：直接删掉文件，不重写、不留空壳。"""
    with Kernel.create(tmp_path / "vault") as kernel:
        gone = kernel.store(b"gone")
        kernel.drop(gone.value_uuid)

        kernel.compact()

        assert Hub(kernel.root / "main").pack_names() == ()
        assert kernel.patrol().clean


def test_compact_removes_the_tombstones(tmp_path: Path):
    """整理之后墓碑本身也没了：它只为删除做证，整理完使命就结束。"""
    with Kernel.create(tmp_path / "vault") as kernel:
        gone = kernel.store(b"gone")
        kernel.drop(gone.value_uuid)
        assert _tombs(kernel) == 1

        kernel.compact()

        assert _tombs(kernel) == 0


def test_compact_is_idempotent(tmp_path: Path):
    """整理可以重复跑：第二趟没有可回收的，一条记录都不动。"""
    with Kernel.create(tmp_path / "vault") as kernel:
        kernel.store(b"one")
        gone = kernel.store(b"two")
        kernel.drop(gone.value_uuid)

        first = kernel.compact()
        second = kernel.compact()

        assert first.dropped >= 1
        assert second.dropped == 0, "第一趟之后就没有垃圾了"
        assert second.kept == 0, "第二趟一份载体都不该动"


def test_compact_keeps_the_owner_of_a_pack(tmp_path: Path):
    """整理不把载体的归属弄丢：它记的是"这份归哪个类型"，丢了配额判定就会算错。"""

    class Owned(Block):
        """指定 hub 的测试类型。"""

        __table__ = "owned"
        __hub__ = "idx"

        def __init__(self) -> None:
            super().__init__()
            self.id = ID()

    with Kernel.create(tmp_path / "vault") as kernel:
        kernel.store(b"x" * 300, kind="owned")
        gone = kernel.store(b"y" * 300, kind="owned")
        kernel.drop(gone.value_uuid)

        kernel.compact()

        hub = Hub(kernel.root / "idx")
        names = hub.pack_names()
        assert names, "还有活着的记录，载体该在"
        for name in names:
            with hub.carrier(name) as carrier:
                assert carrier.owner == owner_digest("owned")


# ---- 计划、进度、取消 ----


def test_compact_takes_the_plan(tmp_path: Path):
    """按勘察给的计划动手，结果与现勘察一致。"""
    with Kernel.create(tmp_path / "vault") as kernel:
        keep = kernel.store(b"keep")
        gone = kernel.store(b"gone")
        kernel.drop(gone.value_uuid)

        plan = kernel.survey()
        report = kernel.compact(plan=plan)

        assert report.dropped >= 1
        assert kernel.load(keep.value_uuid) == b"keep"
        assert kernel.survey().dead_records == 0


def test_compact_reports_progress(tmp_path: Path):
    """进度按载体报：最后一条一定是（总数，总数）。"""
    with Kernel.create(tmp_path / "vault") as kernel:
        gone = kernel.store(b"gone")
        kernel.drop(gone.value_uuid)
        seen: list[tuple[int, int]] = []

        kernel.compact(on_progress=lambda done, total: seen.append((done, total)))

        assert seen, "该报过进度"
        assert seen[-1][0] == seen[-1][1]


def test_compact_can_be_stopped(tmp_path: Path):
    """能取消：取消之后数据完好，只是这次没做完。"""
    with Kernel.create(tmp_path / "vault") as kernel:
        keep = kernel.store(b"keep")
        gone = kernel.store(b"gone")
        kernel.drop(gone.value_uuid)

        report = kernel.compact(should_stop=lambda: True)

        assert report.cancelled is True
        assert report.packs_before == 0, "第一份载体之前就停了"
        assert kernel.load(keep.value_uuid) == b"keep"

# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""巡检契约：两个方向都比、两项都对才算一致、坏点不即停、处置只补不删。"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from core.storage.carrier import HEADER_BYTES as CARRIER_HEADER_BYTES
from core.storage.carrier import Carrier
from core.storage.engine import Storage
from core.storage.format.id import ID
from core.storage.format.record import decode, encode
from core.storage.hub import Hub, find_hubs
from core.storage.index import Index
from core.storage.patrol import FindKind, patrol, repair
from core.storage.tables import Declaration, kernel_tables

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_SLOT = 512


@pytest.fixture
def vault(tmp_path: Path) -> Iterator[Storage]:
    """一个能落盘的引擎（库根 ＋ 已对齐的索引库）。"""
    root = tmp_path / "vault"
    root.mkdir()
    with Index.open(root / "catalog.db", Declaration(kernel_tables()), create=True) as index:
        yield Storage(index, root)


def _hub(engine: Storage, name: str = "main") -> Hub:
    """打开库里已有的 hub。"""
    return Hub(engine.root / name, slot_bytes=_SLOT)


def _raw_at(engine: Storage, value_uuid: str) -> bytes:
    """把一个身份当前指向的记录原始字节读回来。"""
    row = engine.locate(value_uuid)
    assert row is not None
    with _hub(engine).carrier(row.in_hub_pack) as carrier:
        return carrier.read(row.span)


# ---- 一致 ----


def test_clean_vault_has_nothing_to_report(vault: Storage):
    """库里有什么、盘上就有什么：巡检干净，两个方向都没话说。"""
    vault.store(b"clean", kind="notedata")

    report = patrol(vault.index, vault.root)

    assert report.clean
    assert report.hubs_scanned == 1
    assert report.records_scanned == 2


def test_store_registers_the_hub_it_creates(vault: Storage):
    """写路径建 hub 就登记：否则巡检每次都要报一处"登记缺"，那是引擎自己欠的账。"""
    vault.store(b"first", hub="side")

    registration = vault.index.rows.hub("side")
    assert registration is not None
    assert patrol(vault.index, vault.root).clean


def test_duplicate_occurrence_is_not_a_difference(vault: Storage):
    """同一身份在盘上出现多次不算差异：行指向的那一份存在即可（旧副本等压实回收）。"""
    block = vault.store(b"twin", kind="notedata")
    raw = _raw_at(vault, block.value_uuid)
    with Carrier(_hub(vault).packs_dir / "copy", slot_bytes=_SLOT) as copy:
        copy.append(raw)

    assert patrol(vault.index, vault.root).clean


# ---- 可修复的一列 ----


def test_unregistered_hub_and_missing_row_are_repaired(vault: Storage):
    """盘上有、库里没有：补登记 ＋ 补行，处置之后巡检干净。"""
    hub = Hub.create(vault.root / "side", slot_bytes=_SLOT)
    hub.append(encode(ID.of(b"orphan"), b"orphan"))

    before = patrol(vault.index, vault.root)
    assert [item.kind for item in before.finds] == [
        FindKind.MISSING_ROW,
        FindKind.UNREGISTERED_HUB,
    ]
    assert len(before.repairable) == 2

    result = repair(vault.index, before)

    assert result.applied == before.finds
    assert result.skipped == ()
    assert patrol(vault.index, vault.root).clean
    registration = vault.index.rows.hub("side")
    assert registration is not None
    assert registration.name == "side"


def test_misplaced_is_repaired_by_moving_coordinates(vault: Storage):
    """坐标不符：处置**只改坐标**，类型标号与身份字段一个都不许动。"""
    block = vault.store(b"moved", kind="notedata")
    row = vault.locate(block.value_uuid)
    assert row is not None
    vault.index.rows.move_block(replace(row, in_pack_slot=(9999, 9999)))

    report = patrol(vault.index, vault.root)
    assert [item.kind for item in report.finds] == [FindKind.MISPLACED]

    repair(vault.index, report)

    restored = vault.locate(block.value_uuid)
    assert restored is not None
    assert restored.span == row.span
    assert restored.kind == "notedata"
    assert (restored.name, restored.birth_time) == (row.name, row.birth_time)
    assert patrol(vault.index, vault.root).clean


def test_misplaced_body_row_is_repaired_too(vault: Storage):
    """内容行的坐标不符同样只改坐标：两张表各有一条可修复路。"""
    vault.store(b"body move", kind="notedata")
    body = vault.index.rows.bodies_by_hash(ID.of(b"body move").value_hash)[0]
    vault.index.rows.move_body(replace(body, in_pack_slot=(9999, 9999)))

    report = patrol(vault.index, vault.root)
    assert {item.kind for item in report.finds} == {FindKind.MISPLACED}

    repair(vault.index, report)

    restored = vault.index.rows.body(body.value_uuid)
    assert restored is not None
    assert restored.span == body.span
    assert patrol(vault.index, vault.root).clean


# ---- 只能报告的一列 ----


def test_missing_record_is_reported_and_never_touched(vault: Storage):
    """行在、盘上读不出来：报出来，处置一行都不动（删行等于把"丢了"抹掉）。"""
    block = vault.store(b"gone", kind="notedata")
    hub = _hub(vault)
    for name in hub.pack_names():
        (hub.packs_dir / name).unlink()

    report = patrol(vault.index, vault.root)

    assert {item.kind for item in report.finds} == {FindKind.MISSING_RECORD}
    assert report.repairable == ()
    assert len(report.broken) == 2, "块行与内容行各报一处"

    result = repair(vault.index, report)

    assert result.applied == ()
    assert result.skipped == report.finds
    assert vault.locate(block.value_uuid) is not None
    assert vault.index.rows.count_locations() == 2


def test_missing_hub_is_reported_and_not_repaired(vault: Storage):
    """登记在、目录缺：hub 没了，只能报告。"""
    vault.index.rows.register_hub("ghost")

    report = patrol(vault.index, vault.root)

    assert [item.kind for item in report.finds] == [FindKind.MISSING_HUB]
    assert repair(vault.index, report).applied == ()
    assert vault.index.rows.hub("ghost") is not None


def test_corrupt_carrier_does_not_stop_the_scan(vault: Storage):
    """坏点不即停：坏的载体报出来，其余载体照扫——好载体里的身份不能被误报成"内容没了"。"""
    block = vault.store(b"healthy", kind="notedata")
    hub = _hub(vault)
    damaged = hub.packs_dir / "zzz"
    with Carrier(damaged, slot_bytes=_SLOT) as carrier:
        carrier.append(encode(ID.of(b"lost"), b"lost"))
    damaged.write_bytes(damaged.read_bytes()[: CARRIER_HEADER_BYTES + 32])

    report = patrol(vault.index, vault.root)

    assert [item.kind for item in report.finds] == [FindKind.CORRUPT_CARRIER]
    assert report.finds[0].subject == "zzz"
    assert report.records_scanned == 2
    assert vault.locate(block.value_uuid) is not None
    assert repair(vault.index, report).applied == ()


def test_registration_rows_and_carriers_agree_after_repair(vault: Storage):
    """处置之后三样东西（登记、行、载体）重新对得上：巡检再跑一遍是干净的。"""
    hub = Hub.create(vault.root / "side", slot_bytes=_SLOT)
    raw = encode(ID.of(b"adopted"), b"adopted")
    placement = hub.append(raw)
    record = decode(raw)

    repair(vault.index, patrol(vault.index, vault.root))

    located = vault.index.rows.body(record.id.value_uuid)
    assert located is not None
    assert located.in_hub == "side"
    assert located.span == placement.span
    assert located.value_hash == record.id.value_hash
    assert patrol(vault.index, vault.root).clean


def test_placement_is_reported_for_the_row_to_carry(vault: Storage):
    """补行时带的是**那一行该写的样子**：内容记录进 `body`，块记录进 `block`。"""
    hub = Hub.create(vault.root / "far", slot_bytes=_SLOT)
    raw = encode(ID.of(b"payload"), b"payload")
    placement = hub.append(raw)

    find = patrol(vault.index, vault.root).finds[0]

    assert find.kind is FindKind.MISSING_ROW
    assert find.block is None, "这条载荷不是指针，故它不该被补成块行"
    assert find.body is not None
    assert find.body.value_uuid == decode(raw).id.value_uuid
    assert find.body.in_hub_pack == placement.pack
    assert find.body.span == placement.span
    assert find.body.in_hub == "far"


def test_rows_pointing_at_a_missing_hub_are_not_called_lost_content(vault: Storage):
    """hub 没了只报一处 `missing_hub`：同一个原因不该同时报成"内容丢了"，
    否则读报告的人会以为盘上的字节也坏了。"""
    vault.store(b"stranded", hub="side")
    (vault.root / "side").rename(vault.root.parent / "side-away")

    report = patrol(vault.index, vault.root)

    assert {item.kind for item in report.finds} == {FindKind.MISSING_HUB}
    assert report.finds[0].hub == "side"


def test_find_hubs_returns_nothing_for_a_missing_root(tmp_path: Path):
    """根目录不存在就返回空：列 hub 不建东西。"""
    assert find_hubs(tmp_path / "nope") == ()

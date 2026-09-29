# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""档一重建契约：以载体为真源**只补缺行**，已有行一律不动，坏点即停。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core.exc import RecordFormatError
from core.storage.carrier import HEADER_BYTES as CARRIER_HEADER_BYTES
from core.storage.carrier import Carrier
from core.storage.format.id import ID
from core.storage.format.record import decode, encode
from core.storage.hub import Hub
from core.storage.index import Index
from core.storage.rows import Location, rebuild
from core.storage.tables import KERNEL_TABLES, Declaration

if TYPE_CHECKING:
    from pathlib import Path

_SLOT = 512
_HUGE = 1 << 40


def _record(payload: bytes) -> bytes:
    """造一条真实记录。"""
    return encode(ID.of(payload), payload)


def _uuid(raw: bytes) -> str:
    """记录头里的分配形态凭证。"""
    return decode(raw).id.value_uuid


def _hub(root: Path, name: str = "main") -> Hub:
    """建一个能装很多记录的 hub。"""
    return Hub.create(root / name, slot_bytes=_SLOT, max_bytes=_HUGE)


def _index(root: Path) -> Index:
    """建一个对齐好的索引库。"""
    return Index.open(root / "catalog.db", Declaration(KERNEL_TABLES), create=True)


# ---- 补登记与补行 ----


def test_rebuild_registers_hub_and_adds_missing_rows(tmp_path: Path):
    """hub 目录在、登记缺 → 补登记；盘上有记录、库里没有行 → 补行（含位置）。"""
    hub = _hub(tmp_path)
    first_raw, second_raw = _record(b"first"), _record(b"second")
    hub.append(first_raw)
    second = hub.append(second_raw)

    with _index(tmp_path) as index:
        report = rebuild(index.rows, [hub], now=1234)

        assert report.registered_hubs == ("main",)
        assert report.scanned == 2
        assert report.added_rows == (_uuid(first_raw), _uuid(second_raw))
        assert report.changed is True

        stored = index.rows.location(_uuid(second_raw))

    assert stored is not None
    assert (stored.hub, stored.pack) == ("main", second.pack)
    assert stored.span == second.span


def test_rebuild_keeps_unknown_fields_empty(tmp_path: Path):
    """重扫补回的是身份与位置：类型与落盘时刻不在记录头里，只能给空值。"""
    hub = _hub(tmp_path)
    raw = _record(b"only")
    hub.append(raw)

    with _index(tmp_path) as index:
        rebuild(index.rows, [hub], now=5)
        stored = index.rows.location(_uuid(raw))

    assert stored is not None
    assert stored.kind == ""
    assert stored.created == 0
    assert stored.updated == 0
    assert stored.birth_time == 0
    assert stored.value_hash == ID.of(b"only").value_hash
    assert stored.size == len(raw)


def test_rebuild_does_not_touch_existing_rows(tmp_path: Path):
    """已有行一律不动：库里那一行的位置停了就让它停着（处置是巡检与压实的活）。"""
    hub = _hub(tmp_path)
    raw = _record(b"keep")
    placement = hub.append(raw)
    value_uuid = _uuid(raw)

    with _index(tmp_path) as index:
        index.rows.put_location(
            Location(
                value_uuid=value_uuid,
                value_hash="stale",
                hub="main",
                pack="elsewhere",
                span=placement.span,
                size=1,
                created=7,
            )
        )
        report = rebuild(index.rows, [hub], now=9)
        stored = index.rows.location(value_uuid)

    assert report.added_rows == ()
    assert report.scanned == 1
    assert stored is not None
    assert (stored.pack, stored.value_hash, stored.created) == ("elsewhere", "stale", 7)


def test_rebuild_is_idempotent(tmp_path: Path):
    """重建一遍之后再建一遍：什么都不用补。"""
    hub = _hub(tmp_path)
    hub.append(_record(b"one"))
    hub.append(_record(b"two"))

    with _index(tmp_path) as index:
        first = rebuild(index.rows, [hub], now=1)
        second = rebuild(index.rows, [hub], now=2)

    assert first.changed is True
    assert second.changed is False
    assert second.scanned == 2


def test_rebuild_registers_an_empty_hub(tmp_path: Path):
    """空 hub 也要补登记：目录就是存在证明。"""
    hub = _hub(tmp_path, "spare")

    with _index(tmp_path) as index:
        report = rebuild(index.rows, [hub], now=3)
        stored = index.rows.hub("spare")

    assert report.registered_hubs == ("spare",)
    assert report.added_rows == ()
    assert stored is not None
    assert stored.created == 3


# ---- 坏点即停 ----


def test_rebuild_stops_at_a_bad_carrier_and_keeps_what_it_added(tmp_path: Path):
    """坏点即停：坏载体之前补的行留着，坏载体即抛（跳过是巡检的策略，不是重建的）。"""
    hub = _hub(tmp_path)
    good = Carrier(hub.packs_dir / "aaa", slot_bytes=_SLOT)
    good.append(_record(b"good"))
    good.close()
    bad = Carrier(hub.packs_dir / "bbb", slot_bytes=_SLOT)
    bad.append(_record(b"bad"))
    bad.close()
    damaged = hub.packs_dir / "bbb"
    # 截到记录内部（不是格尾补零），这样读记录头时总长与实际字节数对不上
    damaged.write_bytes(damaged.read_bytes()[: CARRIER_HEADER_BYTES + 32])

    with _index(tmp_path) as index:
        with pytest.raises(RecordFormatError):
            rebuild(index.rows, [hub], now=11)

        # 坏点之前补的行留着（重建是幂等的，重跑接着补）
        assert index.rows.count_locations() == 1
        assert index.rows.hub("main") is not None

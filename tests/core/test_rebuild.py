# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""档一重建契约：以载体为真源**只补缺行**，已有行一律不动，坏点即停。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core.exc import RecordFormatError
from core.storage.carrier import HEADER_BYTES as CARRIER_HEADER_BYTES
from core.storage.carrier import Carrier
from core.storage.format.block import BodyRef, encode_block_payload
from core.storage.format.id import ID
from core.storage.format.record import decode, encode
from core.storage.hub import Hub
from core.storage.index import Index
from core.storage.rows import BodyRow, rebuild
from core.storage.tables import Declaration, kernel_tables

if TYPE_CHECKING:
    from pathlib import Path

_SLOT = 512
_HUGE = 1 << 40


def _record(payload: bytes) -> bytes:
    """造一条内容记录（载荷不是指针，故它进 `body` 表）。"""
    return encode(ID.of(payload), payload)


def _block_record(ref: BodyRef) -> bytes:
    """造一条块记录（载荷是指针，故它进 `block` 表）。"""
    pointer = encode_block_payload(ref)
    return encode(ID.of(pointer), pointer)


def _uuid(raw: bytes) -> str:
    """记录头里的分配形态凭证。"""
    return decode(raw).id.value_uuid


def _hub(root: Path, name: str = "main") -> Hub:
    """建一个能装很多记录的 hub。"""
    return Hub.create(root / name, slot_bytes=_SLOT, max_bytes=_HUGE)


def _index(root: Path) -> Index:
    """建一个对齐好的索引库。"""
    return Index.open(root / "catalog.db", Declaration(kernel_tables()), create=True)


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
        assert report.added_bodies == (_uuid(first_raw), _uuid(second_raw))
        assert report.added_blocks == ()
        assert report.changed is True

        stored = index.rows.body(_uuid(second_raw))

    assert stored is not None
    assert (stored.hub, stored.pack) == ("main", second.pack)
    assert stored.span == second.span


def test_rebuild_routes_records_by_payload(tmp_path: Path):
    """进哪张表**由载荷判断**：带指针的进 `block`，其余进 `body`（类型为空也认得出）。"""
    hub = _hub(tmp_path)
    ref = BodyRef(value_uuid="bu", value_hash="bh")
    content_raw = _record(b"content")
    block_raw = _block_record(ref)
    hub.append(content_raw)
    hub.append(block_raw)

    with _index(tmp_path) as index:
        report = rebuild(index.rows, [hub], now=1)

        assert report.added_bodies == (_uuid(content_raw),)
        assert report.added_blocks == (_uuid(block_raw),)
        assert index.rows.count_blocks() == 1
        assert index.rows.count_bodies() == 1
        stored = index.rows.block(_uuid(block_raw))

    assert stored is not None
    assert (stored.body_value_uuid, stored.body_value_hash) == ("bu", "bh")
    assert stored.kind == ""


def test_rebuild_keeps_unknown_fields_empty(tmp_path: Path):
    """重扫补回的是身份与位置：类型与落盘时刻不在记录头里，只能给空值。"""
    hub = _hub(tmp_path)
    raw = _record(b"only")
    hub.append(raw)

    with _index(tmp_path) as index:
        rebuild(index.rows, [hub], now=5)
        stored = index.rows.body(_uuid(raw))

    assert stored is not None
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
        index.rows.put_body(
            BodyRow(
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
        stored = index.rows.body(value_uuid)

    assert report.added_bodies == ()
    assert report.added_blocks == ()
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
    assert report.added_bodies == ()
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

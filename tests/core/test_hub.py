# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""hub 契约：形状判据、读路径不建 hub、活跃载体判据、多载体顺扫。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core.exc import HubNotFoundError, HubShapeError, SlotError
from core.storage import hub as hub_module
from core.storage.carrier import Carrier
from core.storage.format.id import ID
from core.storage.format.record import decode, encode
from core.storage.hub import PACKS_DIRNAME, Hub, Placement

if TYPE_CHECKING:
    from pathlib import Path

_SLOT = 512
_HUGE = 1 << 40


class _FakeUuid:
    """替身：只提供 `hex`，用来逼出"撞名重取"这条分支。"""

    def __init__(self, value: str) -> None:
        self.hex = value


def _record(payload: bytes) -> bytes:
    """造一条真实记录。"""
    return encode(ID.of(payload), payload)


def _make_hub(tmp_path: Path, name: str = "main") -> Hub:
    """建一个带 packs/ 的 hub。"""
    return Hub.create(tmp_path / name, slot_bytes=_SLOT, max_bytes=_HUGE)


# ---- 形状判据 ----


def test_create_makes_dir_and_packs(tmp_path: Path):
    """建立是显式动作：目录与 packs/ 一起造出来。"""
    hub = _make_hub(tmp_path)

    assert hub.name == "main"
    assert hub.packs_dir.is_dir()
    assert hub.pack_names() == ()
    assert list(hub.scan()) == []


def test_create_is_idempotent(tmp_path: Path):
    """已存在的 hub 再 create 一次不出错，也不动里面的内容。"""
    hub = _make_hub(tmp_path)
    hub.append(_record(b"keep"))

    again = _make_hub(tmp_path)

    assert len(again.pack_names()) == 1


def test_read_path_refuses_missing_hub_without_creating(tmp_path: Path):
    """**读路径不建 hub**：目录不在就报错，且绝不留下一个空目录。"""
    missing = tmp_path / "nope"

    with pytest.raises(HubNotFoundError):
        Hub(missing)

    assert not missing.exists()


def test_shape_must_be_hub_not_just_a_directory(tmp_path: Path):
    """有个目录不算 hub，得有 packs/。"""
    plain = tmp_path / "plain"
    plain.mkdir()

    with pytest.raises(HubShapeError, match=PACKS_DIRNAME):
        Hub(plain)


def test_open_refuses_a_file_path(tmp_path: Path):
    """给一个文件路径不是 hub。"""
    target = tmp_path / "afile"
    target.write_bytes(b"x")

    with pytest.raises(HubNotFoundError):
        Hub(target)


def test_create_refuses_path_that_is_a_file(tmp_path: Path):
    """建立 hub 时撞上同名文件：报内核异常，不漏裸 OSError。"""
    target = tmp_path / "afile"
    target.write_bytes(b"x")

    with pytest.raises(HubShapeError, match="无法建立"):
        Hub.create(target)


def test_policy_must_be_positive(tmp_path: Path):
    """策略参数不合法当场拒绝，不带着坏参数跑到写盘那一步。"""
    path = tmp_path / "h"
    Hub.create(path)

    with pytest.raises(SlotError, match="槽长"):
        Hub(path, slot_bytes=0)
    with pytest.raises(SlotError, match="封口线"):
        Hub(path, max_bytes=0)


def test_stray_file_in_packs_is_reported(tmp_path: Path):
    """packs/ 里混着不是载体的文件即报错，不把看不懂的东西当成不存在。"""
    hub = _make_hub(tmp_path)
    (hub.packs_dir / "stray").write_bytes(b"definitely not a carrier" * 4)

    with pytest.raises(HubShapeError, match="不是载体"):
        hub.append(_record(b"x"))


# ---- 写入与活跃载体 ----


def test_first_append_creates_a_pack(tmp_path: Path):
    """第一个载体在第一条记录时出现，位置从第 0 格开始。"""
    hub = _make_hub(tmp_path)
    raw = _record(b"hello")

    placement = hub.append(raw)

    assert hub.pack_names() == (placement.pack,)
    assert placement.span.first == 0
    assert hub.read(placement) == raw


def test_append_reuses_the_active_pack(tmp_path: Path):
    """还有空间就继续写同一个载体，不每写一条就开一个文件。"""
    hub = _make_hub(tmp_path)

    first = hub.append(_record(b"one"))
    second = hub.append(_record(b"two"))

    assert first.pack == second.pack
    assert len(hub.pack_names()) == 1
    assert second.span.first > first.span.first


def test_append_picks_the_fullest_pack_with_room(tmp_path: Path):
    """有多个载体都有空间时，挑最满的那个（写入纪律是"写到满才换"）。"""
    hub = _make_hub(tmp_path)
    with Carrier(hub.packs_dir / "bigger", slot_bytes=_SLOT) as carrier:
        carrier.append(_record(b"one"))
        carrier.append(_record(b"two"))
        carrier.append(_record(b"three"))
    with Carrier(hub.packs_dir / "smaller", slot_bytes=_SLOT) as carrier:
        carrier.append(_record(b"one"))

    placement = hub.append(_record(b"next"))

    assert placement.pack == "bigger"


def test_sealed_pack_is_left_alone(tmp_path: Path):
    """写满封口线的载体不再写：封口线只管"换不换文件"。"""
    limit = 24 + _SLOT
    hub = Hub.create(tmp_path / "sealed", slot_bytes=_SLOT, max_bytes=limit)
    first = hub.append(_record(b"one"))

    sealed = Carrier(hub.packs_dir / first.pack)
    assert sealed.sealed(limit)
    sealed.close()

    second = hub.append(_record(b"two"))

    assert second.pack != first.pack
    assert len(hub.pack_names()) == 2


def test_new_packs_take_the_policy_slot_bytes(tmp_path: Path):
    """槽长只在建载体时取策略：既有载体一律保留各自文件头里的槽长。"""
    limit = 24 + _SLOT
    hub = Hub.create(tmp_path / "policy", slot_bytes=_SLOT, max_bytes=limit)
    old = hub.append(_record(b"one"))
    existing = Carrier(hub.packs_dir / old.pack)
    assert existing.slot_bytes == _SLOT
    existing.close()

    reopened = Hub(hub.path, slot_bytes=256, max_bytes=limit)
    fresh = reopened.append(_record(b"two"))

    assert fresh.pack != old.pack
    fresh_carrier = Carrier(reopened.packs_dir / fresh.pack)
    assert fresh_carrier.slot_bytes == 256
    fresh_carrier.close()
    old_carrier = Carrier(reopened.packs_dir / old.pack)
    assert old_carrier.slot_bytes == _SLOT
    old_carrier.close()


def test_new_pack_names_are_random(tmp_path: Path):
    """新载体名是随机串（无语义、无顺序号），且每个新载体各取一名。"""
    limit = 24 + _SLOT
    hub = Hub.create(tmp_path / "names", slot_bytes=_SLOT, max_bytes=limit)

    first = hub.append(_record(b"one"))
    second = hub.append(_record(b"two"))

    assert first.pack != second.pack
    assert len(first.pack) == 32
    assert len(second.pack) == 32
    assert hub.pack_names() == tuple(sorted([first.pack, second.pack]))


def test_new_pack_name_avoids_collision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """撞上已存在的载体名就重取：绝不覆盖别人的文件。"""
    limit = 24 + _SLOT
    hub = Hub.create(tmp_path / "collide", slot_bytes=_SLOT, max_bytes=limit)
    hub.append(_record(b"one"))
    taken = hub.pack_names()[0]

    names = iter([taken, "fresh-name"])
    monkeypatch.setattr(hub_module, "uuid4", lambda: _FakeUuid(next(names)))

    placement = hub.append(_record(b"two"))

    assert placement.pack == "fresh-name"


# ---- 读取 ----


def test_read_reports_unknown_pack(tmp_path: Path):
    """按位置读一个不存在的载体：报错，而且不会把它建出来。"""
    hub = _make_hub(tmp_path)
    placement = hub.append(_record(b"one"))
    missing = Placement(pack="nope", span=placement.span)

    with pytest.raises(HubNotFoundError):
        hub.read(missing)

    assert not (hub.packs_dir / "nope").exists()


def test_scan_walks_every_pack_in_name_order(tmp_path: Path):
    """顺扫覆盖全部载体：载体名排序、载体内部按写入顺序（索引库丢了靠它重建）。"""
    hub = _make_hub(tmp_path)
    with Carrier(hub.packs_dir / "aaa", slot_bytes=_SLOT) as carrier:
        carrier.append(_record(b"first"))
    with Carrier(hub.packs_dir / "bbb", slot_bytes=_SLOT) as carrier:
        carrier.append(_record(b"second"))
        carrier.append(_record(b"third"))

    seen = [(pack, decode(raw).payload) for pack, _span, raw in hub.scan()]

    assert seen == [("aaa", b"first"), ("bbb", b"second"), ("bbb", b"third")]


def test_scan_spans_can_be_read_back(tmp_path: Path):
    """顺扫给出的位置可直接用于读回：位置即事实。"""
    hub = _make_hub(tmp_path)
    hub.append(_record(b"alpha"))
    hub.append(_record(b"beta" * 300))

    for pack, span, raw in hub.scan():
        assert hub.read(Placement(pack=pack, span=span)) == raw

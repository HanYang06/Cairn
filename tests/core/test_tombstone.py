# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""墓碑契约：删除留下的标记怎么编、怎么被认出、怎么让删除有终局。

这一组钉住"删除不再被巡检撤销"这条线：**编解码 → 落盘 → 巡检放行 → 重开库依然放行**。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cbor2

from core.init import Kernel
from core.storage.format.block import (
    TOMBSTONE_KEY,
    Tombstone,
    block_payload_of,
    encode_tombstone,
    tombstone_of,
)

if TYPE_CHECKING:
    from pathlib import Path

_SPOT = Tombstone(value_uuid="u-1", value_hash="h-1", hub="main", pack="pack-1", span=(2, 8))


# ---- 编解码 ----


def test_tombstone_roundtrip():
    """墓碑编进载荷再读回来，逐项一致（位置是两个格号）。"""
    assert tombstone_of(encode_tombstone(_SPOT)) == _SPOT


def test_tombstone_lives_under_its_own_reserved_key():
    """它写在自己的保留键下，故与块载荷、与业务正文都不会混。"""
    decoded = cbor2.loads(encode_tombstone(_SPOT))

    assert isinstance(decoded, dict)
    assert TOMBSTONE_KEY in decoded
    assert block_payload_of(encode_tombstone(_SPOT)) is None, "墓碑不是块载荷"


def test_malformed_span_reads_as_not_a_tombstone():
    """格区间不是两个整数即算"这不是墓碑"——不猜、不降级，按内容读它是比对那一侧的事。"""
    raw = cbor2.dumps({TOMBSTONE_KEY: {**_SPOT.to_record(), "span": [1]}})

    assert tombstone_of(raw) is None


def test_ordinary_payloads_are_not_tombstones():
    """普通正文与不可解字节都不会被误判成墓碑。"""
    assert tombstone_of(cbor2.dumps({"span": [1, 2]})) is None
    assert tombstone_of(b"\xff\xff") is None


# ---- 落盘与巡检 ----


def test_drop_leaves_the_library_clean(tmp_path: Path):
    """删掉一个块之后巡检是干净的：墓碑让"盘上有、库里没行"这件事有了正当解释。"""
    with Kernel.create(tmp_path / "vault") as kernel:
        block = kernel.store(b"gone")

        assert kernel.drop(block.value_uuid) is True

        assert kernel.patrol().clean, "该报的是「没了」，不是「缺行」"


def test_drop_survives_a_reopen(tmp_path: Path):
    """墓碑是**盘上的事实**：重开库之后巡检照样认它，处置也不会把块补回来。"""
    vault = tmp_path / "vault"
    with Kernel.create(vault) as kernel:
        block = kernel.store(b"gone")
        assert kernel.drop(block.value_uuid) is True
        deleted = block.value_uuid

    with Kernel.open(vault) as kernel:
        assert kernel.patrol().clean

        kernel.repair(kernel.patrol())
        assert kernel.locate(deleted) is None, "处置不该把删掉的那一条补回来"


def test_dropping_a_missing_block_changes_nothing(tmp_path: Path):
    """删一个不存在的块：返回假，且不留墓碑（没有可指的对象）。"""
    with Kernel.create(tmp_path / "vault") as kernel:
        assert kernel.drop("没有这个块") is False

        assert kernel.patrol().clean

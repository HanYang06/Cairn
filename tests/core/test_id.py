# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""身份层契约：唯一性、内容绑定、位置段。"""

from __future__ import annotations

from hashlib import sha256

from core.storage.format.id import ID, digest, new_uuid

_SAMPLE = "巨石堆".encode()


def test_fresh_ids_do_not_share_identity():
    """两个新签发的 ID 不得共用身份。

    这条是回归线：dataclass 的默认值若在类定义时求值，全部实例会共用同一份
    uuid 与时间戳，内容寻址的底座即在此塌陷。
    """
    first = ID()
    second = ID()

    assert first.value_uuid != second.value_uuid
    assert first.birth_time > 0


def test_fresh_id_is_unbound_to_content():
    """新签发的 ID 未绑定内容：摘要形态为空串，且不与任何 ID 同内容。"""
    fresh = ID()

    assert fresh.value_hash == ""
    assert not fresh.same_content(fresh)
    assert not fresh.same_content(ID.of(_SAMPLE))


def test_fresh_id_defaults_are_independent_instances():
    """默认值不得被实例共享：改一处位置段不得影响另一个实例。"""
    first = ID()
    second = ID()
    first.in_hub = "main"
    first.in_pack_slot = (3, 7)

    assert second.in_hub == ""
    assert second.in_pack_slot == (0, 0)


def test_digest_matches_content_hash():
    """摘要形态与内容寻址同口径：同内容同值，内容变则值变。"""
    assert digest(_SAMPLE) == sha256(_SAMPLE).hexdigest()
    assert digest(_SAMPLE) != digest(_SAMPLE + b"!")


def test_new_uuid_hands_out_new_values():
    """分配形态每次调用都得新值。"""
    assert new_uuid() != new_uuid()


def test_id_of_content_binds_digest_and_keeps_identity_free():
    """按内容签发的 ID：摘要由内容定，分配形态与内容无关。"""
    first = ID.of(_SAMPLE)
    second = ID.of(_SAMPLE)

    assert first.value_hash == sha256(_SAMPLE).hexdigest()
    assert first.value_uuid != second.value_uuid
    assert first.same_content(second)


def test_same_content_rejects_other_content():
    """不同内容的两套凭证都不相等。"""
    assert not ID.of(_SAMPLE).same_content(ID.of(_SAMPLE + b"x"))


def test_same_content_ignores_position_and_name():
    """判重只看摘要形态，位置与名称不参与。"""
    left = ID.of(_SAMPLE)
    right = ID.of(_SAMPLE)
    left.in_hub, left.in_hub_pack, left.name = "a", "p1", "甲"
    right.in_hub, right.in_hub_pack, right.name = "b", "p2", "乙"

    assert left.same_content(right)


def test_located_needs_both_hub_and_pack():
    """物理坐标写全才算已定位。"""
    record = ID.of(_SAMPLE)

    assert not record.located
    record.in_hub = "main"
    assert not record.located
    record.in_hub_pack = "packs/0001"
    assert record.located

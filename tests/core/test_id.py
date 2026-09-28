# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""身份层用例：ID 的两套凭证、位置段与落盘子集。

设计依据：`docs/architecture/storage-design.md` §3。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from core.types import Id, InvalidIdError, SlotRange, ValueHash, ValueUuid

_CROCKFORD = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


# ---- ValueUuid：分配形态（比较有效、去重无效）----


def test_uuid_new_shape() -> None:
    value = ValueUuid.new()
    assert len(value) == 26
    assert set(value) <= _CROCKFORD
    assert value[0] <= "7"


def test_uuid_new_is_unique() -> None:
    values = {ValueUuid.new() for _ in range(300)}
    assert len(values) == 300


def test_uuid_parse_roundtrip() -> None:
    value = ValueUuid.new()
    assert ValueUuid.parse(str(value)) == value


def test_uuid_parse_normalizes_case() -> None:
    value = ValueUuid.new()
    assert ValueUuid.parse(str(value).lower()) == value


def test_uuid_time_ms_orders_by_issue() -> None:
    first = ValueUuid.new()
    second = ValueUuid.new()
    assert first.time_ms <= second.time_ms


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "01ARZ3NDEKTSV4RRFFQ69G5FA",
        "8ZZZZZZZZZZZZZZZZZZZZZZZZZ",
        "01ARZ3NDEKTSV4RRFFQ69G5FA!",
        "0" * 27,
    ],
)
def test_uuid_parse_rejects_bad_shape(bad: str) -> None:
    with pytest.raises(InvalidIdError):
        ValueUuid.parse(bad)


# ---- ValueHash：摘要形态（去重有效、比较无效）----


def test_hash_is_deterministic() -> None:
    assert ValueHash.of(b"same") == ValueHash.of(b"same")


def test_hash_differs_by_content() -> None:
    assert ValueHash.of(b"a") != ValueHash.of(b"b")


def test_hash_context_separates_domains() -> None:
    assert ValueHash.of(b"x", context=b"body") != ValueHash.of(b"x", context=b"block")


def test_hash_shape_and_roundtrip() -> None:
    value = ValueHash.of(b"x")
    assert len(value) == 64
    assert set(value) <= set("0123456789abcdef")
    assert ValueHash.parse(str(value)) == value


def test_hash_from_digest_requires_32_bytes() -> None:
    assert len(ValueHash.from_digest(b"\x00" * 32)) == 64
    with pytest.raises(InvalidIdError):
        ValueHash.from_digest(b"\x00" * 31)


@pytest.mark.parametrize("bad", ["", "AB" * 32, "0" * 63, "g" * 64])
def test_hash_parse_rejects_bad_shape(bad: str) -> None:
    with pytest.raises(InvalidIdError):
        ValueHash.parse(bad)


# ---- SlotRange：物理坐标 ----


def test_slot_range_end_is_derived() -> None:
    assert SlotRange(2, 7).end == 8
    assert SlotRange(0, 1).end == 0


def test_slot_range_str_carries_head() -> None:
    assert str(SlotRange(2, 7)) == "2:7:0"
    assert str(SlotRange(2, 7, 5)) == "2:7:5"


def test_slot_range_parse_roundtrip() -> None:
    assert SlotRange.parse("2:7:5") == SlotRange(2, 7, 5)
    assert SlotRange.parse("2:7") == SlotRange(2, 7)
    for bad in ("", "2", "2:", ":7", "2:7:", "a:7", "2:0", "2:7:-1"):
        with pytest.raises(InvalidIdError):
            SlotRange.parse(bad)


def test_slot_range_parse_only_accepts_ascii_digits() -> None:
    """全角数字 / 阿拉伯-印度数字要被拒：`isdecimal()` 认它们、`int()` 也照收，
    于是这种脏字节会莫名其妙地"能解析"（评审指出的一条）。"""
    for bad in ("１２:３", "١٢:٣", "2:７"):
        with pytest.raises(InvalidIdError):
            SlotRange.parse(bad)


def test_slot_range_parse_rejects_absurdly_long_numbers() -> None:
    """超长数字串也走 `InvalidIdError`（`int()` 的位数上限会抛 `ValueError`）。

    契约是"非法槽区间一律抛 `InvalidIdError`"——漏出去一个原始 `ValueError`，
    调用方按类型捕获就漏掉了这条。
    """
    with pytest.raises(InvalidIdError):
        SlotRange.parse("9" * 5000 + ":1")


@pytest.mark.parametrize(
    ("start", "count", "head"),
    [(-1, 1, 0), (0, 0, 0), (0, -3, 0), (0, 1, -2)],
)
def test_slot_range_rejects_bad_bounds(start: int, count: int, head: int) -> None:
    with pytest.raises(ValueError, match="槽"):
        SlotRange(start, count, head)


def test_slot_range_is_frozen() -> None:
    slot = SlotRange(1, 2)
    with pytest.raises(FrozenInstanceError):
        slot.start = 5  # type: ignore[misc]


# ---- Id：两套凭证并存、落盘取子集 ----


def test_id_carries_both_credentials() -> None:
    one = Id.new(b"hello", name="body ID")
    assert isinstance(one.value_uuid, ValueUuid)
    assert isinstance(one.value_hash, ValueHash)


def test_id_same_content_shares_hash_but_not_uuid() -> None:
    first = Id.new(b"hello")
    second = Id.new(b"hello")
    assert first.value_hash == second.value_hash
    assert first.value_uuid != second.value_uuid


def test_id_issued_is_millisecond_int() -> None:
    one = Id.new(b"x")
    assert isinstance(one.issued, int)
    assert one.issued > 0


def test_id_location_fields_are_carried() -> None:
    one = Id.new(
        b"x",
        name="body ID",
        issuer="cairn",
        in_bucket_name="main",
        in_pack_name="3f9a",
        in_pack_path="vault/main/packs/3f9a",
        in_file_slot=(SlotRange(2, 7), SlotRange(9, 1)),
    )
    assert one.name == "body ID"
    assert one.issuer == "cairn"
    assert one.in_bucket_name == "main"
    assert one.in_pack_name == "3f9a"
    assert one.in_file_slot == (SlotRange(2, 7), SlotRange(9, 1))


def test_id_record_is_the_persistence_subset() -> None:
    one = Id.new(
        b"x",
        in_bucket_name="main",
        in_pack_name="3f9a",
        in_pack_path="vault/main/packs/3f9a",
        in_file_path="vault/main/packs/3f9a",
        in_file_name="3f9a",
        in_net_ip="10.0.0.1",
        in_file_slot=(SlotRange(2, 7),),
    )
    record = one.record()
    assert set(record) == {
        "value_uuid",
        "value_hash",
        "name",
        "issued",
        "issuer",
        "in_bucket_name",
        "in_pack_name",
    }
    for not_persisted in (
        "in_file_slot",
        "in_pack_path",
        "in_file_path",
        "in_file_name",
        "in_net_ip",
    ):
        assert not_persisted not in record


def test_id_record_roundtrip_for_persisted_fields() -> None:
    """落盘子集的往返：只比较**进落盘的那些字段**，位置段不参与。"""
    one = Id.new(b"x", name="body ID", issuer="cairn", in_bucket_name="main")
    back = Id.from_record(one.record())
    assert back.value_uuid == one.value_uuid
    assert back.value_hash == one.value_hash
    assert back.name == one.name
    assert back.issued == one.issued
    assert back.issuer == one.issuer
    assert back.in_bucket_name == one.in_bucket_name


def test_id_from_record_ignores_unknown_keys() -> None:
    raw = Id.new(b"x").record()
    raw["future_field"] = "whatever"
    assert Id.from_record(raw).value_hash == raw["value_hash"]


def test_id_from_record_treats_explicit_null_as_empty() -> None:
    """键在、值是显式 null → 还原成空串，**不是字符串 "None"**。

    `str(None)` 会造出一个幽灵名字 / 幽灵桶名，下游按名匹配时就对不上了（评审指出的一条）。
    """
    raw = Id.new(b"x").record()
    raw.update({"name": None, "issuer": None, "in_bucket_name": None, "in_pack_name": None})
    back = Id.from_record(raw)
    assert (back.name, back.issuer, back.in_bucket_name, back.in_pack_name) == ("", "", "", "")


def test_id_from_record_requires_identity_keys() -> None:
    raw = Id.new(b"x").record()
    del raw["issued"]
    with pytest.raises(InvalidIdError):
        Id.from_record(raw)


def test_id_is_hashable_and_frozen() -> None:
    one = Id.new(b"x")
    assert len({one, Id.new(b"x")}) == 2
    with pytest.raises(FrozenInstanceError):
        one.name = "changed"  # type: ignore[misc]


def test_id_str_shows_place_when_known() -> None:
    assert str(Id.new(b"x", in_bucket_name="main", in_pack_name="3f9a")).endswith("@main/3f9a")
    assert "@" not in str(Id.new(b"x"))

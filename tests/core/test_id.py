# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""ID 契约:名字与凭证,局部可变,**段列表**,正文摘要链,库里那一行.

本文件钉六件事:

- **身份只有一条来源**:`value_uuid` 由签发分配,与内容无关;摘要形态不属于身份;
- **可变是局部的**:`value_uuid` / `birth_time` / `name` 创建即锁死,位置段可改;
- **名字由持有者推出**:`ID(self)` 是最省事的写法,且**只记名字,不持有对象**;
- **段列表的规范形四条**:升序,不重叠,相邻合并,段数最少;
- **编码与解析各只有一套**:位置段的 `pack_segments` / `parse_segments`,
  正文摘要链的 `encode_body_history` / `parse_body_history`;
- **库里的行恰好七列**:身份字段加正文摘要链一列,**没有"哪几格是属性槽"那一列**.
"""

from __future__ import annotations

import gc
import weakref
from hashlib import sha256

import pytest

from core.exc import InvalidIdError
from core.storage.db.engine import columns_of
from core.storage.db.id import (
    BODY_HISTORY_FIELD,
    ID,
    ID_FIELDS,
    SlotSpan,
    canonical_segments,
    digest,
    encode_body_history,
    keep_generations,
    new_uuid,
    pack_segments,
    parse_body_history,
    parse_segments,
    segments_of,
)


class Notedata:
    """一个冒充载体的类:只用它的名字,不用它的任何别的东西."""


# ---- 签发 ----


def test_a_new_id_has_an_allocation_credential_and_a_birth_time():
    """签发只做两件事:分配一个唯一标识,记下**它自己**被签发的时刻."""
    identity = ID(Notedata)

    assert identity.value_uuid
    assert identity.birth_time > 0
    assert not identity.located


def test_two_issued_ids_never_collide():
    """分配形态与内容无关:签发两次即两个身份,哪怕它们指同一份内容."""
    first, second = ID(), ID()

    assert first.value_uuid != second.value_uuid


def test_the_digest_algorithm_is_sha256():
    """摘要口径就这一条,测试直接对算法:换算法必须是有意的."""
    assert digest(b"cairn") == sha256(b"cairn").hexdigest()


def test_new_uuid_keeps_issuing_distinct_values():
    """签发算法收在一处:换实现只动 `new_uuid` 一个函数."""
    assert new_uuid() != new_uuid()


@pytest.mark.parametrize(
    "gone", ["value_hash", "EMPTY_HASH", "of", "bind", "bound", "same_content"]
)
def test_the_digest_form_is_no_longer_part_of_identity(gone: str):
    """**摘要形态不属于身份**(2026-10-02 裁定):随它退役的成员一个都不在."""
    import core.storage.db.id as module  # noqa: PLC0415 — 用例按名字逐个取证

    assert not hasattr(ID, gone)
    assert not hasattr(module, gone)


@pytest.mark.parametrize("gone", ["ATTR_SLOT_FIELD", "attr_in_pack_slot"])
def test_the_attr_slot_column_is_gone(gone: str):
    """**"哪几格是属性槽"那一列已删**(2026-10-02 修正裁定).

    它错在"用 pack 内坐标表达跨 pack 的事":槽号只在 pack 内有意义,而属性槽与正文槽
    靠槽头种类分辨.故常量与属性一个都不在.
    """
    import core.storage.db.id as module  # noqa: PLC0415 — 用例按名字逐个取证

    assert not hasattr(ID, gone)
    assert not hasattr(module, gone)


# ---- 名字由持有者推出 ----


def test_passing_the_holder_resolves_the_name_from_it():
    """**`ID(self)` 是最省事的写法**:名字从持有者推出来,故不必在类里再写一遍类名."""
    holder = Notedata()

    assert ID(holder).name == "notedata"
    assert ID(Notedata).name == "notedata", "传类也认，两条路一个答案"
    assert ID("显式给的名字").name == "显式给的名字", "给字符串就照用"
    assert ID().name == "", "什么都不给就是空名，不是编出来的"


def test_the_holder_is_not_kept():
    """**只记名字,不持有那个对象**:`obj → id → obj` 会成环,块永远回收不掉."""
    holder = Notedata()
    identity = ID(holder)
    watcher = weakref.ref(holder)
    del holder
    gc.collect()

    assert watcher() is None, "ID 不该让持有者活着"
    assert identity.name == "notedata", "名字已经解析出来了，不靠对象"


# ---- 局部可变 ----


def test_the_allocation_credential_is_locked_at_creation():
    """分配形态凭证创建即锁死:改它就是另一个身份."""
    identity = ID()

    with pytest.raises(AttributeError):
        identity.value_uuid = "改"  # type: ignore[misc]


def test_the_birth_time_is_locked_at_creation():
    """签发时刻创建即锁死:它记的是"这个 ID 什么时候生的",不是可调的状态."""
    identity = ID()

    with pytest.raises(AttributeError):
        identity.birth_time = 0  # type: ignore[misc]


def test_the_name_is_locked_once_resolved():
    """名字由持有者定,没有"之后改"的正当理由,故同样锁死."""
    identity = ID(Notedata)

    with pytest.raises(AttributeError):
        identity.name = "别的"  # type: ignore[misc]


def test_an_id_holds_no_unexpected_attributes():
    """字段就是那几个:`__slots__` 拦住"另行挂一个状态上去"."""
    identity = ID()

    with pytest.raises(AttributeError):
        identity.something_else = 1  # type: ignore[attr-defined]


def test_the_position_segment_stays_writable():
    """位置段**可写**:它是真源,写入后由库记下,回收搬移后重写."""
    identity = ID()

    identity.place([3, 4], hub="main", pack="abc")

    assert identity.located
    assert identity.in_pack_slot == [(3, 4)]
    assert identity.slots == (3, 4)


def test_placing_in_groups_keeps_the_groups_apart():
    """分组写位置段:**组内相邻者并段,组与组之间不并**,次序照给的次序.

    分组的理由只有一条——写侧的次序有语义(属性槽在前,正文槽在后);
    **"哪一格是什么"不在这里表达**,那是槽头的事.
    """
    identity = ID()

    identity.place([5, 6], [9], hub="main", pack="abc")

    assert identity.in_pack_slot == [(5, 6), 9], "两组各自归位，不跨组合并"
    assert identity.slots == (5, 6, 9)


def test_clearing_the_place_also_drops_the_history():
    """删除之后位置段与摘要链都不该再指着已失效的坐标."""
    identity = ID()
    identity.place([1], hub="main", pack="abc")
    identity.body_history = ["aaaa"]

    identity.clear_place()

    assert not identity.located
    assert identity.in_pack_slot == []
    assert identity.body_history == []


# ---- 段列表:规范形四条 ----


def test_segments_are_sorted_and_merged():
    """规范形:**升序,不重叠,相邻合并,段数最少**."""
    assert canonical_segments([5, 3, 4, 1]) == (1, (3, 5))
    assert canonical_segments([(3, 3)]) == (3,), "单格与区间是同一格，段数取最少"
    assert canonical_segments([(1, 2), (3, 4)]) == ((1, 4),), "相邻两段并成一段"
    assert canonical_segments([1, 5]) == (1, 5), "不相邻就不并"


def test_an_empty_segment_list_is_legal():
    """没落盘时一个槽都不占:空段列表是合法值,不是错误."""
    assert canonical_segments([]) == ()
    assert parse_segments("") == ()
    assert pack_segments([]) == ""


def test_segments_reject_illegal_elements():
    """格号为负,区间反着写,元素形态不对,一律当场报错."""
    with pytest.raises(InvalidIdError):
        canonical_segments([-1])
    with pytest.raises(InvalidIdError):
        canonical_segments([(3, 1)])
    with pytest.raises(InvalidIdError):
        canonical_segments([True])
    with pytest.raises(InvalidIdError):
        canonical_segments(["三"])  # type: ignore[list-item]


def test_segments_of_builds_from_a_slot_or_a_span():
    """写侧最常用的两种构造:一个格号,或一个闭区间."""
    assert segments_of(7) == [7]
    assert segments_of(span=(2, 5)) == [(2, 5)]
    with pytest.raises(InvalidIdError):
        segments_of()


def test_the_text_form_writes_single_slots_and_ranges():
    """文本形态:**单格写一个数,连续的一段写 `起-止`**."""
    assert pack_segments([1, 5, 9]) == "1,5,9"
    assert pack_segments([2, 3, 4]) == "2-4"
    assert pack_segments([(4, 7)]) == "4-7"
    assert pack_segments([3]) == "3"


def test_the_text_form_round_trips():
    """编出来再解回去,段列表一字不差."""
    spans: list[SlotSpan] = [0, 2, (5, 9), 12]

    assert parse_segments(pack_segments(spans)) == canonical_segments(spans)


def test_parsing_reads_the_old_range_form_too():
    """`3:5` 这种旧写法仍读得出来(只为读旧值,新写一律用 `起-止`)."""
    assert parse_segments("3:5") == ((3, 5),)
    assert parse_segments("3") == (3,)


def test_parsing_rejects_a_broken_text():
    """段落写不成数字,空项,区间反着写,一律报错,不静默取零."""
    with pytest.raises(InvalidIdError):
        parse_segments("1,,2")
    with pytest.raises(InvalidIdError):
        parse_segments("三")
    with pytest.raises(InvalidIdError):
        parse_segments("9-2")


# ---- 正文摘要链 ---- #


def test_the_history_round_trips_newest_first():
    """摘要链编出来再解回去,世代次序是**新到旧**,条数一条不多."""
    chain = ["aa", "bb", "cc"]

    assert parse_body_history(encode_body_history(chain)) == ("aa", "bb", "cc")


def test_an_empty_history_is_an_empty_text():
    """还没有正文即空串;空串读回空链."""
    assert encode_body_history([]) == ""
    assert parse_body_history("") == ()


def test_the_history_carries_digests_not_slots():
    """**摘要链里没有槽号**:一条摘要是一个十六进制串,而槽号只在 pack 内有意义.

    越 pack(甚至越 hub)的关联只能用摘要——这正是这一列改口径的理由.
    """
    written = encode_body_history([digest(b"cairn")])

    assert digest(b"cairn") in written
    assert "0-1" not in written, "它不是段列表"


def test_history_parsing_rejects_broken_text():
    """解不成数组即报错,不静默当成"没有正文";条目形态不对同样报错."""
    with pytest.raises(InvalidIdError):
        parse_body_history("not json at all")
    with pytest.raises(InvalidIdError):
        parse_body_history('{"a": 1}')
    with pytest.raises(InvalidIdError):
        parse_body_history('[""]')
    with pytest.raises(InvalidIdError):
        parse_body_history("[7]")


def test_encoding_refuses_an_empty_digest():
    """空串不是一条世代:写进去就会让"当前正文是哪一份"这一问答不出东西来."""
    with pytest.raises(InvalidIdError, match="非空文本"):
        encode_body_history([""])


def test_keep_generations_trims_to_the_depth():
    """保留世代数数的是**总共几代**(最新那一代就是当前用的),故深度 1 只留一条."""
    chain = ["一", "二", "三", "四"]

    assert keep_generations(chain, depth=2) == ("一", "二")
    assert keep_generations(chain, depth=1) == ("一",), "只留当前那一代"
    assert keep_generations(chain, depth=0) == ()
    assert keep_generations(chain, depth=99) == ("一", "二", "三", "四")


def test_the_current_generation_is_the_newest_digest():
    """**最新那一代就是当前用的那份正文的摘要**;没有正文时空串."""
    identity = ID()
    identity.body_history = ["新", "旧"]

    assert identity.current_generation == "新"
    assert ID().current_generation == ""


# ---- 库里那一行 ---- #


def test_the_identity_field_list_is_the_id_itself():
    """身份列清单是从 `ID` 上数出来的,不是另抄一份子集——加一个字段就多一列."""
    assert ID_FIELDS == (
        "name",
        "value_uuid",
        "birth_time",
        "in_hub",
        "in_hub_pack",
        "in_pack_slot",
    )
    assert "value_hash" not in ID_FIELDS, "摘要形态已移出身份"


def test_the_table_has_exactly_seven_columns():
    """**身份表恰好七列**:身份字段加正文摘要链一列,一个不多.

    没有 `attr_in_pack_slot`:那一列错在"用 pack 内坐标表达跨 pack 的事"——
    属性槽与正文槽靠槽头种类分辨,载体上每一格本来就写着.
    """
    assert columns_of() == (
        "name",
        "value_uuid",
        "birth_time",
        "in_hub",
        "in_hub_pack",
        "in_pack_slot",
        BODY_HISTORY_FIELD,
    )
    assert len(columns_of()) == 7
    assert "attr_in_pack_slot" not in columns_of()


def test_the_field_list_matches_the_slots():
    """清单与 `__slots__` 一一对应,只多出库里那一列摘要链(它不是身份字段)."""
    slots = {name.lstrip("_") for name in ID.__slots__}
    extra = {BODY_HISTORY_FIELD}

    assert slots - extra == set(ID_FIELDS)
    assert extra - slots == set()


def test_a_row_round_trips():
    """写下去,读回来:身份,位置段与摘要链一字不差."""
    identity = ID(Notedata, value_uuid="u", birth_time=7)
    identity.place([1, 4, (5, 6), 20], hub="main", pack="p")
    identity.body_history = ["aa", "bb"]

    restored = ID.from_row(identity.to_row())

    assert restored.name == "notedata"
    assert restored.value_uuid == "u"
    assert restored.birth_time == 7
    assert restored.in_hub == "main"
    assert restored.in_hub_pack == "p"
    assert restored.in_pack_slot == [1, (4, 6), 20], "4、5、6 相邻，按次序归成一段"
    assert restored.body_history == ["aa", "bb"]
    assert restored.current_generation == "aa"


def test_a_row_missing_a_credential_is_refused():
    """分配形态凭证缺失即抛:半截身份读不得,补一个编的值更不行."""
    with pytest.raises(InvalidIdError):
        ID.from_row({})
    with pytest.raises(InvalidIdError):
        ID.from_row({"value_uuid": ""})


def test_a_row_without_a_place_reads_as_unplaced():
    """只有凭证的行读成"还没落点",位置段与摘要链都是空的."""
    restored = ID.from_row({"value_uuid": "u"})

    assert restored.value_uuid == "u"
    assert restored.name == ""
    assert restored.birth_time == 0
    assert not restored.located
    assert restored.in_pack_slot == []
    assert restored.body_history == []


def test_a_corrupt_integer_field_is_refused():
    """整数字段形态非法即抛:不静默吞掉脏值."""
    with pytest.raises(InvalidIdError, match="整数字段非法"):
        ID.from_row({"value_uuid": "u", "birth_time": "昨天"})


def test_an_id_repr_shows_its_place():
    """诊断用:名字,凭证前一段,以及位置(若已落盘)."""
    identity = ID(Notedata, value_uuid="abcdefgh")
    identity.place([2], hub="main", pack="p")

    text = repr(identity)

    assert "notedata" in text
    assert "abcdefgh" in text
    assert "main" in text

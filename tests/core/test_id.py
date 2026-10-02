# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""ID 契约：两套凭证、**局部可变**、落盘子集。

本文件钉五件事：

- **两套凭证并存**：分配形态（签发时定、去重无效）与摘要形态（由内容算、比较无效）；
- **可变是局部的**：`value_uuid` / `birth_time` 创建即锁死，`value_hash` 只由 `bind` 写一次，
  而位置段可改（它是投影，压实搬移后重算即得）；
- **名字由持有者推出**：`ID(self)` 是最省事的写法，且**只记名字、不持有对象**；
- **未绑定内容不伪造摘要**：空串就是"还没绑"，读一条缺摘要的记录即报错；
- **落盘子集**：记录头只带推不出来的那几项，位置段不带（扫到它时位置已知）。
"""

from __future__ import annotations

import gc
import weakref
from hashlib import sha256

import pytest

from core.exc import InvalidIdError
from core.storage.db.id import EMPTY_HASH, ID, ID_FIELDS, digest, new_uuid

_SAMPLE = "巨石堆".encode()


class Notedata:
    """一个冒充载体的类：只用它的名字，不用它的任何别的东西。"""


# ---- 签发 ----


def test_a_new_id_has_an_allocation_credential_and_a_birth_time():
    """签发只做两件事：分配一个唯一标识、记下**它自己**被签发的时刻。"""
    identity = ID(Notedata)

    assert identity.value_uuid
    assert identity.birth_time > 0
    assert identity.value_hash == EMPTY_HASH, "还没绑定内容，摘要就是空的"
    assert not identity.bound
    assert not identity.located


def test_two_issued_ids_never_collide():
    """分配形态与内容无关：签发两次即两个身份，哪怕它们指同一份内容。"""
    first, second = ID(), ID()

    assert first.value_uuid != second.value_uuid
    assert first.value_hash == second.value_hash == EMPTY_HASH


# ---- 名字由持有者推出 ----


def test_passing_the_holder_resolves_the_name_from_it():
    """**`ID(self)` 是最省事的写法**：名字从持有者推出来，故不必在类里再写一遍类名。"""
    holder = Notedata()

    assert ID(holder).name == "notedata"
    assert ID(Notedata).name == "notedata", "传类也认，两条路一个答案"
    assert ID("显式给的名字").name == "显式给的名字", "给字符串就照用"
    assert ID().name == "", "什么都不给就是空名，不是编出来的"


def test_the_holder_is_not_kept():
    """**只记名字，不持有那个对象**：`obj → id → obj` 会成环，块永远回收不掉。"""
    holder = Notedata()
    identity = ID(holder)
    watcher = weakref.ref(holder)
    del holder
    gc.collect()

    assert watcher() is None, "ID 不该让持有者活着"
    assert identity.name == "notedata", "名字已经解析出来了，不靠对象"


# ---- 局部可变：三项锁死 ----


def test_the_allocation_credential_is_locked_at_creation():
    """分配形态凭证创建即锁死：改它就是另一个身份。"""
    identity = ID()

    with pytest.raises(AttributeError):
        identity.value_uuid = "改"  # type: ignore[misc]


def test_the_birth_time_is_locked_at_creation():
    """签发时刻创建即锁死：它记的是"这个 ID 什么时候生的"，不是可调的状态。"""
    identity = ID()

    with pytest.raises(AttributeError):
        identity.birth_time = 0  # type: ignore[misc]


def test_the_name_is_locked_once_resolved():
    """名字由持有者定，没有"之后改"的正当理由，故同样锁死。"""
    identity = ID(Notedata)

    with pytest.raises(AttributeError):
        identity.name = "别的"  # type: ignore[misc]


def test_the_position_segment_stays_writable():
    """位置段**可写**：它是投影，写入后回填，压实搬移后重算即得。"""
    identity = ID.of(_SAMPLE)
    identity.in_hub = "main"
    identity.in_hub_pack = "abc"
    identity.in_pack_slot = (3, 4)

    assert identity.located
    assert identity.in_pack_slot == (3, 4)


def test_an_id_holds_no_unexpected_attributes():
    """字段就是那几个：`__slots__` 拦住"另行挂一个状态上去"。"""
    identity = ID()

    with pytest.raises(AttributeError):
        identity.something_else = 1  # type: ignore[attr-defined]


# ---- 内容绑定 ----


def test_signing_by_content_pins_the_digest():
    """按内容签发：同内容恒得同一个摘要，故去重成立。"""
    first = ID.of(_SAMPLE)
    second = ID.of(_SAMPLE)

    assert first.value_hash == digest(_SAMPLE)
    assert first.value_hash == second.value_hash
    assert first.value_uuid != second.value_uuid, "分配形态仍各不相同"


def test_binding_later_fills_the_digest_of_an_unbound_id():
    """先建对象、内容后定：绑定一次即补上摘要。"""
    identity = ID.unbound()

    assert identity.bind(_SAMPLE) == digest(_SAMPLE)
    assert identity.bound
    assert identity.same_content(ID.of(_SAMPLE))


def test_the_digest_is_locked_after_it_is_bound():
    """摘要写定即不可改：`bind` 是唯一通路，属性本身只读。"""
    identity = ID.of(_SAMPLE)

    with pytest.raises(AttributeError):
        identity.value_hash = "改"  # type: ignore[misc]


def test_binding_the_same_content_twice_is_harmless():
    """重复绑定同一份内容不算错：它是同一件事的重放。"""
    identity = ID.of(_SAMPLE)

    assert identity.bind(_SAMPLE) == digest(_SAMPLE)


def test_binding_a_different_content_is_refused():
    """一份身份不许指两份内容：那是身份被用错了，当场报错而不是静默覆盖。"""
    identity = ID.of(_SAMPLE)

    with pytest.raises(InvalidIdError, match="别的内容"):
        identity.bind(b"another")


def test_same_content_compares_by_digest_only():
    """ "是不是同一份内容"只比摘要：分配形态不同不影响。"""
    first = ID.of(_SAMPLE)
    second = ID.of(_SAMPLE)

    assert first.same_content(second)
    assert not first.same_content(ID.of(b"other"))


def test_an_unbound_id_is_never_the_same_content():
    """未绑定内容的身份**恒不相等**：空摘要与空摘要相同，但那不构成"同一份内容"。"""
    first, second = ID(), ID()

    assert first.value_hash == second.value_hash == EMPTY_HASH
    assert not first.same_content(second)


# ---- 落盘 ----


def test_the_record_carries_identity_but_not_position():
    """落盘只带推不出来的那几项：名字、两套凭证、签发时刻；**位置不入记录**。"""
    identity = ID.of(_SAMPLE, name=Notedata)
    raw = identity.to_record()

    assert raw == {
        "name": "notedata",
        "value_uuid": identity.value_uuid,
        "value_hash": identity.value_hash,
        "birth_time": identity.birth_time,
    }
    assert "in_hub" not in raw
    assert "in_pack_slot" not in raw


def test_a_record_round_trips():
    """写下去、读回来，身份一字不差；位置仍空着（它本来就不在记录里）。"""
    identity = ID.of(_SAMPLE, name="body")

    restored = ID.from_record(identity.to_record())

    assert restored.name == identity.name
    assert restored.value_uuid == identity.value_uuid
    assert restored.value_hash == identity.value_hash
    assert restored.birth_time == identity.birth_time
    assert not restored.located


def test_a_record_missing_a_credential_is_refused():
    """分配形态凭证缺失即抛：半截身份读不得，补一个编的值更不行。"""
    with pytest.raises(InvalidIdError):
        ID.from_record({})
    with pytest.raises(InvalidIdError):
        ID.from_record({"value_uuid": ""})
    with pytest.raises(InvalidIdError):
        ID.from_record({"value_hash": "h"})


def test_a_record_without_a_digest_is_allowed_and_reads_as_unbound():
    """摘要**允许为空**：记录的身份不必与内容摘要重合。

    内容记录按载荷摘要寻址，它自己那份身份是分配形态；把摘要读成空只是"这份身份没绑内容"，
    不是坏记录。
    """
    restored = ID.from_record({"value_uuid": "u"})

    assert restored.value_uuid == "u"
    assert not restored.bound


def test_an_unknown_birth_time_reads_as_zero_not_now():
    """缺签发时刻读成 0，**不取当前时刻**——否则读旧记录会凭空冒出一个时间。"""
    restored = ID.from_record({"value_uuid": "u", "value_hash": "h"})

    assert restored.birth_time == 0
    assert restored.name == ""


def test_a_corrupt_integer_field_is_refused():
    """整数字段形态非法即抛：不静默吞掉脏字节。"""
    with pytest.raises(InvalidIdError, match="整数字段非法"):
        ID.from_record({"value_uuid": "u", "value_hash": "h", "birth_time": "昨天"})


# ---- 字段清单 ----


def test_the_identity_field_list_is_the_id_itself():
    """身份列清单是从 `ID` 上数出来的，不是另抄一份子集——加一个字段就多一列。"""
    assert ID_FIELDS == (
        "name",
        "value_uuid",
        "value_hash",
        "birth_time",
        "in_hub",
        "in_hub_pack",
        "in_pack_slot",
    )


def test_the_field_list_matches_the_slots():
    """清单与 `__slots__` 一一对应：私有槽去掉前缀即公开字段名。"""
    slots = {name.lstrip("_") for name in ID.__slots__}
    assert slots == set(ID_FIELDS)


def test_new_uuid_keeps_issuing_distinct_values():
    """签发算法收在一处：换实现只动 `new_uuid` / `digest` 两个函数。"""
    assert new_uuid() != new_uuid()


def test_the_digest_algorithm_is_sha256():
    """摘要口径就这一条，测试直接对算法：换算法必须是有意的。"""
    assert digest(b"cairn") == sha256(b"cairn").hexdigest()

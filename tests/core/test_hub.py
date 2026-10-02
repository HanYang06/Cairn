# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""hub 的契约：形状判据、选活跃载体、换载体、按名开载体。

本文件钉五件事：

- **判据是形状**：`<hub>/packs/` 才算 hub；`packs/` 里混着别的东西即报错；
- **读路径不建东西**：目录不在就报错，不悄悄建一个空的顶上；
- **选地方**：活跃载体 = **有空间的最满者**；一份都没有才新开；
- **换载体**：写到封口线就换下一份，而**单条记录大于封口线照样整条写入**；
- **hub 自己不写字节**：它只选地方，写是 pack 的事。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from core.exc import HubNotFoundError, HubShapeError
from core.storage.db.id import ID
from core.storage.hub import PACKS_DIRNAME, Hub, find_hubs
from core.storage.pack import HEADER_SIZE

if TYPE_CHECKING:
    from pathlib import Path

_SLOT = 512


def _id(name: str = "notedata") -> ID:
    """一条记录的身份：名字与凭证都由调用方给，内核不代签。"""
    return ID.unbound(name=name)


def _capacity(records: int) -> int:
    """一份载体封口前的容量：头 + `records` 格。

    `records` 就是这个函数的意思：**占满格时放够这么多条，这份就封口**。
    判据是"剩下的地方装不下下一格"（`长度 + 格长 > 封口线`），而这条容量恰好让它成立——
    写满第 `records` 条之后，再加一格就超额了。
    """
    return HEADER_SIZE + records * _SLOT


def _hub(tmp_path: Path, *, records: int = 1) -> Hub:
    """建一个可写的小 hub：`records` 是"占满格时能放几条"，默认一条。"""
    return Hub.create(tmp_path / "main", slot_bytes=_SLOT, max_bytes=_capacity(records))


# ---- 建立与形状 ----


def test_create_makes_the_packs_directory(tmp_path: Path):
    """建立 hub 只做一件事：造出 `packs/`。**它不预建载体**——空 hub 不该有一份空载体。"""
    hub = _hub(tmp_path)

    assert hub.packs_dir.is_dir()
    assert hub.pack_names() == ()


def test_create_is_idempotent(tmp_path: Path):
    """重复建立不出错，也不会多造东西。"""
    Hub.create(tmp_path / "main").append(_id(), b"hello")

    second = Hub.create(tmp_path / "main")

    assert len(second.pack_names()) == 1


def test_opening_a_missing_hub_reports_it(tmp_path: Path):
    """读路径不建东西：目录不在即报错。"""
    with pytest.raises(HubNotFoundError, match="不在"):
        Hub.open(tmp_path / "nope")


def test_a_plain_directory_is_not_a_hub(tmp_path: Path):
    """**判据是形状**：没有 `packs/` 的目录不算 hub——不把看不懂的东西当成 hub。"""
    (tmp_path / "stray").mkdir()
    with pytest.raises(HubShapeError, match="不是 hub"):
        Hub.open(tmp_path / "stray")


def test_the_hub_name_is_its_directory_name(tmp_path: Path):
    """Hub 名就是目录名：**它不持有身份**，标识即名字。"""
    assert _hub(tmp_path).name == "main"


def test_a_new_pack_carries_the_hub_s_policy(tmp_path: Path):
    """新载体照 hub 当前的策略建：格长与**封口线**都交给它。

    封口线一项漏传时，`sealed` 会拿默认值（2 GiB）判，而配置里写的小数**看起来生效、
    实际没有**——这条钉的正是"配置真的落地了"。
    """
    hub = _hub(tmp_path, records=3)

    pack = hub.new_pack()

    assert pack.max_bytes == _capacity(3)
    assert pack.layout().slot == _SLOT


def test_a_stray_file_inside_packs_is_refused(tmp_path: Path):
    """`packs/` 里混着不是载体的东西即报错，不静默跳过——跳过的策略属于巡检，不属于本层。"""
    hub = _hub(tmp_path)
    (hub.packs_dir / "not-a-pack").write_bytes(b"junk")

    with pytest.raises(HubShapeError, match="混着"):
        hub.pack_names()


def test_a_subdirectory_inside_packs_is_refused(tmp_path: Path):
    """载体是文件，故 `packs/` 里的子目录同样不合格。"""
    hub = _hub(tmp_path)
    (hub.packs_dir / "nested").mkdir()

    with pytest.raises(HubShapeError, match="混着目录"):
        hub.pack_names()


# ---- 选地方 ----


def test_the_first_write_opens_exactly_one_pack(tmp_path: Path):
    """第一次写入时才有载体：写之前一个都没有。"""
    hub = _hub(tmp_path)
    assert hub.active() is None

    record = hub.append(_id(), b"hello")

    assert len(hub.pack_names()) == 1
    assert record.span.first == 0


def test_appends_land_in_the_same_pack_while_it_has_room(tmp_path: Path):
    """同一份载体还有空间就一直用它：写入纪律是"写到满才换"。"""
    hub = _hub(tmp_path, records=3)
    first = hub.append(_id(), b"a")
    second = hub.append(_id(), b"b")

    assert len(hub.pack_names()) == 1, "两条小记录落在同一份里"
    assert first.span.first == 0
    assert second.span.first == 1, "第二条从上一条占满的格之后开始"


def test_a_full_pack_is_sealed_and_the_next_write_opens_a_new_one(tmp_path: Path):
    """写到封口线就换下一份：封口线只管"换不换文件"。

    **不手算格数**：按实测的字节数推——只要"这一份已经装不下下一格了"，
    下一次写入就必须另开一份。
    """
    hub = _hub(tmp_path, records=1)
    hub.append(_id(), b"x" * 400)  # 第一条：占满这一份
    before = hub.pack(hub.pack_names()[0])

    second = hub.append(_id(), b"y" * 10)

    assert before.sealed, "第一份此后装不下任何一格"
    assert len(hub.pack_names()) == 2
    assert second.span.first == 0, "第二条落在新开的那一份的头上"


def test_a_record_larger_than_the_seal_line_is_written_whole(tmp_path: Path):
    """单条记录大于封口线照样整条写入——否则大记录永远写不进去。"""
    hub = _hub(tmp_path)
    record = hub.append(_id(), b"z" * 4096)

    assert len(hub.pack_names()) == 1
    assert record.span.size > 1
    assert hub.pack(hub.pack_names()[0]).size > _capacity(1), "写下了比封口线还长的一段"


def test_the_active_pack_is_the_fullest_one_with_room(tmp_path: Path):
    """活跃载体 = **有空间的最满者**：判据不依赖时间戳，也不依赖载体名的顺序。"""
    hub = _hub(tmp_path, records=2)
    hub.append(_id(), b"a" * 1400)  # 一份装得下两条这样的
    hub.append(_id(), b"b" * 1400)
    hub.append(_id(), b"c")  # 这份满了，换下一份

    active = hub.active()
    unsealed = [pack for pack in hub.packs() if not pack.sealed]

    assert active is not None
    assert not active.sealed, "活跃载体必须是还有空间的"
    assert active.size == max(pack.size for pack in unsealed), "有空间的里面它最满"
    assert len(unsealed) < len(hub.pack_names()), "确实存在已封口的载体"


def test_appends_keep_going_into_the_newest_pack(tmp_path: Path):
    """换到新载体之后，后续写入落在新载体里，旧的那份不再被碰。"""
    hub = _hub(tmp_path, records=2)
    hub.append(_id(), b"x" * 400)  # 第一格
    hub.append(_id(), b"y" * 400)  # 第二格：这份满了
    third = hub.append(_id(), b"z" * 10)  # 换下一份

    assert len(hub.pack_names()) == 2
    assert third.span.first == 0, "第三条落在那份新开的载体头上"


# ---- 读侧 ----


def test_a_pack_can_be_opened_by_name(tmp_path: Path):
    """按名字取载体：**名字就是文件的名字**，也是身份里 `in_hub_pack` 那一项。"""
    hub = _hub(tmp_path)
    record = hub.append(_id("notedata"), b"payload")
    name = hub.pack_names()[0]

    pack = hub.pack(name)
    restored = pack.read(record.span)

    assert pack.name == name
    assert restored.payload == b"payload"
    assert restored.identity.value_uuid == record.identity.value_uuid


def test_opening_an_unknown_pack_name_reports_it(tmp_path: Path):
    """点名一个不存在的载体即报错，不猜也不新造一份。"""
    with pytest.raises(HubNotFoundError, match="载体不在"):
        _hub(tmp_path).pack("nobody")


def test_packs_can_be_walked_for_a_full_scan(tmp_path: Path):
    """`packs()` 逐个打开全部载体——**这就是顺扫的入口**。

    顺序按载体名（随机串）排，故两条记录落在同一份里时，读写次序一致。
    """
    hub = _hub(tmp_path, records=3)
    hub.append(_id(), b"a" * 400)
    hub.append(_id(), b"b" * 400)
    assert len(hub.pack_names()) == 1, "两条记录落在同一份里"

    payloads = [record.payload for pack in hub.packs() for record in pack.scan()]

    assert payloads == [b"a" * 400, b"b" * 400]


# ---- 库根下的多个 hub ----


def test_find_hubs_takes_only_directories_shaped_like_a_hub(tmp_path: Path):
    """在库根下按形状找 hub：库根还会有别的东西，见目录就当 hub 会把它们卷进来。"""
    Hub.create(tmp_path / "main")
    Hub.create(tmp_path / "archive")
    (tmp_path / "catalog.db").write_bytes(b"")
    (tmp_path / "stray").mkdir()

    assert [hub.name for hub in find_hubs(tmp_path)] == ["archive", "main"]


def test_find_hubs_on_a_missing_root_finds_nothing(tmp_path: Path):
    """库根不在时返回空：只找不建，也不报错——"没有 hub"与"库根不在"由调用方分。"""
    assert find_hubs(tmp_path / "nope") == ()


def test_the_packs_dir_name_is_the_shape_judgement():
    """形状判据只有一条：这个常量所指的子目录在不在。"""
    assert PACKS_DIRNAME == "packs"

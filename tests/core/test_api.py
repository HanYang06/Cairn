# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""命令面契约：方法表、参数校验，以及它交出来的东西**确实落在 JSON 域里**。

这一层是**传输无关**的，所以测试也不需要任何 stdio——帧协议在 `app/` 那一侧。
本文件钉四件事：

- **方法表就是入口清单**：不认识的名字当场报错，并把有的报出来；
- **结果只有四种东西**：身份、位置、计数、记录原文（base64）。故这里逐条检查它们的形状；
- **写不由命令面发起**：块自己 `save()`，命令面是读与诊断（删除除外）；
- **库是投影**：库里没有那一行时按分配形态退回顺扫，不该把"缺一行"当成"块不存在"。
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

import pytest

from core.api import Api
from core.exc import InvalidParamsError, ObjectNotFoundError, UnknownMethodError
from core.init import Kernel
from core.storage.db.id import ID
from core.storage.db.payload import decode_block
from core.storage.engine import Block
from core.storage.types import Attr, Body

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class Memo(Block):
    """命令面用例用的最小块：一个可索引属性，外加一段内容。"""

    title: str = Attr("")  # type: ignore[assignment]
    lines: list[str] = Body([])  # type: ignore[assignment]


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Api]:
    """一个接了临时库的命令面（内核关掉时那根线自动解开）。"""
    with Kernel.create(tmp_path / "vault") as kernel:
        yield Api(kernel)


def _stored() -> Memo:
    """造一个填好的块并存进去。"""
    memo = Memo(ID(Memo))
    memo.title = "标题"
    memo.lines = ["第一行"]
    memo.save()
    return memo


# ---- 方法表 ----


def test_methods_lists_the_surface(api: Api):
    """表上有哪些方法是可问的，且顺序确定。"""
    assert set(api.methods) == {"delete", "hubs", "locate", "record", "rows", "stats", "tables"}
    assert api.methods == tuple(sorted(api.methods))


def test_unknown_method_is_refused(api: Api):
    """不认识的方法名当场报错，顺带把有的报出来。"""
    with pytest.raises(UnknownMethodError, match="没有这个方法"):
        api.call("没有这个方法")


# ---- 读与诊断 ----


def test_tables_lists_the_identity_tables(api: Api):
    """库里有哪些身份表：用了 ID 的类型各有一张，而库自用的那两张不算。"""
    _stored()

    listed = api.call("tables")

    assert isinstance(listed, dict)
    tables = listed["tables"]
    assert isinstance(tables, list)
    assert "memo" in tables, "存过的类型必有它那张表"
    assert "hub" not in tables
    assert "meta" not in tables


def test_rows_gives_the_place_of_each_identity(api: Api):
    """一行身份就是"这个身份在哪儿"：位置段由引擎写完回填，故四段都该有值。"""
    memo = _stored()

    listed = api.call("rows", {"table": "memo"})

    assert isinstance(listed, dict)
    rows = listed["rows"]
    assert isinstance(rows, list)
    assert [row["uuid"] for row in rows] == [memo.id.value_uuid]
    row = rows[0]
    assert row["name"] == "memo"
    assert row["hash"] == memo.id.value_hash
    assert row["hub"] == "main"
    assert row["pack"], "载体名是随机串，但不该为空"
    assert row["last"] >= row["first"] >= 0


def test_locate_finds_where_a_block_lives(api: Api):
    """按身份找位置：逐张身份表找那一行，交出它在哪张表与哪个坐标。"""
    memo = _stored()

    found = api.call("locate", {"uuid": memo.id.value_uuid})

    assert isinstance(found, dict)
    assert found["table"] == "memo"
    assert found["uuid"] == memo.id.value_uuid
    assert found["hub"] == "main"


def test_locate_says_nothing_for_an_unknown_identity(api: Api):
    """不认识的 uuid 不是错：找不到就是找不到。"""
    assert api.call("locate", {"uuid": "没有这个块"}) is None


def test_record_returns_the_payload_verbatim(api: Api):
    """记录原文是 base64 的字节：解回来还是那条块记录，摘要也对得上。"""
    memo = _stored()

    found = api.call("record", {"uuid": memo.id.value_uuid})

    assert isinstance(found, dict)
    raw = base64.b64decode(str(found["payload"]))
    assert decode_block(raw) is not None, "交出来的必须是一条块记录"
    assert found["hash"] == memo.id.value_hash
    assert found["first"] <= found["last"]


def test_record_of_an_unknown_identity_is_refused(api: Api):
    """取不出来的东西就报"不在"，不交一个空壳回去。"""
    with pytest.raises(ObjectNotFoundError, match="块不在"):
        api.call("record", {"uuid": "没有这个块"})


def test_stats_counts_records_by_their_reserved_key(api: Api):
    """整库计数按保留键分四类，**数的是盘上的条数**：内容记录与块记录各算各的。"""
    memo = _stored()

    before = api.call("stats")
    assert isinstance(before, dict)
    assert before["blocks"] == 1
    assert before["contents"] == 1, "一份内容只写一条"
    assert before["indexes"] >= 1, "Attr 声明过的字段会写正表行"
    assert before["tombstones"] == 0
    assert before["records"] == (
        before["blocks"] + before["contents"] + before["indexes"] + before["tombstones"]
    )

    api.call("delete", {"uuid": memo.id.value_uuid})

    after = api.call("stats")
    assert isinstance(after, dict)
    assert after["tombstones"] == 1, "删除落一条墓碑"
    assert after["blocks"] == 1, "旧字节删不掉：这一条仍在盘上，等 GC 回收"


def test_delete_reports_whether_it_hit(api: Api):
    """删除报真假：第二次删同一个就是假。"""
    memo = _stored()

    assert api.call("delete", {"uuid": memo.id.value_uuid}) == {"deleted": True}
    assert api.call("delete", {"uuid": memo.id.value_uuid}) == {"deleted": False}


# ---- 参数校验：缺了、类型不对 ----


def test_missing_parameter_is_refused(api: Api):
    with pytest.raises(InvalidParamsError, match="uuid"):
        api.call("record", {})


def test_wrong_type_is_refused(api: Api):
    with pytest.raises(InvalidParamsError, match="uuid"):
        api.call("delete", {"uuid": 7})


def test_empty_parameter_is_refused(api: Api):
    """空串不是"随便找一个"：身份是必须给出的东西。"""
    with pytest.raises(InvalidParamsError, match="table"):
        api.call("rows", {"table": ""})


def test_kernel_errors_pass_through(api: Api):
    """内核自己抛的异常原样交给调用方：命令面不吞它、也不改名。"""
    with pytest.raises(ObjectNotFoundError):
        api.call("record", {"uuid": "没有这个块"})

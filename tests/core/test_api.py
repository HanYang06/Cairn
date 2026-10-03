# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""命令面契约:方法表,参数校验,以及它交出来的东西**确实落在 JSON 域里**.

这一层是**传输无关**的,所以测试也不需要任何 stdio——帧协议在 `app/` 那一侧.
本文件钉五件事:

- **方法表就是入口清单**:不认识的名字当场报错,并把有的报出来;
- **结果只有四种东西**:身份,位置,计数,槽的原文(base64).故这里逐条检查它们的形状;
- **位置段按段列表交出去**:不再切成"头格与末格"两半;
- **`stats` 里没有墓碑那一栏**:删除即摘掉库里那一行,载体上不留标记;
- **写不由命令面发起**:块自己 `save()`,命令面是读与诊断(删除除外).
"""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING

import pytest

from core.api import Api
from core.exc import InvalidParamsError, ObjectNotFoundError, UnknownMethodError
from core.init import Kernel
from core.storage.db.id import ID
from core.storage.engine import Block
from core.storage.types import Attr, Body

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class Memo(Block):
    """命令面用例用的最小块:一个可索引属性,外加一段正文."""

    title: str = Attr("")  # type: ignore[assignment]
    lines: list[str] = Body([])  # type: ignore[assignment]


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Api]:
    """一个接了临时库的命令面(内核关掉时那根线自动解开)."""
    with Kernel.create(tmp_path / "vault") as kernel:
        yield Api(kernel)


def _stored() -> Memo:
    """造一个填好的块并存进去."""
    memo = Memo(ID(Memo))
    memo.title = "标题"
    memo.lines = ["第一行"]
    memo.save()
    return memo


# ---- 方法表 ----


def test_methods_lists_the_surface(api: Api):
    """表上有哪些方法是可问的,且顺序确定."""
    assert set(api.methods) == {"delete", "hubs", "locate", "record", "rows", "stats", "tables"}
    assert api.methods == tuple(sorted(api.methods))


def test_unknown_method_is_refused(api: Api):
    """不认识的方法名当场报错,顺带把有的报出来."""
    with pytest.raises(UnknownMethodError, match="没有这个方法"):
        api.call("没有这个方法")


def test_a_call_without_params_is_taken_as_an_empty_mapping(api: Api):
    """参数不给即当空映射:`tables` 一类没有参数的方法照旧可用."""
    assert api.call("tables") == api.call("tables", {})


# ---- 读与诊断 ----


def test_tables_lists_the_identity_tables(api: Api):
    """库里有哪些身份表:用了 ID 的类型各有一张,而库自用的那两张不算."""
    _stored()

    listed = api.call("tables")

    assert isinstance(listed, dict)
    tables = listed["tables"]
    assert isinstance(tables, list)
    assert "memo" in tables, "存过的类型必有它那张表"
    assert "hub" not in tables
    assert "meta" not in tables


def test_rows_gives_the_place_of_each_identity(api: Api):
    """一行身份就是"这个身份在哪儿,它的正文是哪一份,经过哪几代":位置段按**段列表**交出来."""
    memo = _stored()

    listed = api.call("rows", {"table": "memo"})

    assert isinstance(listed, dict)
    rows = listed["rows"]
    assert isinstance(rows, list)
    assert [row["uuid"] for row in rows] == [memo.id.value_uuid]
    row = rows[0]
    assert row["name"] == "memo"
    assert row["hub"] == "main"
    assert row["pack"], "载体名是随机串，但不该为空"
    assert row["segments"], "位置段是段列表的文本写法"
    assert row["slots"], "另给一份展开之后的槽号"
    assert json.loads(str(row["history"])) == memo.id.body_history, "摘要链原样交出来"
    assert "attr_slots" not in row, "哪几格是属性槽由槽头回答，库里不再有那一列"
    assert "hash" not in row, "摘要形态已移出身份"


def test_a_row_carries_no_tombstone_column(api: Api):
    """**库里没有墓碑那一栏**:删除即摘掉那一行,载体上不留标记."""
    memo = _stored()

    listed = api.call("rows", {"table": "memo"})

    assert isinstance(listed, dict)
    row = listed["rows"][0]
    for gone in ("tombstone", "value_hash", "deleted"):
        assert gone not in row
    assert row["uuid"] == memo.id.value_uuid


def test_locate_finds_where_a_block_lives(api: Api):
    """按身份找位置:逐张身份表找那一行,交出它在哪张表与哪个坐标."""
    memo = _stored()

    found = api.call("locate", {"uuid": memo.id.value_uuid})

    assert isinstance(found, dict)
    assert found["table"] == "memo"
    assert found["uuid"] == memo.id.value_uuid
    assert found["hub"] == "main"


def test_locate_says_nothing_for_an_unknown_identity(api: Api):
    """不认识的 uuid 不是错:找不到就是找不到."""
    assert api.call("locate", {"uuid": "没有这个块"}) is None


def test_record_returns_the_raw_slots(api: Api):
    """`record` 的字面意思:**读出该块各槽的原文**(base64),逐格交出."""
    memo = _stored()

    found = api.call("record", {"uuid": memo.id.value_uuid})

    assert isinstance(found, dict)
    assert found["uuid"] == memo.id.value_uuid
    assert found["hub"] == "main"
    slots = found["slots"]
    assert isinstance(slots, list)
    assert len(slots) == 2, "属性槽一格、正文槽一格"
    kinds = {entry["kind"] for entry in slots}
    assert kinds == {"属性槽", "正文槽"}
    for entry in slots:
        raw = base64.b64decode(str(entry["content"]))
        assert entry["length"] == len(raw)
        assert raw, "原文不是空的"


def test_record_separates_the_attributes_from_the_body(api: Api):
    """原文里分得清哪一格是属性,哪一格是正文——判据只在槽头上."""
    memo = _stored()

    found = api.call("record", {"uuid": memo.id.value_uuid})

    assert isinstance(found, dict)
    slots = found["slots"]
    assert isinstance(slots, list)
    kinds = {entry["kind"] for entry in slots}
    assert kinds == {"属性槽", "正文槽"}


def test_record_of_an_unknown_identity_is_refused(api: Api):
    """取不出来的东西就报"不在",不交一个空壳回去."""
    with pytest.raises(ObjectNotFoundError, match="对象不在"):
        api.call("record", {"uuid": "没有这个块"})


def test_stats_counts_slots_by_their_kind(api: Api):
    """整库计数按**槽的种类**数:属性槽,正文槽,没写过的格,各算各的."""
    _stored()

    counted = api.call("stats")

    assert isinstance(counted, dict)
    assert counted["attrs"] >= 1, "这个块有属性槽，索引块的正表行也落在属性槽上"
    assert counted["bodies"] == 1, "一份正文只写一格"
    assert counted["rows"] >= 1, "库里至少有一行身份"
    assert counted["hubs"] == 1
    assert "tombstones" not in counted, "没有墓碑那一栏"
    assert counted["slots"] == counted["attrs"] + counted["bodies"] + counted["empty"]


def test_delete_reports_whether_it_hit(api: Api):
    """删除报真假:第二次删同一个就是假."""
    memo = _stored()

    assert api.call("delete", {"uuid": memo.id.value_uuid}) == {"deleted": True}
    assert api.call("delete", {"uuid": memo.id.value_uuid}) == {"deleted": False}


def test_delete_takes_the_row_away_without_touching_the_pack(api: Api):
    """删除只摘掉那一行:载体上不留标记,故 `stats` 的槽数一个都不变."""
    memo = _stored()
    before = api.call("stats")

    api.call("delete", {"uuid": memo.id.value_uuid})

    after = api.call("stats")
    assert isinstance(before, dict)
    assert isinstance(after, dict)
    assert after["attrs"] == before["attrs"]
    assert after["bodies"] == before["bodies"]
    assert after["rows"] == before["rows"] - 1, "少的是库里那一行"


def test_hubs_lists_the_default_one(api: Api):
    """已登记的 hub 名:写一次就登记一个."""
    _stored()

    assert api.call("hubs") == {"hubs": ["main"]}


# ---- 参数校验:缺了,类型不对 ----


def test_missing_parameter_is_refused(api: Api):
    with pytest.raises(InvalidParamsError, match="uuid"):
        api.call("record", {})


def test_wrong_type_is_refused(api: Api):
    with pytest.raises(InvalidParamsError, match="uuid"):
        api.call("delete", {"uuid": 7})


def test_empty_parameter_is_refused(api: Api):
    """空串不是"随便找一个":身份是必须给出的东西."""
    with pytest.raises(InvalidParamsError, match="table"):
        api.call("rows", {"table": ""})


def test_kernel_errors_pass_through(api: Api):
    """内核自己抛的异常原样交给调用方:命令面不吞它,也不改名."""
    with pytest.raises(ObjectNotFoundError):
        api.call("record", {"uuid": "没有这个块"})


def test_the_result_stays_inside_json(api: Api):
    """结果必须落在 JSON 域里:交出来的每一层都是映射,列表,字符串或数字."""
    _stored()

    for method in ("tables", "hubs", "stats"):
        assert json.loads(json.dumps(api.call(method))) is not None
    assert json.loads(json.dumps(api.call("rows", {"table": "memo"}))) is not None

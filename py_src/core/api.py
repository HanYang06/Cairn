# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""内核命令面:把内核的动作定成一张表,供边车 / CLI / 测试调用.

它**传输无关**:这里只有"方法名 → 参数 → 结果",没有 socket,没有 stdio,没有 JSON.
接线(长度头分帧,序列化,子进程)在 `py_src/app/` 那一侧;壳只做转发,**不许认识领域字段**.

**结果必须落在 JSON 域里**:映射,列表,字符串,数字,布尔与空值.故这一面只交出
四样东西——**身份,位置,计数,槽的原文(base64)**.它**不解领域载荷**:把载荷解成
领域结构是领域格式层(`model/note/format/`)的活,尚未落地,这里就不假装解得出.

**这一面是读与诊断**.写由领域块自己发起(`note.save()`),不能因为命令面里放一个
`store` 就绕过领域——那样"谁决定落点"这条就断了.删除是例外:它是整库动作,落在这里.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from core.exc import InvalidParamsError, ObjectNotFoundError, UnknownMethodError
from core.storage.db.id import BODY_HISTORY_FIELD, ID
from core.storage.pack import ATTR_SLOT, Slot

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from core.init import Kernel

#: 库自己的几张表:它们不是身份表,列举类型与统计时都不该混进去.
_RESERVED_TABLES = frozenset({"hub", "meta"})


class Api:
    """命令面:一个已装配的内核,加一张"方法名 → 处理器"的表."""

    def __init__(self, kernel: Kernel) -> None:
        """接上一个已装配的内核."""
        self._kernel = kernel

    @property
    def kernel(self) -> Kernel:
        """命令面背后的内核."""
        return self._kernel

    @property
    def methods(self) -> tuple[str, ...]:
        """这张表上有哪些方法(按名字排序)——调试与文档用."""
        return tuple(sorted(_METHODS))

    def call(self, method: str, params: Mapping[str, object] | None = None) -> object:
        """派一次调用;参数不给即当空映射.

        Raises:
            UnknownMethodError: 方法名不在表里.
            InvalidParamsError: 参数缺了,多了或类型不对.
            CairnError: 内核自己抛的那一族,原样交给调用方.
        """
        handler = _METHODS.get(method)
        if handler is None:
            raise UnknownMethodError(f"命令面没有这个方法: {method!r}（有的是 {self.methods}）")
        return handler(self, {} if params is None else params)


# ---- 方法实现:每个都只做"读参数 → 问内核 → 折成 JSON" ---- #


def _tables(api: Api, _params: Mapping[str, object]) -> dict[str, object]:
    """库里有哪几张身份表:**用了 ID 的类型各有一张**,按名字排序."""
    return {
        "tables": [
            name for name in api.kernel.engine.index.tables() if name not in _RESERVED_TABLES
        ]
    }


def _hubs(api: Api, _params: Mapping[str, object]) -> dict[str, object]:
    """已登记的 hub 名:登记是库的一列,真源是库根下那些目录."""
    return {"hubs": list(api.kernel.engine.index.hubs())}


def _rows(api: Api, params: Mapping[str, object]) -> dict[str, object]:
    """某个类型的身份行:一行是"这个身份在哪儿,它的正文是哪一份,经过哪几代".

    **表名由参数给**,不由命令面去猜:库是一个类型一张表,故"查哪张"这一问只能由
    调用方回答——它知道自己要什么类型.
    """
    table = _text(params, "table")
    return {"rows": [_row(row) for row in api.kernel.engine.index.rows(table)]}


def _locate(api: Api, params: Mapping[str, object]) -> object:
    """按身份找位置:**逐张身份表找那一行**,返回它在哪张表,哪个 hub / 载体 / 段列表.

    找不到即 ``None``——"没有这个身份"不是错误.
    """
    value_uuid = _text(params, "uuid")
    found = _catalog_row(api, value_uuid)
    if found is None:
        return None
    table, row = found
    return _row(row) | {"table": table}


def _record(api: Api, params: Mapping[str, object]) -> dict[str, object]:
    """**读出该块各槽的原文**(base64):属性槽与正文槽逐格交出,不解释,不降级.

    这条是刻意留的"最低限度可读":领域载荷解不成 JSON,而诊断与调试恰恰需要看到原始字节.
    槽的种类与内容长度一并交出,故调用方据此分清哪几格是属性,哪几格是正文.

    Raises:
        ObjectNotFoundError: 库里没有这个身份,或它指着的那一格读不出来.
    """
    value_uuid = _text(params, "uuid")
    identity = _identity(api, value_uuid)
    row = api.kernel.engine.index_row(identity)
    held = api.kernel.engine.scan_slots(identity)
    return {
        "uuid": identity.value_uuid,
        "name": identity.name,
        "hub": str(row.get("in_hub") or ""),
        "pack": str(row.get("in_hub_pack") or ""),
        "segments": str(row.get("in_pack_slot") or ""),
        "history": str(row.get(BODY_HISTORY_FIELD) or ""),
        "slots": [
            _slot(index, slot, str(row.get("in_hub_pack") or "")) for index, slot in enumerate(held)
        ],
    }


def _stats(api: Api, _params: Mapping[str, object]) -> dict[str, object]:
    """整库的**计数**:顺扫一遍,按槽的种类数.

    **数的是盘上的格数,不判死活**:载体是追加写,被删掉的那些槽仍在盘上,
    要等回收才收走——故这里的数不小于"库里那些行指着"的数.

    **没有墓碑那一栏**:删除即摘掉索引库那一行,载体上不留标记.
    """
    attrs = bodies = empty = 0
    for _hub, _pack, _number, slot in api.kernel.engine.scan():
        if not slot.kind:
            empty += 1
        elif slot.kind == ATTR_SLOT:
            attrs += 1
        else:
            bodies += 1
    return {
        "slots": attrs + bodies + empty,
        "attrs": attrs,
        "bodies": bodies,
        "empty": empty,
        "rows": _row_count(api),
        "hubs": len(api.kernel.engine.index.hubs()),
    }


def _delete(api: Api, params: Mapping[str, object]) -> dict[str, object]:
    """摘掉一个块:返回是否确实摘掉了一个.

    载体是追加写,旧字节删不掉——删除的落法是**摘掉库里那一行**,空间等回收收敛.
    故"删掉"是**语义上不再存在**,不是字节消失.

    **没有那一行不是错**:删两次时第二次就是没有可删的东西,报假即可——
    与"删掉了一个"这件事对不上号的是"它到底删没删",不是"它原先在不在".
    """
    value_uuid = _text(params, "uuid")
    found = _catalog_row(api, value_uuid)
    if found is None:
        return {"deleted": False}
    _table, row = found
    return {"deleted": api.kernel.engine.delete(ID.from_row(row))}


#: 命令面那张表:方法名 → 处理器.**它是唯一的入口清单**,加方法只改这里.
_METHODS: Mapping[str, Callable[[Api, Mapping[str, object]], object]] = {
    "delete": _delete,
    "hubs": _hubs,
    "locate": _locate,
    "record": _record,
    "rows": _rows,
    "stats": _stats,
    "tables": _tables,
}


# ---- 内部:身份还原与行折形 ---- #


def _catalog_row(api: Api, value_uuid: str) -> tuple[str, dict[str, object]] | None:
    """逐张身份表找这个 uuid 的那一行;没有即 ``None``."""
    index = api.kernel.engine.index
    for table in index.tables():
        if table in _RESERVED_TABLES:
            continue
        row = index.get(table, value_uuid)
        if row is not None:
            return table, row
    return None


def _identity(api: Api, value_uuid: str) -> ID:
    """由库里的那一行还原身份:**身份,位置段与正文历史一起读回**.

    **库里没有这一行即报错**:索引库是权威视角,缺一行就是"这个块不存在",
    没有顺扫这条退路.
    """
    found = _catalog_row(api, value_uuid)
    if found is None:
        raise ObjectNotFoundError(f"对象不在: {value_uuid}")
    _table, row = found
    return ID.from_row(row)


def _row(row: Mapping[str, object]) -> dict[str, object]:
    """把一行身份折成 JSON:**位置段按段列表交出去**,正文摘要链另给一份.

    **没有 `attr_slots` 那一栏**(2026-10-02 修正裁定):哪几格是属性槽由载体的槽头回答,
    库里不再有那一列.要分拣就读槽头——`:meth:`record` 交出的每一格都带着槽种类.
    """
    return {
        "uuid": str(row.get("value_uuid") or ""),
        "name": str(row.get("name") or ""),
        "birth_time": str(row.get("birth_time") or ""),
        "hub": str(row.get("in_hub") or ""),
        "pack": str(row.get("in_hub_pack") or ""),
        "segments": str(row.get("in_pack_slot") or ""),
        "slots": list(_slot_numbers(str(row.get("in_pack_slot") or ""))),
        "history": str(row.get(BODY_HISTORY_FIELD) or ""),
    }


def _slot_numbers(text: str) -> tuple[int, ...]:
    """把段列表文本展开成升序的一串槽号(命令面按格号交出去)."""
    found: list[int] = []
    for part in text.split(","):
        item = part.strip()
        if not item:
            continue
        head, sep, tail = item.partition("-")
        if not sep:
            found.append(int(head))
            continue
        found.extend(range(int(head), int(tail) + 1))
    return tuple(found)


def _slot(index: int, slot: Slot, pack: str) -> dict[str, object]:
    """把一格折成 JSON:**槽号,槽种类与内容原文**."""
    return {
        "slot": index,
        "kind": slot.kind_name,
        "pack": pack,
        "length": len(slot.content),
        "content": _as_base64(slot.content),
    }


def _row_count(api: Api) -> int:
    """库里身份行的总条数(不含 `hub` 与 `meta`)."""
    index = api.kernel.engine.index
    total = 0
    for table in index.tables():
        if table in _RESERVED_TABLES:
            continue
        total += sum(1 for _row_item in index.rows(table))
    return total


# ---- 参数读取:缺了或类型不对就报错,不猜 ---- #


def _text(params: Mapping[str, object], key: str) -> str:
    """取一个必需的字符串参数."""
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise InvalidParamsError(f"参数 {key} 必须是非空字符串: {value!r}")
    return value


def _as_base64(data: bytes) -> str:
    """把二进制折成能进 JSON 的写法."""
    return base64.b64encode(data).decode("ascii")


__all__ = ["Api"]

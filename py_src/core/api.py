# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""内核命令面：把内核的动作定成一张表，供边车 / CLI / 测试调用。

它**传输无关**：这里只有"方法名 → 参数 → 结果"，没有 socket、没有 stdio、没有 JSON。
接线（长度头分帧、序列化、子进程）在 `py_src/app/` 那一侧；壳只做转发，**不许认识领域字段**。

**结果必须落在 JSON 域里**：映射、列表、字符串、数字、布尔与空值。故这一面只交出
四样东西——**身份、位置、计数、记录的原文（base64）**。它**不解领域载荷**：把载荷解成
领域结构是领域格式层（`model/note/format/`）的活，尚未落地，这里就不假装解得出。

**这一面是读与诊断**。写由领域块自己发起（`note.save()`），不能因为命令面里放一个
`store` 就绕过领域——那样"谁决定落点"这条就断了。删除是例外：它是整库动作，落在这里。
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from core.exc import InvalidParamsError, ObjectNotFoundError, UnknownMethodError
from core.storage.db.payload import decode_block, decode_index, decode_tombstone

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from core.init import Kernel
    from core.storage.db.id import ID

#: 库自己的几张表：它们不是身份表，列举类型与统计时都不该混进去。
_RESERVED_TABLES = frozenset({"hub", "meta"})


class Api:
    """命令面：一个已装配的内核，加一张"方法名 → 处理器"的表。"""

    def __init__(self, kernel: Kernel) -> None:
        """接上一个已装配的内核。"""
        self._kernel = kernel

    @property
    def kernel(self) -> Kernel:
        """命令面背后的内核。"""
        return self._kernel

    @property
    def methods(self) -> tuple[str, ...]:
        """这张表上有哪些方法（按名字排序）——调试与文档用。"""
        return tuple(sorted(_METHODS))

    def call(self, method: str, params: Mapping[str, object] | None = None) -> object:
        """派一次调用；参数不给即当空映射。

        Raises:
            UnknownMethodError: 方法名不在表里。
            InvalidParamsError: 参数缺了、多了或类型不对。
            CairnError: 内核自己抛的那一族，原样交给调用方。
        """
        handler = _METHODS.get(method)
        if handler is None:
            raise UnknownMethodError(f"命令面没有这个方法: {method!r}（有的是 {self.methods}）")
        return handler(self, {} if params is None else params)


# ---- 方法实现：每个都只做"读参数 → 问内核 → 折成 JSON" ----


def _tables(api: Api, _params: Mapping[str, object]) -> dict[str, object]:
    """库里有哪几张身份表：**用了 ID 的类型各有一张**，按名字排序。"""
    return {
        "tables": [
            name for name in api.kernel.engine.index.tables() if name not in _RESERVED_TABLES
        ]
    }


def _hubs(api: Api, _params: Mapping[str, object]) -> dict[str, object]:
    """已登记的 hub 名：登记是投影，真源是库根下那些目录。"""
    return {"hubs": list(api.kernel.engine.index.hubs())}


def _rows(api: Api, params: Mapping[str, object]) -> dict[str, object]:
    """某个类型的身份行：一行是"这个身份在哪儿"。

    **表名由参数给**，不由命令面去猜：库是一个类型一张表，故"查哪张"这一问只能由
    调用方回答——它知道自己要什么类型。
    """
    table = _text(params, "table")
    return {"rows": [_row(row) for row in api.kernel.engine.index.rows(table)]}


def _locate(api: Api, params: Mapping[str, object]) -> object:
    """按身份找位置：**逐张身份表找那一行**，返回它在哪张表、哪个 hub / 载体 / 格区间。

    位置本来就是投影，故这一问的答案随时能由顺扫重算；这里只是走索引那条快路。
    找不到即 ``None``。
    """
    value_uuid = _text(params, "uuid")
    found = _catalog_row(api, value_uuid)
    if found is None:
        return None
    table, row = found
    return _row(row) | {"table": table}


def _record(api: Api, params: Mapping[str, object]) -> dict[str, object]:
    """块记录的**载荷原文**（base64）：不解释、不降级，解它的人自己知道那是什么。

    这条是刻意留的"最低限度可读"：领域载荷解不成 JSON，而诊断与调试恰恰需要看到
    原始字节。它顺带把身份两套凭证交回去，调用方据此核对"读到的确实是这一份"。

    Raises:
        ObjectNotFoundError: 盘上没有这个身份的块记录。
    """
    identity = _identity(api, _text(params, "uuid"))
    found = api.kernel.engine.find_block(identity)
    if found is None:
        raise ObjectNotFoundError(f"块不在: {identity.value_uuid}")
    hub, pack, span, payload = found
    return {
        "uuid": identity.value_uuid,
        "hub": hub,
        "pack": pack,
        "first": span.first,
        "last": span.last,
        "hash": identity.value_hash,
        "payload": _as_base64(payload),
    }


def _stats(api: Api, _params: Mapping[str, object]) -> dict[str, object]:
    """整库的**计数**：顺扫一遍，按载荷把记录分成四类。

    **数的是盘上的条数，不判死活**：载体是追加写，被墓碑标记过的块记录仍在盘上，
    要等 GC 才回收——故 `tombstones` 与 `blocks` 会同时非零，那不是矛盾，是现状。
    它也**不吐记录本身**：整库记录随库体量无限增长，而这一面要交出 JSON 域里的值。

    四类各有自己的保留键，判据一起比——只比"不是块记录"会把索引条目也算进来。
    """
    records = blocks = contents = indexes = tombstones = 0
    for record in api.kernel.engine.scan():
        records += 1
        if decode_block(record.payload) is not None:
            blocks += 1
        elif decode_index(record.payload) is not None:
            indexes += 1
        elif decode_tombstone(record.payload) is not None:
            tombstones += 1
        else:
            contents += 1
    return {
        "records": records,
        "blocks": blocks,
        "contents": contents,
        "indexes": indexes,
        "tombstones": tombstones,
        "hubs": len(api.kernel.engine.index.hubs()),
    }


def _delete(api: Api, params: Mapping[str, object]) -> dict[str, object]:
    """摘掉一个块：返回是否确实摘掉了一个。

    载体是追加写，旧字节删不掉——删除的落法是一条墓碑（顺扫据此不再把它算数），
    空间等 GC 回收。故"删掉"是**语义上不再存在**，不是字节消失。
    """
    identity = _identity(api, _text(params, "uuid"))
    return {"deleted": api.kernel.engine.delete(identity)}


#: 命令面那张表：方法名 → 处理器。**它是唯一的入口清单**，加方法只改这里。
_METHODS: Mapping[str, Callable[[Api, Mapping[str, object]], object]] = {
    "delete": _delete,
    "hubs": _hubs,
    "locate": _locate,
    "record": _record,
    "rows": _rows,
    "stats": _stats,
    "tables": _tables,
}


# ---- 内部：身份还原与行折形 ----


def _catalog_row(api: Api, value_uuid: str) -> tuple[str, dict[str, object]] | None:
    """逐张身份表找这个 uuid 的那一行；没有即 ``None``。"""
    index = api.kernel.engine.index
    for table in index.tables():
        if table in _RESERVED_TABLES:
            continue
        row = index.get(table, value_uuid)
        if row is not None:
            return table, row
    return None


def _identity(api: Api, value_uuid: str) -> ID:
    """由库里的那一行还原身份：**整行照 `ID.from_record` 搬**，故两套凭证都在。

    库里没有这一行时退回"只有分配形态"的身份，让引擎顺扫去找——库是投影，
    缺一行不该等于"这个块不存在"（那时摘要也真的没人给出，故它为空）。
    """
    from core.storage.db.id import ID  # noqa: PLC0415 — 只在这一处用到，按需取

    found = _catalog_row(api, value_uuid)
    if found is None:
        return ID("", value_uuid=value_uuid)
    _table, row = found
    return ID.from_record(row)


def _row(row: Mapping[str, object]) -> dict[str, object]:
    """把一行身份折成 JSON：位置段落成两个数，其余照字符串交出去。"""
    return {
        "uuid": str(row.get("value_uuid") or ""),
        "name": str(row.get("name") or ""),
        "hash": str(row.get("value_hash") or ""),
        "birth_time": str(row.get("birth_time") or ""),
        "hub": str(row.get("in_hub") or ""),
        "pack": str(row.get("in_hub_pack") or ""),
        "first": _slot(row.get("in_pack_slot"), 0),
        "last": _slot(row.get("in_pack_slot"), 1),
    }


def _slot(value: object, offset: int) -> int:
    """取格区间的头 / 末格：库里落成 ``"头:末"``，读不回来即零。"""
    head, sep, tail = str(value or "").partition(":")
    if not sep:
        return 0
    try:
        return int((head, tail)[offset])
    except ValueError:
        return 0


# ---- 参数读取：缺了或类型不对就报错，不猜 ----


def _text(params: Mapping[str, object], key: str) -> str:
    """取一个必需的字符串参数。"""
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise InvalidParamsError(f"参数 {key} 必须是非空字符串: {value!r}")
    return value


def _as_base64(data: bytes) -> str:
    """把二进制折成能进 JSON 的写法。"""
    return base64.b64encode(data).decode("ascii")


__all__ = ["Api"]

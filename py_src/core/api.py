# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""内核命令面：把内核的动作定成一张表，供边车 / CLI / 测试调用。

它**传输无关**：这里只有"方法名 → 参数 → 结果"，没有 socket、没有 stdio、没有 JSON。
接线（长度头分帧、序列化、子进程）在 `py_src/app/` 那一侧；壳只做转发，**不许认识领域字段**。

**参数与结果都是 JSON 域里的值**：映射、列表、字符串、数字、布尔与空值。二进制（正文）
这一版走 base64——小载荷够用；**大正文的原始字节通道尚未接线**，故此处不假装它存在。

**速查表在这里缓存**：`query` 要一份倒排，而它可整份重算。`store` / `drop` / `repair`
之后缓存自动失效——它是纯派生物，丢了重建即可，不会与库分叉。

**UI 需求**：这些方法都跑在内核里，界面只经 IPC 调它们。其中 `patrol` / `repair` /
`survey` / `compact` / `reindex` 是**整库动作**，耗时随库体量增长，界面应放进后台线程
并给进度（`compact` 还能取消）。
"""

from __future__ import annotations

import base64
import binascii
from typing import TYPE_CHECKING

from core.exc import InvalidParamsError, UnknownMethodError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from core.init import Kernel
    from core.storage.attrindex import AttributeIndex


class Api:
    """命令面：一个内核，加一份随取随建的速查缓存。"""

    def __init__(self, kernel: Kernel) -> None:
        """接上一个已装配的内核。"""
        self._kernel = kernel
        self._table: AttributeIndex | None = None

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

    def attribute_index(self) -> AttributeIndex:
        """取速查表：没有就现建一份。它是派生物，随时可丢。"""
        if self._table is None:
            self._table = self._kernel.reindex()
        return self._table

    def reindex(self) -> AttributeIndex:
        """重建速查表并缓存它。"""
        self._table = self._kernel.reindex()
        return self._table

    def invalidate(self) -> None:
        """丢掉速查缓存：写路径之后调它，下次查询会自动重建。"""
        self._table = None


# ---- 方法实现：每个都只做"读参数 → 调内核 → 折成 JSON" ----


def _store(api: Api, params: Mapping[str, object]) -> dict[str, object]:
    identity = api.kernel.store(
        _bytes(params, "data"),
        kind=_optional_text(params, "kind") or "",
        attrs=_optional_mapping(params, "attrs"),
    )
    api.invalidate()
    return {"uuid": identity.value_uuid, "hash": identity.value_hash}


def _load(api: Api, params: Mapping[str, object]) -> dict[str, object]:
    return {"data": _as_base64(api.kernel.load(_text(params, "uuid")))}


def _drop(api: Api, params: Mapping[str, object]) -> dict[str, object]:
    dropped = api.kernel.drop(_text(params, "uuid"))
    if dropped:
        api.invalidate()
    return {"dropped": dropped}


def _locate(api: Api, params: Mapping[str, object]) -> object:
    row = api.kernel.locate(_text(params, "uuid"))
    if row is None:
        return None
    return {
        "hub": row.in_hub,
        "pack": row.in_hub_pack,
        "first": row.in_pack_slot[0],
        "last": row.in_pack_slot[1],
    }


def _payload(api: Api, params: Mapping[str, object]) -> object:
    parsed = api.kernel.storage.block_payload(_text(params, "uuid"))
    if parsed is None:
        return None
    return {
        "attrs": dict(parsed.attrs),
        "body_uuid": parsed.ref.value_uuid,
        "body_hash": parsed.ref.value_hash,
    }


def _blocks(api: Api, _params: Mapping[str, object]) -> dict[str, object]:
    return {
        "blocks": [
            {
                "uuid": row.value_uuid,
                "hash": row.value_hash,
                "kind": row.kind,
                "hub": row.in_hub,
                "pack": row.in_hub_pack,
                "first": row.in_pack_slot[0],
                "last": row.in_pack_slot[1],
            }
            for row in api.kernel.index.rows.blocks()
        ]
    }


def _query(api: Api, params: Mapping[str, object]) -> dict[str, object]:
    found = api.attribute_index().find(
        _text(params, "kind"), _text(params, "attribute"), _value(params)
    )
    return {"uuids": list(found)}


def _patrol(api: Api, _params: Mapping[str, object]) -> dict[str, object]:
    report = api.kernel.patrol()
    return {
        "clean": report.clean,
        "hubs_scanned": report.hubs_scanned,
        "records_scanned": report.records_scanned,
        "finds": [
            {
                "kind": item.kind.value,
                "hub": item.hub,
                "subject": item.subject,
                "detail": item.detail,
            }
            for item in report.finds
        ],
    }


def _repair(api: Api, _params: Mapping[str, object]) -> dict[str, object]:
    report = api.kernel.repair(api.kernel.patrol())
    api.invalidate()
    return {"applied": len(report.applied), "skipped": len(report.skipped)}


def _survey(api: Api, _params: Mapping[str, object]) -> dict[str, object]:
    report = api.kernel.survey()
    return {
        "waste_ratio": report.waste_ratio,
        "expected_ratio": report.expected_ratio,
        "live_records": report.live_records,
        "dead_records": report.dead_records,
        "bytes_to_read": report.bytes_to_read,
        "bytes_to_write": report.bytes_to_write,
        "packs_to_rewrite": report.packs_to_rewrite,
        "worth_it": report.worth_it,
    }


def _compact(api: Api, _params: Mapping[str, object]) -> dict[str, object]:
    report = api.kernel.compact()
    return {
        "reclaimed": report.reclaimed,
        "kept": report.kept,
        "dropped": report.dropped,
        "packs_before": report.packs_before,
        "packs_after": report.packs_after,
        "cancelled": report.cancelled,
    }


def _reindex(api: Api, _params: Mapping[str, object]) -> dict[str, object]:
    return {
        "attributes": [{"kind": kind, "attribute": name} for kind, name in api.reindex().attributes]
    }


#: 命令面那张表：方法名 → 处理器。**它是唯一的入口清单**，加方法只改这里。
_METHODS: Mapping[str, Callable[[Api, Mapping[str, object]], object]] = {
    "blocks": _blocks,
    "compact": _compact,
    "drop": _drop,
    "load": _load,
    "locate": _locate,
    "patrol": _patrol,
    "payload": _payload,
    "query": _query,
    "reindex": _reindex,
    "repair": _repair,
    "store": _store,
    "survey": _survey,
}


# ---- 参数读取：缺了或类型不对就报错，不猜 ----


def _text(params: Mapping[str, object], key: str) -> str:
    """取一个必需的字符串参数。"""
    value = params.get(key)
    if not isinstance(value, str):
        raise InvalidParamsError(f"参数 {key} 必须是字符串: {value!r}")
    return value


def _optional_text(params: Mapping[str, object], key: str) -> str | None:
    """取一个可选的字符串参数：没给即 `None`，给了但不是字符串即报错。"""
    value = params.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidParamsError(f"参数 {key} 必须是字符串: {value!r}")
    return value


def _optional_mapping(params: Mapping[str, object], key: str) -> Mapping[str, object] | None:
    """取一个可选的映射参数（块属性就是它）。"""
    value = params.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise InvalidParamsError(f"参数 {key} 必须是映射: {value!r}")
    return value


def _value(params: Mapping[str, object]) -> object:
    """取要查的那个属性值：**必须给**，空值也是值。"""
    if "value" not in params:
        raise InvalidParamsError("参数 value 不能少：按属性查要给出要查的值")
    return params["value"]


def _bytes(params: Mapping[str, object], key: str) -> bytes:
    """取一个 base64 编码的二进制参数。"""
    text = _text(params, key)
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as error:
        raise InvalidParamsError(f"参数 {key} 不是合法的 base64: {error}") from error


def _as_base64(data: bytes) -> str:
    """把二进制折成能进 JSON 的写法。"""
    return base64.b64encode(data).decode("ascii")


__all__ = ["Api"]

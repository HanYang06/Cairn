# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""行身份与行结构：行序列规范化、行 id、嵌入占位、超长判定。"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

from core.types import ValueUuid

Line = dict[str, Any]
Marker = dict[str, int]

_MARKER_KEYS = ("canvas", "access")

# 超长行阈值：等效中文字数（见 ``text_weight``）。
OVERLONG_WEIGHT = 300.0


def new_id() -> str:
    """生成一个行身份（ULID）。"""
    return str(ValueUuid.new())


def is_marker(value: Any) -> bool:
    """是否是嵌入占位（画板 / 多媒体）。"""
    return isinstance(value, Mapping) and any(key in value for key in _MARKER_KEYS)


def text_weight(text: str) -> float:
    """等效中文字数：全角 / 宽字符记 1，半角记 0.5（用于超长行判定）。"""
    return sum(1.0 if unicodedata.east_asian_width(ch) in ("W", "F") else 0.5 for ch in text)


def entry(line_id: str, value: Any, para: Any = None) -> Line:
    """造一个行元素（可带段落属性 ``p``）；占位映射按值拷贝，避免别名。"""
    item: Line = {"id": line_id, "v": dict(value) if isinstance(value, Mapping) else value}
    if para:
        item["p"] = dict(para)
    return item


def normalize_body(raw: Any) -> list[Line]:
    r"""把任意输入规范成带 id 的行序列；字符串按 ``\n`` 拆行，保留 ``p``（段落属性）。"""
    if isinstance(raw, str):
        raw = raw.split("\n")
    elif isinstance(raw, Mapping) and "v" in raw:
        raw = [raw]
    lines: list[Line] = []
    for item in raw or ():
        if is_marker(item):
            lines.append(entry(new_id(), dict(item)))
            continue
        if isinstance(item, Mapping) and "v" in item:
            lid = str(item.get("id") or new_id())
            para = item.get("p")
            value = item["v"]
            if isinstance(value, str):
                for offset, part in enumerate(value.split("\n")):
                    lines.append(entry(lid if offset == 0 else new_id(), part, para))
            else:
                lines.append(entry(lid, value, para))
            continue
        lines.extend(entry(new_id(), part) for part in str(item).split("\n"))
    return lines or [entry(new_id(), "")]


def copy_lines(lines: Sequence[Line]) -> list[Line]:
    """浅拷贝一份行序列（保 id / 值 / 段落属性）。"""
    return [entry(line["id"], line["v"], line.get("p")) for line in lines]


def index_of(lines: Sequence[Line], line_id: str) -> int:
    """某行在序列里的下标；找不到返回 ``-1``。"""
    for index, line in enumerate(lines):
        if line["id"] == line_id:
            return index
    return -1


__all__ = [
    "OVERLONG_WEIGHT",
    "Line",
    "Marker",
    "copy_lines",
    "entry",
    "index_of",
    "is_marker",
    "new_id",
    "normalize_body",
    "text_weight",
]

# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""属性速查：按属性值找块。

它是**倒排**（值 → 块身份），也是**纯派生**：从块整份重算，丢了重建即可，故
**不落盘、不进备份、不在写路径上维护**。这一条是有意的——倒排在写入时增量维护最容易出
"漏了一处"的事故，而那种事故不报错、只是查不到；整份重算没有这个问题。

用法：

    table = build(index, root)
    table.find("notedata", "title", "第一篇")     # 某个类型的某个属性
    table.find_any("title", "第一篇")             # 不限类型
    table.attributes                              # 能按什么查（界面用）

**哪些属性可查由领域说了算**：属性自己身上写着 `indexed=True`（`core/attr/`）。
没有声明的类型不进表；容器的属性名在声明期就被拦下。

**只收索引里还活着的块**：删除留下的墓碑不指向块记录，故"那份记录还在盘上"不等于
"它还活着"——判据以 `block` 表为准，与巡检、整理同一条口径。

**UI 需求**：它是一次**全库顺扫**，耗时随库体量增长。界面在启动或按需重建时，
应放进后台线程并给进度；查表本身是内存操作，随便调。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .format.block import block_payload_of
from .format.record import decode
from .hub import PackPolicy, find_hubs
from .registry import REGISTRY

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from .index import Index

_EntryKey = tuple[str, str, str, str]
"""表里每一项的键：(类型表名, 属性名, 值的类型名, 值的文本)。"""


def _key(value: object) -> tuple[str, str]:
    """把值折成查表用的键：**带上类型名**，免得 `1` 与 `True` 撞在一起。

    （Python 里 `1 == True` 且哈希相同，不带类型名就会串。）
    """
    return type(value).__name__, str(value)


@dataclass(frozen=True, slots=True)
class AttributeIndex:
    """一份属性速查表：从块重算出来的倒排。

    Attributes:
        entries: 每一项的键 → 块身份清单。
        scanned: 重算时扫过多少条记录。
        indexed: 收进表里的键值对条数。
    """

    entries: Mapping[_EntryKey, tuple[str, ...]] = field(default_factory=dict)
    scanned: int = 0
    indexed: int = 0

    def find(self, kind: str, attribute: str, value: object) -> tuple[str, ...]:
        """按（类型，属性，值）找块身份；没有即空元组。"""
        type_name, text = _key(value)
        return self.entries.get((kind, attribute, type_name, text), ())

    def find_any(self, attribute: str, value: object) -> tuple[str, ...]:
        """跨类型按（属性，值）找：同一个属性名在多个类型上都可查时用它。"""
        wanted = _key(value)
        found: list[str] = []
        for key, identities in self.entries.items():
            _kind, name, item_type, item_text = key
            if name == attribute and (item_type, item_text) == wanted:
                found.extend(identities)
        return tuple(found)

    @property
    def attributes(self) -> tuple[tuple[str, str], ...]:
        """表里有哪些（类型，属性）可查——界面拿它显示"能按什么查"。"""
        return tuple(sorted({(kind, name) for kind, name, _type, _text in self.entries}))


def build(index: Index, root: str | Path, *, policy: PackPolicy | None = None) -> AttributeIndex:
    """从块整份重算一份属性速查表（**只读**，一个字节都不动）。

    顺扫全部载体，认出块记录、解开它的属性，按类型声明把"要查的那些"收进倒排。
    """
    declared = _declared()
    alive = {row.value_uuid for row in index.rows.blocks()}
    entries: dict[_EntryKey, list[str]] = {}
    scanned = indexed = 0
    for hub in find_hubs(root, policy=policy):
        for pack in hub.pack_names():
            with hub.carrier(pack) as carrier:
                for _span, raw in carrier.scan():
                    scanned += 1
                    record = decode(raw)
                    if record.id.value_uuid not in alive:
                        continue
                    parsed = block_payload_of(record.payload)
                    if parsed is None:
                        continue  # 内容记录：它没有属性
                    wanted = declared.get(record.kind)
                    if not wanted:
                        continue
                    for name in wanted:
                        if name not in parsed.attrs:
                            continue
                        type_name, text = _key(parsed.attrs[name])
                        entries.setdefault((record.kind, name, type_name, text), []).append(
                            record.id.value_uuid
                        )
                        indexed += 1
    return AttributeIndex(
        entries={key: tuple(value) for key, value in entries.items()},
        scanned=scanned,
        indexed=indexed,
    )


def _declared() -> dict[str, tuple[str, ...]]:
    """登记表里声明了要建速查的那些类型：表名 → 属性名。"""
    return {decl.table: decl.indexed for decl in REGISTRY.declarations() if decl.indexed}


__all__ = ["AttributeIndex", "build"]

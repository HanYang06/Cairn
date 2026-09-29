# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""巡检与处置：库与真源双向比对，只报告；处置**只补不删**（设计篇 §8.7）。

三条最容易写错的口径，都钉在代码里：

- **两个方向都比**：盘上有、库里没有（`missing_row`）与库里有、盘上读不出来（`missing_record`）
  是两种不同的毛病，修法也不同；
- **一致要两项都对**：位置（hub / 载体 / 格区间）与**摘要凭证**同时与该身份的某次出现相符，
  才算"行指向的字节还在"。只比位置会放过这一种：索引行被改坏，位置恰好落在该身份的另一份副本上，
  而那份副本的内容与行声明的摘要不符；
- **坏点不即停**：重建遇到读不出的载体要抛（半份结果不能当结果），巡检相反——
  **按载体捕捉、其余照扫**，"还坏在哪儿"正是它要回答的问题。

两条边界：**同一身份在盘上出现多次不算差异**（更新留下的旧副本等压实回收，只要行指向的那一份
存在即可）；**处置是"补"而不是"修"**——不可修复的发现一律不碰，删行等于把"丢了东西"这件事抹掉。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from core.clock import now_ms
from core.exc import HubShapeError, RecordFormatError, SlotError

from .format.record import decode
from .hub import Hub, PackPolicy, find_hubs
from .rows import Location

if TYPE_CHECKING:
    from pathlib import Path

    from .carrier import SlotRange
    from .index import Index


class FindKind(Enum):
    """六类发现：种类即处置依据。"""

    UNREGISTERED_HUB = "unregistered_hub"
    """hub 目录在、登记缺——可由补登记修复。"""

    MISSING_ROW = "missing_row"
    """盘上有记录、库里没有行——可由补行修复。"""

    MISPLACED = "misplaced"
    """行在、摘要对得上，但坐标与载体里的实际位置不符——可由改坐标修复。"""

    MISSING_RECORD = "missing_record"
    """行在、盘上读不出来——**内容真的没了**，只能报告。"""

    MISSING_HUB = "missing_hub"
    """登记或行指向的 hub 目录缺——**hub 没了**，只能报告。"""

    CORRUPT_CARRIER = "corrupt_carrier"
    """载体读不到底（截断 / 校验失败）——**坏点只有人看得出来**，只能报告。"""


REPAIRABLE = frozenset({FindKind.UNREGISTERED_HUB, FindKind.MISSING_ROW, FindKind.MISPLACED})
"""可由补登记 / 补行 / 改坐标修复的那一列；其余一律不碰。"""


@dataclass(frozen=True, slots=True)
class Find:
    """一处发现。

    Attributes:
        kind: 发现种类。
        hub: 涉及的 hub。
        subject: 涉及的对象（身份或载体名）。
        detail: 人读的说明。
        location: 行级发现带上"应该写成什么样"——处置据此补行或改坐标，不去 `detail` 里反解。
    """

    kind: FindKind
    hub: str
    subject: str
    detail: str
    location: Location | None = None

    @property
    def repairable(self) -> bool:
        """这一处能不能由处置修好。"""
        return self.kind in REPAIRABLE


@dataclass(frozen=True, slots=True)
class PatrolReport:
    """一次巡检的结果。

    Attributes:
        finds: 全部发现，按（种类、hub、对象）排序。
        hubs_scanned: 看过几个 hub 目录。
        records_scanned: 读过几条记录。
    """

    finds: tuple[Find, ...] = ()
    hubs_scanned: int = 0
    records_scanned: int = 0

    @property
    def clean(self) -> bool:
        """库与真源没有差异。"""
        return not self.finds

    @property
    def repairable(self) -> tuple[Find, ...]:
        """可由处置修好的那一列。"""
        return tuple(item for item in self.finds if item.repairable)

    @property
    def broken(self) -> tuple[Find, ...]:
        """修不好、只能报告的那一列。"""
        return tuple(item for item in self.finds if not item.repairable)


@dataclass(frozen=True, slots=True)
class RepairReport:
    """一次处置的结果。

    Attributes:
        applied: 实际补上的发现。
        skipped: 不碰的发现（不可修复）。
    """

    applied: tuple[Find, ...] = ()
    skipped: tuple[Find, ...] = ()


@dataclass(frozen=True, slots=True)
class _Occurrence:
    """盘上一次出现：哪个身份、在哪儿、摘要是什么。"""

    value_uuid: str
    hub: str
    pack: str
    span: SlotRange
    value_hash: str
    size: int
    issued: int


def patrol(index: Index, root: str | Path, *, policy: PackPolicy | None = None) -> PatrolReport:
    """巡检：把库与真源比一遍，**只报告不动库**。

    Args:
        index: 已对齐的索引库。
        root: vault 根目录。
        policy: 打开 hub 时用的策略（只影响列目录，不影响比对）。

    Returns:
        发现清单：可修复的与只能报告的都在里面。
    """
    rows = index.rows
    on_disk = {hub.name: hub for hub in find_hubs(root, policy=policy)}
    registered = {item.name for item in rows.hubs()}
    finds, occurrences, records_scanned = _scan_disk(on_disk, registered)

    locations = rows.locations()
    missing = {name for name in registered if name not in on_disk}
    missing |= {item.hub for item in locations if item.hub not in on_disk}
    finds.extend(
        Find(FindKind.MISSING_HUB, name, name, "登记或行指向的 hub 目录不在")
        for name in sorted(missing)
    )
    finds.extend(_row_finds(locations, missing, occurrences))
    finds.extend(_missing_row_finds(locations, occurrences))

    ordered = tuple(sorted(finds, key=lambda item: (item.kind.value, item.hub, item.subject)))
    return PatrolReport(
        finds=ordered,
        hubs_scanned=len(on_disk),
        records_scanned=records_scanned,
    )


def _scan_disk(
    on_disk: dict[str, Hub], registered: set[str]
) -> tuple[list[Find], dict[str, list[_Occurrence]], int]:
    """盘 → 库：登记缺的 hub、坏载体，以及各身份在盘上的出现。

    坏载体**按载体捕捉**（`_scan` 一次只扫一个），故一个坏了不影响其余的照扫。
    """
    finds: list[Find] = []
    occurrences: dict[str, list[_Occurrence]] = {}
    records_scanned = 0
    for name, hub in on_disk.items():
        if name not in registered:
            finds.append(Find(FindKind.UNREGISTERED_HUB, name, name, "hub 目录在、登记缺"))
        for pack in hub.pack_names():
            try:
                records_scanned += _scan(hub, pack, occurrences)
            except (RecordFormatError, SlotError, HubShapeError) as error:
                finds.append(Find(FindKind.CORRUPT_CARRIER, name, pack, f"载体读不到底: {error}"))
    return finds, occurrences, records_scanned


def _row_finds(
    locations: tuple[Location, ...],
    missing: set[str],
    occurrences: dict[str, list[_Occurrence]],
) -> list[Find]:
    """库 → 盘：逐行比位置与摘要。"""
    finds: list[Find] = []
    for location in locations:
        if location.hub in missing:
            continue
        find = _compare_row(location, occurrences)
        if find is not None:
            finds.append(find)
    return finds


def _missing_row_finds(
    locations: tuple[Location, ...], occurrences: dict[str, list[_Occurrence]]
) -> list[Find]:
    """盘上有、库里没有的身份：补行的那一列。"""
    known = {item.value_uuid for item in locations}
    return [
        Find(
            FindKind.MISSING_ROW,
            occurrence.hub,
            value_uuid,
            "盘上有记录、库里没有行",
            location=_as_location(occurrence),
        )
        for value_uuid in sorted(occurrences)
        if value_uuid not in known
        for occurrence in [occurrences[value_uuid][0]]
    ]


def repair(index: Index, report: PatrolReport, *, now: int | None = None) -> RepairReport:
    """处置：**只动可修复的那一列，且只补不删**。

    - 缺登记 → 补登记（登记记的是"第一次见到它"）；
    - 缺行 → 按记录补行（类型与落盘时刻给空值，重扫编不出来）；
    - 坐标不符 → 只改坐标（不动类型标号与三个时刻）。

    不可修复的发现一律不碰：删行等于把"丢了东西"这件事抹掉。
    """
    rows = index.rows
    stamp = now_ms() if now is None else now
    applied: list[Find] = []
    skipped: list[Find] = []

    for find in report.finds:
        if find.kind is FindKind.UNREGISTERED_HUB:
            rows.register_hub(find.hub, created=stamp)
        elif find.kind is FindKind.MISSING_ROW and find.location is not None:
            rows.put_location(find.location)
        elif find.kind is FindKind.MISPLACED and find.location is not None:
            rows.move_location(find.location, updated=stamp)
        else:
            skipped.append(find)
            continue
        applied.append(find)

    return RepairReport(applied=tuple(applied), skipped=tuple(skipped))


def _scan(hub: Hub, pack: str, occurrences: dict[str, list[_Occurrence]]) -> int:
    """扫**一个**载体，把记录登记进 `occurrences`；返回读到的条数。

    只扫一个：坏载体由调用方捕捉，其余照扫——这是"坏点不即停"的落点。
    """
    count = 0
    with hub.carrier(pack) as carrier:
        for span, raw in carrier.scan():
            record = decode(raw)
            occurrences.setdefault(record.id.value_uuid, []).append(
                _Occurrence(
                    value_uuid=record.id.value_uuid,
                    hub=hub.name,
                    pack=pack,
                    span=span,
                    value_hash=record.id.value_hash,
                    size=len(raw),
                    issued=record.id.birth_time,
                )
            )
            count += 1
    return count


def _compare_row(location: Location, occurrences: dict[str, list[_Occurrence]]) -> Find | None:
    """比一行：位置与摘要**两项都对**才算一致。"""
    found = occurrences.get(location.value_uuid, [])
    same_place = [
        item
        for item in found
        if item.hub == location.hub and item.pack == location.pack and item.span == location.span
    ]
    if any(item.value_hash == location.value_hash for item in same_place):
        return None

    same_content = [item for item in found if item.value_hash == location.value_hash]
    if same_content:
        return Find(
            FindKind.MISPLACED,
            location.hub,
            location.value_uuid,
            "行在、摘要对得上，但坐标与实际位置不符",
            location=_as_location(same_content[0]),
        )
    return Find(
        FindKind.MISSING_RECORD,
        location.hub,
        location.value_uuid,
        "行在、盘上读不出这一份内容",
    )


def _as_location(occurrence: _Occurrence) -> Location:
    """把盘上的一次出现写成"应该补成什么样"的行（类型与落盘时刻未知，给空值）。

    `name` 也给空：作用域名是引用方写下的，顺扫载体读不到它——重建补行时只能是未知，
    与 `kind` / `created` 同一种降级（设计篇 §8.5）。
    """
    return Location(
        value_uuid=occurrence.value_uuid,
        value_hash=occurrence.value_hash,
        hub=occurrence.hub,
        pack=occurrence.pack,
        span=occurrence.span,
        size=occurrence.size,
        birth_time=occurrence.issued,
    )


__all__ = [
    "REPAIRABLE",
    "Find",
    "FindKind",
    "PatrolReport",
    "RepairReport",
    "patrol",
    "repair",
]

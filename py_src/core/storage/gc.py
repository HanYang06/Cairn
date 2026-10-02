# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""GC：把没人要的字节真正抹掉。

**它是引擎的另一种确定性形态**：走同一条 pack / hub 的路，换一套判据——写入按
"写进来就落"，回收按"库里的行指着谁"。故它不新开一套机制：读用载体、写用载体，
位置段照引擎那一套写。

**按索引库收活槽**（不按载体上的标记收）：载体上没有一处字节说明"这些槽还算数"，
故活口只有一个来源——索引库里的行。

| 槽 | 活着的意思 |
|---|---|
| 属性槽 | 库里有一行，且那一行的位置段指着它 |
| 正文槽 | 库里某一行的**当前世代**或**保留范围之内的旧世代**指着它 |
| 索引条目 | 照 `read_index_rows` 那一条口径：同一个块同一列最后写的那一条说了算 |

**保护旧世代**：保留世代数取配置 `body.history.depth`，超出范围的最老世代可收；
写序那一侧另有一条边界——新槽落定并通过校验之前，旧世代不得被回收。

**收敛零散段**：同一块分散在多处的槽，回收这一趟搬成**连续的一段**，位置段随之改写成
规范形（升序、不重叠、相邻合并、段数最少）。

**开头只扫一遍**：全库的行与全部槽一次收下来，此后的判活、重写、报数字都读这一份抄本。
分散去扫会出现"两处判得不一样"，而这种不一致不报错，只是多删或少删几格。

**挑载体由回收自己办**：新字节写进**新的一份**，不参与 `hub.active` 的挑选——
若交给 hub 去挑，它会挑中那些还没清干净的旧载体，把新槽又写回待回收的文件里。
**没有死槽的载体原地不动**，否则每一趟回收都要把整库抄一遍。

**崩在半路不坏库**：新字节全部落盘之后才删旧载体，故最坏的情形是"新旧两份并存、
白占一份空间"；库里的行先改成指着新的那一份，而旧的那一份还没删，读哪一份都是同一个答案。

**两个触发点**：手动调用本模块的 :func:`sweep`，以及死字节达到配置 `gc.auto.byte`
时自动——自动那一路的判据是 :func:`reclaimable_bytes`，**接线到后台线程尚未落码**。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from core.storage.db.engine import HUB_TABLE, META_TABLE
from core.storage.db.id import (
    ATTR_SLOT_FIELD,
    BODY_HISTORY_FIELD,
    ID,
    canonical_segments,
    encode_body_history,
    pack_segments_ordered,
)
from core.storage.hub import PACKS_DIRNAME, Hub
from core.storage.pack import HEADER_SIZE, Pack, Slot

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from core.storage.engine import Engine

#: 一趟开头那份抄本里的一行：（hub 名，载体路径，这一份载体上的全部槽）。
_Scanned = tuple[str, Path, tuple[Slot, ...]]

#: 落点的坐标：（hub 名，载体名，槽号）。
_Where = tuple[str, str, int]


@dataclass(frozen=True, slots=True)
class SweepReport:
    """一趟回收的结果：按载体与按槽两条口径各给一份数字。

    Attributes:
        hubs: 这一趟走过的 hub 名（按名字排序）。
        packs_before: 开始时的载体份数。
        packs_after: 结束时的载体份数。
        slots_before: 开始时的槽数。
        slots_after: 结束时的槽数。
        bytes_before: 开始时全部载体的总字节数。
        bytes_after: 结束时全部载体的总字节数。
        cancelled: 是否被 `should_stop` 叫停（已处理的那几个 hub 保持不变）。
    """

    hubs: tuple[str, ...]
    packs_before: int
    packs_after: int
    slots_before: int
    slots_after: int
    bytes_before: int
    bytes_after: int
    cancelled: bool = False

    @property
    def reclaimed(self) -> int:
        """这一趟真正收回的字节数（可能为零：没有死槽时回收什么都不做）。"""
        return self.bytes_before - self.bytes_after


def reclaimable_bytes(engine: Engine) -> int:
    """当前**可回收的字节数**：死槽那几格的字节数，即自动回收的判据。

    判据与 :func:`sweep` 同一套（按库里的行收活槽），故"够不够触发"与实际会收掉多少一致。
    配置 `gc.auto.byte` 为零即不自动回收，调用方按它决定要不要问这一问。
    """
    live = _live_slots(engine)
    room = _slot_bytes(engine)
    total = 0
    for hub_name, path, slots in _scan(engine):
        pack_name = path.name
        for number, _slot in enumerate(slots):
            if (hub_name, pack_name, number) not in live:
                total += room
    return total


def sweep(
    engine: Engine,
    *,
    on_progress: Callable[[int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> SweepReport:
    """走一趟：把全库的死槽去掉，并把索引库扶正。

    Args:
        engine: 要整理的引擎。
        on_progress: 每处理完一个 hub 报一次，参数是（已完成，总数）。
        should_stop: 每个 hub 开始之前问一次；返回真即停下，已处理的那几个保持不变。

    Returns:
        这一趟的数字。
    """
    scanned = tuple(_scan(engine))
    bytes_before = sum(_pack_bytes(path, slots) for _hub, path, slots in scanned)
    packs_before = len(scanned)
    slots_before = sum(len(slots) for _hub, _path, slots in scanned)
    names = tuple(sorted({hub for hub, _path, _slots in scanned}))
    live = _live_slots(engine)
    cancelled = False
    for done, hub_name in enumerate(names, start=1):
        if should_stop is not None and should_stop():
            cancelled = True
            break
        moved = _rewrite(engine, hub_name, scanned, live)
        _reindex(engine, moved)
        live.update(_live_slots(engine))
        if on_progress is not None:
            on_progress(done, len(names))
    _forget_the_dead(engine, live)
    after = tuple(_scan(engine))
    return SweepReport(
        hubs=tuple(sorted({hub for hub, _path, _slots in after})),
        packs_before=packs_before,
        packs_after=len(after),
        slots_before=slots_before,
        slots_after=sum(len(slots) for _hub, _path, slots in after),
        bytes_before=bytes_before,
        bytes_after=sum(_pack_bytes(path, slots) for _hub, path, slots in after),
        cancelled=cancelled,
    )


def _live_slots(engine: Engine) -> set[_Where]:
    """活口清单：**全部行的当前世代与保留范围之内的旧世代**。

    库是权威视角，故清单只从库里来：行的位置段给出当前世代，正文历史那一列给出旧世代。
    保留世代数由 `keep_generations` 在写侧截过，故这里把两者一并收下即可——超出范围
    的最老世代根本不在库里，那是可以收掉的。
    """
    live: set[_Where] = set()
    for table in _identity_tables(engine):
        for row in engine.index.rows(table):
            hub_name = str(row.get("in_hub") or "")
            pack_name = str(row.get("in_hub_pack") or "")
            if not hub_name or not pack_name:
                continue
            identity = ID.from_row(row)
            for generation in identity.generations:
                for slot in _slots_of(generation):
                    live.add((hub_name, pack_name, slot))
    return live


def _identity_tables(engine: Engine) -> tuple[str, ...]:
    """库里的身份表：**库自用的那两张不算**（`hub` 与 `meta` 不是身份表）。"""
    return tuple(table for table in engine.index.tables() if table not in {HUB_TABLE, META_TABLE})


def _scan(engine: Engine) -> Iterator[_Scanned]:
    """顺扫全库一遍，连"这一份在哪个 hub"一起收下来。"""
    for directory in _hub_dirs(engine):
        for pack in Hub.open(directory).packs():
            yield directory.name, pack.path, tuple(slot for _number, slot in pack.scan())


def _hub_dirs(engine: Engine) -> Iterator[Path]:
    """库根下的 hub 目录（按名字排序）：**只认形状**，与 hub 那一层的判据一致。"""
    root = engine.root
    if not root.is_dir():
        return
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and (entry / PACKS_DIRNAME).is_dir():
            yield entry


def _pack_bytes(path: Path, slots: tuple[Slot, ...]) -> int:
    """一份载体的字节数。

    **按已写过的格数算**（文件头加格数乘格长）：文件尾不会残留不足一格的部分，
    故它与文件的实际长度一致，而格长由文件头的算术得出，不必再读一遍文件头。
    """
    size = path.stat().st_size
    return size if slots else HEADER_SIZE


def _slot_bytes(engine: Engine) -> int:
    """这次装配的格长：报告与自动回收的判据按它计数。"""
    return engine.slot_bytes


def _rewrite(
    engine: Engine,
    hub_name: str,
    scanned: tuple[_Scanned, ...],
    live: set[_Where],
) -> dict[_Where, tuple[str, int]]:
    """重写一个 hub 里那些**有死槽**的载体：活的搬进新的一份，旧的删掉。

    新的一份**按需开**（第一条要写的活槽才开）；搬动之后位置段改写成规范形，
    故零散段在这一趟收敛成整段。

    Returns:
        搬动过的那几格：旧坐标 → （新载体名，新槽号）。**凡是指着旧坐标的行都要改**，
        故它交给调用方去扶正，而不是在这里只改"拥有"那一格的那一行。
    """
    dirty = [
        (path, slots)
        for hub, path, slots in scanned
        if hub == hub_name
        and any((hub_name, path.name, number) not in live for number in range(len(slots)))
    ]
    if not dirty:
        return {}
    hub = Hub.create(
        engine.root / hub_name, slot_bytes=engine.slot_bytes, max_bytes=engine.max_bytes
    )
    moved: dict[_Where, tuple[str, int]] = {}
    writer: Pack | None = None
    target = 0
    for path, slots in dirty:
        for number, slot in enumerate(slots):
            if (hub_name, path.name, number) not in live:
                continue
            if writer is None or writer.sealed:
                writer = hub.new_pack()
                target = 0
            writer.write_at(target, slot.kind, slot.content)
            moved[(hub_name, path.name, number)] = (writer.name, target)
            target += 1
    for path, _slots in dirty:
        path.unlink()
    return moved


def _reindex(engine: Engine, moved: dict[_Where, tuple[str, int]]) -> None:
    """把搬动过的槽写回库里那些行：**位置段照新落点重写，并归成规范形**。"""
    for table in _identity_tables(engine):
        for row in tuple(engine.index.rows(table)):
            _rehome(engine, table, row, moved)


def _rehome(
    engine: Engine, table: str, row: dict[str, object], moved: dict[_Where, tuple[str, int]]
) -> None:
    """扶正一行：它的每一个世代里被搬动的槽都换成新坐标。

    **载体名也要跟着换**：旧的载体这一趟就被删了，只换格号不换名字，下一趟读就指向一个
    已经不存在的文件——而**不报错**，只是读不出来。

    **段边界按写侧的约定重建**：`attr_slots` 那一列数的是属性槽占几**段**，故扶正时
    必须照"正文槽在前、属性槽在后、两段不相邻不合并"铺一遍。照旧那一份的格号次序铺会
    让两段并成一段，读侧就再也切不开，而**不报错**。
    """
    hub_name = str(row.get("in_hub") or "")
    pack_name = str(row.get("in_hub_pack") or "")
    if not hub_name or not pack_name:
        return
    identity = ID.from_row(row)
    hold = list(identity.attr_in_pack_slot)
    targets: list[int] = []
    attr_targets: list[int] = []
    new_pack = pack_name
    changed = False
    for point in identity.in_pack_slot:
        for slot in _slots_of([point]):
            where = moved.get((hub_name, pack_name, slot))
            target = slot if where is None else where[1]
            if where is not None:
                changed = True
                new_pack = where[0]
            if _holds(hold, slot):
                attr_targets.append(target)
                continue
            targets.append(target)
    if not changed:
        return
    identity.in_pack_slot = list(_merge_groups([targets, attr_targets]))
    identity.attr_in_pack_slot = list(canonical_segments(attr_targets))
    row["in_hub_pack"] = new_pack
    row["in_pack_slot"] = pack_segments_ordered(_slots_of(identity.in_pack_slot))
    row[ATTR_SLOT_FIELD] = pack_segments_ordered(attr_targets)
    row[BODY_HISTORY_FIELD] = encode_body_history(identity.body_history)
    engine.index.put(table, row)


def _holds(attr_spans: Iterable[int | tuple[int, int]], slot: int) -> bool:
    """这一格在不在属性槽那几段里。"""
    return slot in set(_slots_of(attr_spans))


def _merge_groups(groups: Iterable[Iterable[int]]) -> list[int | tuple[int, int]]:
    """按分组把槽号折成段列表（组内相邻者并段，组与组之间不并）。"""
    return [item for group in groups for item in _merge(group)]


def _merge(slots: Iterable[int]) -> list[int | tuple[int, int]]:
    """把一串槽号折成段（相邻者并段），次序照给的次序。"""
    found: list[int | tuple[int, int]] = []
    for slot in slots:
        if found and isinstance(found[-1], tuple) and found[-1][1] + 1 == slot:
            found[-1] = (found[-1][0], slot)
            continue
        if found and isinstance(found[-1], int) and found[-1] + 1 == slot:
            found[-1] = (found[-1], slot)
            continue
        found.append(slot)
    return found


def _forget_the_dead(engine: Engine, live: set[_Where]) -> None:
    """摘掉位置段已全部不在活口里的行：**那些身份已经没有字节了**。

    **只动身份表**：库自用的那两张（`hub` 与 `meta`）不动。
    """
    for table in _identity_tables(engine):
        for row in tuple(engine.index.rows(table)):
            identity = ID.from_row(row)
            if not identity.in_hub or not identity.in_hub_pack:
                continue
            if any(
                (identity.in_hub, identity.in_hub_pack, slot) in live
                for generation in identity.generations
                for slot in _slots_of(generation)
            ):
                continue
            engine.index.drop_row(table, identity.value_uuid)


def _slots_of(spans: Iterable[int | tuple[int, int]]) -> tuple[int, ...]:
    """把段列表展开成升序的一串槽号。"""
    found: list[int] = []
    for item in spans:
        if isinstance(item, int):
            found.append(item)
            continue
        found.extend(range(item[0], item[1] + 1))
    return tuple(found)


def _int(value: object) -> int:
    """把整数字段读回：缺失取 0。"""
    return 0 if value in {None, ""} else int(str(value))


__all__ = ["SweepReport", "reclaimable_bytes", "sweep"]

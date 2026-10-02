# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""GC：把没人要的字节真正抹掉。

**它是引擎的另一种确定性形态**：走同一条 slot / pack / hub 的路，换一套判据——写入按
"写进来就落"，GC 按"谁还活着"。故它不新开一套机制：读用 `pack.scan`，写用
`pack.append`，位置回填照 `Engine` 那一套办。

**四条判据，一条都不能少**：

| 记录 | 活着的意思 |
|---|---|
| 块记录 | 同一个身份**最后**写的那一条，且没有被墓碑标记过 |
| 内容记录 | 被某条活着的块记录的指针指着（内容按摘要寻址，同一份只留一条） |
| 索引条目 | 它指的那个块还活着（指着已删的块的那一行是死重量） |
| 墓碑 | **不保留**：它标记的那些字节这一趟就没了，留着它只是死重量 |

**判活按载荷摘要**：块身份随载荷，故"最后一条说了算"在摘要上判得准；而索引块的身份是个容器
（一块装很多行），它自己那份摘要没有意义。

**开头只扫一遍**：全库记录连"它在哪个 hub 的哪份载体里"一起收下来，此后的判活、重写、报数字
都读这一份抄本。分散去扫会出现"两处判得不一样"，而这种不一致不报错，只是多删或少删几条。

**挑载体由 GC 自己办**：它写的是**新的一份**（`Hub.new_pack`），不参与 `hub.active` 的挑选——
若交给 hub 去挑，它会挑中那些还没清干净的旧载体，把新记录又写回待删的文件里。
**没有死记录的载体原地不动**，否则每一趟 GC 都要把整库抄一遍。

**崩在半路不坏库**：新字节全部落盘之后才删旧载体，故最坏的情形是"新旧两份并存、白占一份
空间"，而两份内容逐字相同——记录自带身份，读哪一份都是同一个答案。下一趟 GC 会把重出来的
那一份判成死记录收掉。

**库是投影，故这一趟一并扶正**：活着的身份按新坐标重写行、消失的身份摘掉行。这一步不是可选
的：坐标一旦失效，"按身份问路"就走空（引擎会回退顺扫，故不至于读错，但每次都退化成扫全库）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.storage.db.engine import HUB_TABLE, META_TABLE
from core.storage.db.id import digest
from core.storage.db.payload import decode_block, decode_index, decode_tombstone
from core.storage.hub import PACKS_DIRNAME, Hub
from core.storage.pack import Pack, Record

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from core.storage.db.engine import Index
    from core.storage.db.id import ID
    from core.storage.db.payload import ContentRef
    from core.storage.engine import Engine

#: 一趟开头那份抄本的一行：（hub 名，载体，它里面的记录）。**顺序即顺扫的顺序**。
_Scanned = tuple[str, Pack, tuple[Record, ...]]


@dataclass(frozen=True, slots=True)
class SweepReport:
    """一趟 GC 的结果：按载体与按字节两条口径各给一份数字。

    Attributes:
        hubs: 这一趟走过的 hub 名（按名字排序）。
        packs_before: 开始时的载体份数。
        packs_after: 结束时的载体份数。
        records_before: 开始时的记录条数。
        records_after: 结束时的记录条数。
        bytes_before: 开始时全部载体的总字节数。
        bytes_after: 结束时全部载体的总字节数。
        cancelled: 是否被 `should_stop` 叫停（已处理的那几个 hub 保持不变）。
    """

    hubs: tuple[str, ...]
    packs_before: int
    packs_after: int
    records_before: int
    records_after: int
    bytes_before: int
    bytes_after: int
    cancelled: bool = False

    @property
    def reclaimed(self) -> int:
        """这一趟真正收回的字节数（可能为零：没有死记录时 GC 什么都不做）。"""
        return self.bytes_before - self.bytes_after


def sweep(
    engine: Engine,
    *,
    on_progress: Callable[[int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> SweepReport:
    """走一趟：把全库的死字节去掉，并把索引库扶正。

    Args:
        engine: 要整理的引擎。
        on_progress: 每处理完一个 hub 报一次，参数是（已完成，总数）。
        should_stop: 每个 hub 开始之前问一次；返回真即停下，已处理的那几个保持不变。

    Returns:
        这一趟的数字。
    """
    scanned = tuple(_scan(engine))
    live = _Live.of(scanned)
    names = _hub_names(scanned)
    bytes_before = sum(pack.size for _hub, pack, _records in scanned)
    packs_before = len(scanned)
    records_before = sum(len(records) for _hub, _pack, records in scanned)
    cancelled = False
    for done, hub_name in enumerate(names, start=1):
        if should_stop is not None and should_stop():
            cancelled = True
            break
        _rewrite(engine, hub_name, scanned, live)
        if on_progress is not None:
            on_progress(done, len(names))

    _reindex(engine, live)
    after = tuple(_hub_packs(engine))
    bytes_after, packs_after, records_after = _measure(after)
    return SweepReport(
        hubs=tuple(directory.name for directory, _ in after),
        packs_before=packs_before,
        packs_after=packs_after,
        records_before=records_before,
        records_after=records_after,
        bytes_before=bytes_before,
        bytes_after=bytes_after,
        cancelled=cancelled,
    )


class _Live:
    """这一趟的**活口清单**：谁还活着，以及它这一趟之后落在哪儿。

    判据集中在这里算一遍，重写与扶正两段都读它。
    """

    def __init__(self) -> None:
        """空清单：活口摘要、身份与落点各一张表。"""
        self.digests: set[str] = set()
        """活着的载荷摘要。块身份随载荷，故摘要相同即同一条记录。"""
        self.identities: dict[str, ID] = {}
        """活着的身份：`value_uuid` → 身份（扶正索引库时按它写行）。"""
        self.places: dict[str, tuple[str, str, tuple[int, int]]] = {}
        """落点：`value_uuid` → （hub，载体，格区间）。**先记原样，搬动的改写它**。"""

    @classmethod
    def of(cls, scanned: tuple[_Scanned, ...]) -> _Live:
        """由那份抄本算一遍：先认墓碑，再按"最后一条说了算"与"谁被指着"定活口。"""
        live = cls()
        blocks, contents, indexes = _classify(scanned)
        for entry in blocks.values():
            live._keep(*entry)
        wanted = {_ref_of(entry[2][0]).value_hash for entry in blocks.values()}
        for payload_digest, entry in contents.items():
            if payload_digest in wanted:
                live._keep(*entry)
        for entry in indexes.values():
            parsed = decode_index(entry[2][0].payload)
            if parsed is not None and any(uuid in live.identities for uuid in parsed[3]):
                live._keep(*entry)
        return live

    def _keep(self, hub_name: str, pack: Pack, records: tuple[Record, ...]) -> None:
        """收下一条活记录：摘要、身份、**它现在的位置**（位置是扫出来的，不是猜的）。"""
        for record in records:
            self.digests.add(digest(record.payload))
            self.identities[record.identity.value_uuid] = record.identity
            self.places[record.identity.value_uuid] = (
                hub_name,
                pack.name,
                (record.span.first, record.span.last),
            )


def _scan(engine: Engine) -> Iterator[_Scanned]:
    """顺扫全库一遍，连"这条在哪个 hub 的哪份载体"一起收下来。"""
    for directory, packs in _hub_packs(engine):
        for pack in packs:
            yield directory.name, pack, tuple(pack.scan())


def _classify(
    scanned: tuple[_Scanned, ...],
) -> tuple[dict[str, _Scanned], dict[str, _Scanned], dict[tuple[str, str], _Scanned]]:
    """把抄本分三拨收好：（块记录，内容记录，索引条目）。

    三拨的判据只看载荷的保留键，故这一趟不需要任何领域知识。**同一个身份的块记录取最后一条**
    （每存一次追加一条）；索引条目按（字段，它指的那些块）取最后一条——那正是
    `Engine.read_index_rows` 翻反表时"最后写的说了算"的同一条口径。

    **墓碑要等扫完再比**：墓碑是追加写的，它总排在它标记的那条记录**之后**，
    故边扫边比会把"已删的块"留成活的。
    """
    marked: set[str] = set()
    blocks: dict[str, _Scanned] = {}
    contents: dict[str, _Scanned] = {}
    indexes: dict[tuple[str, str], _Scanned] = {}
    for hub_name, pack, records in scanned:
        for record in records:
            payload = record.payload
            victim = decode_tombstone(payload)
            if victim is not None:
                marked.add(victim)
            elif decode_block(payload) is not None:
                blocks[record.identity.value_uuid] = (hub_name, pack, (record,))
            else:
                entry = decode_index(payload)
                if entry is None:
                    contents[digest(payload)] = (hub_name, pack, (record,))
                else:
                    indexes[(entry[1], ",".join(entry[3]))] = (hub_name, pack, (record,))
    return (
        {
            uuid: entry
            for uuid, entry in blocks.items()
            if digest(entry[2][0].payload) not in marked
        },
        contents,
        indexes,
    )


def _hub_packs(engine: Engine) -> Iterator[tuple[Path, tuple[Pack, ...]]]:
    """每个 hub 与它当前的载体（按名字排序）。"""
    for directory in _hub_dirs(engine):
        yield directory, tuple(Hub.open(directory).packs())


def _hub_dirs(engine: Engine) -> Iterator[Path]:
    """库根下的 hub 目录（按名字排序）：**只认形状**，与 hub 那一层的判据一致。"""
    root = engine.root
    if not root.is_dir():
        return
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and (entry / PACKS_DIRNAME).is_dir():
            yield entry


def _hub_names(scanned: tuple[_Scanned, ...]) -> tuple[str, ...]:
    """抄本里出现过的 hub 名，按名字排序（去重）。"""
    return tuple(sorted({hub_name for hub_name, _pack, _records in scanned}))


def _measure(hubs: tuple[tuple[Path, tuple[Pack, ...]], ...]) -> tuple[int, int, int]:
    """（总字节，载体份数，记录条数）：报告用的两条口径。"""
    total = sum(pack.size for _directory, packs in hubs for pack in packs)
    records = sum(len(tuple(pack.scan())) for _directory, packs in hubs for pack in packs)
    return total, sum(len(packs) for _directory, packs in hubs), records


def _rewrite(engine: Engine, hub_name: str, scanned: tuple[_Scanned, ...], live: _Live) -> None:
    """重写一个 hub 里那些**有死记录**的载体：活的搬进新的一份，旧的删掉。

    新的一份**按需开**（第一条要写的记录才开）：整份都死了的载体不该留下一个空壳。
    """
    mine = [
        (pack, records)
        for name, pack, records in scanned
        if name == hub_name
        and any(digest(record.payload) not in live.digests for record in records)
    ]
    if not mine:
        return
    hub = Hub.create(
        engine.root / hub_name, slot_bytes=engine.slot_bytes, max_bytes=engine.max_bytes
    )
    writer: Pack | None = None
    for _pack, records in mine:
        for record in records:
            if digest(record.payload) not in live.digests:
                continue
            if writer is None or writer.sealed:
                writer = hub.new_pack()
            identity = record.identity
            span = writer.append(identity, record.payload)
            live.places[identity.value_uuid] = (hub_name, writer.name, (span.first, span.last))
    for pack, _records in mine:
        pack.path.unlink()


def _ref_of(record: Record) -> ContentRef:
    """块记录指向的内容凭证；不是块记录即抛（调用处只拿块记录进来）。"""
    parsed = decode_block(record.payload)
    if parsed is None:  # pragma: no cover — 调用处已经筛过
        raise ValueError("这一条不是块记录")
    return parsed[0]


def _reindex(engine: Engine, live: _Live) -> None:
    """把索引库扶正：活着的身份按**新坐标**重写行，消失的身份摘掉行。"""
    index = engine.index
    for value_uuid, identity in live.identities.items():
        table = identity.name
        if not table:
            continue
        hub, pack, span = live.places[value_uuid]
        index.ensure_table(table)
        index.register_hub(hub)
        index.put(
            table,
            identity.to_record() | {"in_hub": hub, "in_hub_pack": pack, "in_pack_slot": span},
        )
    _forget_the_dead(index, set(live.identities))


def _forget_the_dead(index: Index, alive: set[str]) -> None:
    """摘掉已消失的身份那一行：**只动身份表**，库自用的那两张不动。"""
    for table in index.tables():
        if table in {HUB_TABLE, META_TABLE}:
            continue
        for row in tuple(index.rows(table)):
            value_uuid = str(row.get("value_uuid") or "")
            if value_uuid and value_uuid not in alive:
                index.drop_row(table, value_uuid)


__all__ = ["SweepReport", "sweep"]

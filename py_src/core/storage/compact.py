# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""整理整库：把墓碑、被删记录与没人用的正文真正抹掉，空间回收。

分两段，这是刻意的：

1. :func:`survey` —— **只读**扫一遍全库，出一份计划：哪些载体要重写、能省多少、
   当前与预计的浪费比率、要读多少字节、要写多少字节；
2. :func:`compact` —— 按计划动手，逐份载体重写。

中间隔着"用户看一眼再确认"，所以扫描不会顺手改东西；勘察给出的数字正是界面要显示的
（发现多少块、当前比率、预计结果比率、预计耗时）。**内核不猜时间**——它不知道这块盘有多快，
故只报"要读多少 / 要写多少字节"，时间由界面按自己的实测吞吐换算。

**为什么不是异步**：文件读写本质是阻塞的，`asyncio` 的非阻塞只对 socket 成立，对文件它靠
线程池模拟、并不更快。真正的效率在**大块顺序读写**，而不是并发读多份载体（并发写还会打乱
顺序）。所以内核保持同步，"不阻塞界面"由上层放进后台线程解决——IO 密集时 GIL 会释放。

**什么算活着**：索引行是权威。

- 块记录：有块行指着它的位置；
- 内容记录：**有块引用它**（`block` 行的 `body_value_hash`）——删块之后留下的正文没人用了，
  整理时连同它的内容行一起回收；
- 墓碑：只为删除做证，整理之后使命结束。

"同一身份的多份副本"与"没人指的旧副本"因此自然落选，不必逐个读墓碑。

**它凭什么可以重复跑**：一份载体没有死记录就跳过。这个数顺扫一遍即可算出，故
**不需要记住"整理过哪些"**；中途崩了重跑，已整理好的那几份自然被跳过，不会把记录复制第二遍。

**崩溃安全**：逐份载体处理，每份的次序是"写新载体 → 更新索引坐标 → 删旧载体"。
写新与改坐标之间崩，多出一份没人指的副本（无害，下次重跑回收）；改坐标与删旧之间崩，
两份都在而索引指新的（也无害，下次重跑删旧的）。

**UI 需求**（这是整库动作，不是某一次写入）：

- 需**用户显式触发**：内核不自己跑——它耗时且会重写文件；
- **分两段给反馈**：先 `survey()` 显示数字（发现多少块、当前比率、预计结果比率、预计耗时），
  用户确认之后再 `compact(plan=…)`；
- **不阻塞界面**：由上层放进后台线程（内核是同步的，见上）；
- **进度**：传 `on_progress(done, total)`，按载体数报；
- **可取消**：传 `should_stop`，取消不影响数据完整性，最多这次没做完。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from .carrier import HEADER_BYTES, Carrier, SlotRange, slots_needed
from .format.block import tombstone_of
from .format.record import decode
from .hub import Hub, PackPolicy, find_hubs
from .rows import BlockRow, BodyRow

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from .index import Index


@dataclass(frozen=True, slots=True)
class PackPlan:
    """一份载体打算怎么处理。

    Attributes:
        hub: 它所在的 hub。
        pack: 载体名。
        live_records: 要留的记录条数。
        dead_records: 要抹的记录条数（墓碑、被删的块、没人用的正文都在内）。
        bytes_before: 它现在的字节数（不含文件头）。
        live_grids: 活记录占的格数；它也是重写之后的格数。
        grids_before: 它现在占的格数（不含文件头）。
        bytes_after: 重写之后的字节数。
    """

    hub: str
    pack: str
    live_records: int = 0
    dead_records: int = 0
    bytes_before: int = 0
    live_grids: int = 0
    grids_before: int = 0
    bytes_after: int = 0

    @property
    def rewrite(self) -> bool:
        """要不要动它：一条死记录都没有就已经紧凑，跳过。"""
        return self.dead_records > 0

    @property
    def grids_after(self) -> int:
        """处理之后它占的格数：要重写就只剩活记录，不重写就照旧。"""
        return self.live_grids if self.rewrite else self.grids_before


@dataclass(frozen=True, slots=True)
class SurveyReport:
    """一次勘察：整库现在什么样、整理之后该什么样（**只读**）。

    UI 要的那些数都在这里；预计耗时由界面用 `bytes_to_read` / `bytes_to_write`
    按自己的实测吞吐换算。

    Attributes:
        plans: 逐份载体的计划，按（hub、载体名）排序。
        live_grids: 活记录占的格数。
        total_grids: 全部载体合起来的格数（不含文件头）。
        live_records: 活记录条数。
        dead_records: 该抹掉的记录条数。
        bytes_to_read: 要读多少字节。
        bytes_to_write: 要写多少字节（只算要重写的那几份）。
    """

    plans: tuple[PackPlan, ...] = ()
    live_grids: int = 0
    total_grids: int = 0
    live_records: int = 0
    dead_records: int = 0
    bytes_to_read: int = 0
    bytes_to_write: int = 0

    @property
    def waste_ratio(self) -> float:
        """当前的浪费比例：用不上的格数 ÷ 全部格数。"""
        if self.total_grids == 0:
            return 0.0
        return (self.total_grids - self.live_grids) / self.total_grids

    @property
    def expected_ratio(self) -> float:
        """整理之后预计的浪费比例（只剩格尾补零那一点）。"""
        after = sum(plan.grids_after for plan in self.plans)
        if after == 0:
            return 0.0
        return max(0.0, (after - self.live_grids) / after)

    @property
    def packs_to_rewrite(self) -> int:
        """有几份载体需要动（已经紧凑的不算）。"""
        return sum(1 for plan in self.plans if plan.rewrite)

    @property
    def worth_it(self) -> bool:
        """有没有值得跑一趟的活。"""
        return self.packs_to_rewrite > 0


@dataclass(frozen=True, slots=True)
class CompactReport:
    """一次整理的结果。

    Attributes:
        packs_before: 动过手的载体份数。
        packs_after: 整理后留下的载体份数。
        bytes_before: 动过手的那几份原来的总字节数（不含文件头）。
        bytes_after: 它们现在的总字节数。
        kept: 保留下来的记录条数。
        dropped: 抹掉的记录条数。
        cancelled: 是不是被中途叫停的；数据无损，只是这次没做完。
    """

    packs_before: int = 0
    packs_after: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    kept: int = 0
    dropped: int = 0
    cancelled: bool = False

    @property
    def reclaimed(self) -> int:
        """回收了多少字节。"""
        return max(0, self.bytes_before - self.bytes_after)


def survey(index: Index, root: str | Path, *, policy: PackPolicy | None = None) -> SurveyReport:
    """只读勘察：算出整理计划与全部显示用的数字（**一个字节都不动**）。"""
    plans: list[PackPlan] = []
    live_grids = total_grids = live_records = dead_records = bytes_to_read = bytes_to_write = 0
    for hub in find_hubs(root, policy=policy):
        live = _live(index)
        for pack in hub.pack_names():
            plan = _plan_one(hub, pack, live)
            plans.append(plan)
            live_grids += plan.live_grids
            total_grids += plan.grids_before
            live_records += plan.live_records
            dead_records += plan.dead_records
            bytes_to_read += plan.bytes_before
            if plan.rewrite:
                bytes_to_write += plan.bytes_after
    return SurveyReport(
        plans=tuple(plans),
        live_grids=live_grids,
        total_grids=total_grids,
        live_records=live_records,
        dead_records=dead_records,
        bytes_to_read=bytes_to_read,
        bytes_to_write=bytes_to_write,
    )


def compact(  # noqa: PLR0913 — 一次整理要的那几样：目标、计划、进度、取消，散开更直白
    index: Index,
    root: str | Path,
    *,
    plan: SurveyReport | None = None,
    policy: PackPolicy | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> CompactReport:
    """按计划整理整库：逐份载体重写，只留活记录。

    Args:
        index: 已对齐的索引库；"哪些记录还活着"以它的行为准。
        root: vault 根目录。
        plan: 勘察结果；不给就现场勘察一遍。**计划只用来挑目标**——每一份都现读现判，
            所以勘察之后库又变了也不会把活记录弄丢。
        policy: 开 hub 时用的策略（只影响新建载体的槽长与封口线）。
        on_progress: 每处理完一份载体报一次，参数是（已完成，总数）。
        should_stop: 每份载体开始之前问一次；返回真即停下（已处理的那几份保持不变）。

    Returns:
        本次整理的结果；`cancelled` 为真说明还有没处理到的载体。
    """
    report = survey(index, root, policy=policy) if plan is None else plan
    targets = [(item.hub, item.pack) for item in report.plans if item.rewrite]
    total = len(targets)
    hubs = {hub.name: hub for hub in find_hubs(root, policy=policy)}

    tally = _Tally()
    cancelled = False
    for done, (hub_name, pack) in enumerate(targets, start=1):
        if should_stop is not None and should_stop():
            cancelled = True
            break
        hub = hubs.get(hub_name)
        if hub is None:  # 勘察之后 hub 没了：跳过，那是巡检该报的事
            continue
        _compact_one(index, hub, pack, tally)
        if on_progress is not None:
            on_progress(done, total)
    return tally.done(cancelled=cancelled)


@dataclass(slots=True)
class _Tally:
    """整理过程中的计数：报告是它收口出来的。"""

    packs_before: int = 0
    packs_after: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    kept: int = 0
    dropped: int = 0

    def done(self, *, cancelled: bool) -> CompactReport:
        """收口成一份报告。"""
        return CompactReport(
            packs_before=self.packs_before,
            packs_after=self.packs_after,
            bytes_before=self.bytes_before,
            bytes_after=self.bytes_after,
            kept=self.kept,
            dropped=self.dropped,
            cancelled=cancelled,
        )


def _plan_one(hub: Hub, pack: str, live: _Live) -> PackPlan:
    """算一份载体的计划：留几条、丢几条、重写后占多少格。"""
    with hub.carrier(pack) as carrier:
        raws, _dead, seen = _split(carrier, hub.name, pack, live)
        slot_bytes = carrier.slot_bytes
        size = max(0, carrier.size - HEADER_BYTES)
    grids = sum(slots_needed(len(raw), slot_bytes) for raw in raws)
    return PackPlan(
        hub=hub.name,
        pack=pack,
        live_records=len(raws),
        dead_records=seen - len(raws),
        bytes_before=size,
        live_grids=grids,
        grids_before=size // slot_bytes,
        bytes_after=grids * slot_bytes,
    )


def _compact_one(index: Index, hub: Hub, pack: str, tally: _Tally) -> None:
    """整理一份载体：写新的、改坐标、删旧行与旧文件；结果累进 `tally`。"""
    rows_live = _live(index)
    with hub.carrier(pack) as carrier:
        raws, dead_bodies, seen = _split(carrier, hub.name, pack, rows_live)
        owner = carrier.owner
        size = max(0, carrier.size - HEADER_BYTES)

    tally.packs_before += 1
    tally.bytes_before += size
    tally.kept += len(raws)
    tally.dropped += seen - len(raws)

    if not raws:
        (hub.packs_dir / pack).unlink()
        _drop_bodies(index, dead_bodies)
        return
    if seen == len(raws):
        # 一条死记录都没有：跳过。重复跑整理时，上一轮写出来的那几份走的正是这一支。
        tally.packs_after += 1
        tally.bytes_after += size
        return
    tally.bytes_after += _rewrite(index, hub, pack, raws, owner=owner)
    _drop_bodies(index, dead_bodies)
    tally.packs_after += 1


def _rewrite(index: Index, hub: Hub, pack: str, live: tuple[bytes, ...], *, owner: bytes) -> int:
    """把一份载体重写成一份新的，再把索引坐标改过来，最后删掉旧的；返回新的字节数。

    归属随旧载体带过去：它记的是"这份载体归哪个类型"，重写不该把它弄丢——一旦丢了，
    配额判定会把这份载体算进**每个**类型的账里。

    次序是有意的：**新的没写好之前，旧的不能动**。中途任何一步失败，索引要么还指着旧的
    （数据完好），要么已指着新的（数据也完好）——不会出现"两边都没有"。
    """
    name, fresh = hub.new_pack(owner=owner)
    size = 0
    try:
        for raw in live:
            span = fresh.append(raw)
            size += slots_needed(len(raw), fresh.slot_bytes) * fresh.slot_bytes
            _remap(index, hub.name, name, span, raw)
    finally:
        fresh.close()
    (hub.packs_dir / pack).unlink()
    return size


def _remap(index: Index, hub: str, pack: str, span: SlotRange, raw: bytes) -> None:
    """把一条记录的索引行挪到新坐标（只改坐标，不重写整行）。"""
    identity = decode(raw).id.value_uuid
    block = index.rows.block(identity)
    if block is not None:
        index.rows.move_block(_at_place(block, hub, pack, span))
        return
    body = index.rows.body(identity)
    if body is not None:
        index.rows.move_body(_at_place(body, hub, pack, span))


def _drop_bodies(index: Index, identities: tuple[str, ...]) -> None:
    """把没人用的正文的行摘掉：记录都回收了，行留着只会让巡检报"读不出来"。"""
    for identity in identities:
        index.rows.drop_body(identity)


def _at_place[T: (BlockRow, BodyRow)](row: T, hub: str, pack: str, span: SlotRange) -> T:
    """换一版坐标，其余字段照抄：身份、摘要、指针与类型标号一律不动。"""
    return replace(row, in_hub=hub, in_hub_pack=pack, in_pack_slot=(span.first, span.last))


def _live(index: Index) -> _Live:
    """取索引里的全部行，外加"被块引用到的内容地址"。

    最后那一项是内容记录的活判据：一份内容活着，当且仅当**有块指向它**。
    """
    blocks = {row.value_uuid: row for row in index.rows.blocks()}
    bodies = {row.value_uuid: row for row in index.rows.bodies()}
    return _Live(blocks, bodies, {row.body_value_hash for row in blocks.values()})


@dataclass(slots=True)
class _Live:
    """判"谁还活着"的三样东西：块行、内容行、被块引用到的内容地址。"""

    blocks: dict[str, BlockRow]
    bodies: dict[str, BodyRow]
    referenced: set[str]


def _split(
    carrier: Carrier, hub: str, pack: str, live: _Live
) -> tuple[tuple[bytes, ...], tuple[str, ...], int]:
    """把一份载体的记录分成三类，返回（活的原始字节，该删行的内容身份，扫到的总条数）。

    活的判据分两种：块记录看"有没有块行指着它"，内容记录看"有没有块引用这份内容"。
    墓碑一律落选。
    """
    raws: list[bytes] = []
    dead_bodies: list[str] = []
    seen = 0
    for span, raw in carrier.scan():
        seen += 1
        record = decode(raw)
        identity = record.id.value_uuid
        if tombstone_of(record.payload) is not None:
            continue
        block = live.blocks.get(identity)
        if block is not None:
            if _at(block, hub, pack, span):
                raws.append(raw)
            continue
        body = live.bodies.get(identity)
        if body is not None and _at(body, hub, pack, span):
            if record.id.value_hash in live.referenced:
                raws.append(raw)
            else:
                dead_bodies.append(identity)
    return tuple(raws), tuple(dead_bodies), seen


def _at(row: BlockRow | BodyRow, hub: str, pack: str, span: SlotRange) -> bool:
    """这一行是不是正好指着这份副本（位置三项都对）。"""
    return (
        row.in_hub == hub
        and row.in_hub_pack == pack
        and row.in_pack_slot == (span.first, span.last)
    )


__all__ = ["CompactReport", "PackPlan", "SurveyReport", "compact", "survey"]

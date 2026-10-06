# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""GC:把没人要的字节真正抹掉.

**它是引擎的另一种确定性形态**:走同一条 pack / hub 的路,换一套判据——写入按
"写进来就落",回收按"库里的行指着谁".故它不新开一套机制:读用载体,写用载体,
位置段照引擎那一套写.

**按索引库收活槽**(不按载体上的标记收):载体上没有一处字节说明"这些槽还算数",
故活口只有两个来源——库里那些行的位置段,以及**被任何块的摘要链引用到的正文位置**.

| 槽 | 活着的意思 |
|---|---|
| 属性槽 | 库里有一行,且那一行的位置段指着它 |
| 正文槽 | **某个块自带**(它位置段里的 body 槽),或**某个块的摘要链引用到那份正文** |
| 正文位置行 | 同一个判据:还有块的摘要链指着这一份正文,那一行就是它的坐标 |
| 索引块的槽 | 与任何块同路:索引块自己在库里也有行,指着它的槽即活口 |

**摘要链是活口的第二来源**(2026-10-02 修正裁定):一份正文的坐标**不挂在某个块身上**
(那一块被删了,还在引用它的块就断了),故"还有没有人要这份正文"只能按各块的摘要链现算.
由此得到两条:**块被删时正文索引行与正文槽留着**,由回收判活;**没人要了才摘掉那一行**
(位置行是推导出来的坐标,不是内容本身,故摘它不丢数据).

**保护旧世代**:摘要链里保留范围之内的那几代都算活口(保留世代数取配置
`body.history.depth`),超出范围的最老世代可收;写序那一侧另有一条边界——新槽落定并通过
校验之前,旧世代不得被回收.

**收敛零散段**:同一块分散在多处的槽,回收这一趟搬成**连续的一段**,位置段随之改写成
规范形(升序,不重叠,相邻合并,段数最少).

**开头只扫一遍**:全库的行与全部槽一次收下来,此后的判活,重写,报数字都读这一份抄本.
分散去扫会出现"两处判得不一样",而这种不一致不报错,只是多删或少删几格.

**挑载体由回收自己办**:新字节写进**新的一份**,不参与 `hub.active` 的挑选——
若交给 hub 去挑,它会挑中那些还没清干净的旧载体,把新槽又写回待回收的文件里.
**没有死槽的载体原地不动**,否则每一趟回收都要把整库抄一遍.

**崩在半路不坏库**:新字节全部落盘之后才删旧载体,故最坏的情形是"新旧两份并存,
白占一份空间";库里的行先改成指着新的那一份,而旧的那一份还没删,读哪一份都是同一个答案.

**两个触发点**:手动调用本模块的 :func:`sweep`,以及死字节达到配置 `gc.auto.byte`
时自动——自动那一路的判据是 :func:`reclaimable_bytes`,**接线到后台线程尚未落码**.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from core.exc import (
    HubNotFoundError,
    HubShapeError,
    IndexNotFoundError,
    IndexSchemaError,
    SlotTooLargeError,
)
from core.storage.db.engine import HUB_TABLE, META_TABLE
from core.storage.db.id import ID, canonical_segments, parse_body_history, parse_segments
from core.storage.db.payload import (
    COLUMN_KEY,
    HUB_KEY,
    PACK_KEY,
    SEGMENTS_KEY,
    decode_index_row,
    decode_segments,
    encode_index_row,
    encode_segments,
    index_text,
)
from core.storage.hub import PACKS_DIRNAME, Hub
from core.storage.pack import ATTR_SLOT, BODY_SLOT, HEADER_SIZE, Pack, Slot

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping

    from core.storage.engine import Engine

#: 一趟开头那份抄本里的一行:(hub 名,载体路径,这一份载体上的全部槽).
_Scanned = tuple[str, Path, tuple[Slot, ...]]

#: 落点的坐标:(hub 名,载体名,槽号).
_Where = tuple[str, str, int]


@dataclass(frozen=True, slots=True)
class SweepReport:
    """一趟回收的结果:按载体与按槽两条口径各给一份数字.

    Attributes:
        hubs: 这一趟走过的 hub 名(按名字排序).
        packs_before: 开始时的载体份数.
        packs_after: 结束时的载体份数.
        slots_before: 开始时的槽数.
        slots_after: 结束时的槽数.
        bytes_before: 开始时全部载体的总字节数.
        bytes_after: 结束时全部载体的总字节数.
        cancelled: 是否被 `should_stop` 叫停(已处理的那几个 hub 保持不变).
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
        """这一趟真正收回的字节数(可能为零:没有死槽时回收什么都不做)."""
        return self.bytes_before - self.bytes_after


def reclaimable_bytes(engine: Engine) -> int:
    """当前**可回收的字节数**:死槽那几格的字节数,即自动回收的判据.

    判据与 :func:`sweep` 同一套(按库里的行收活槽),故"够不够触发"与实际会收掉多少一致.
    配置 `gc.auto.byte` 为零即不自动回收,调用方按它决定要不要问这一问.
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
    """走一趟:把全库的死槽去掉,并把索引库扶正.

    Args:
        engine: 要整理的引擎.
        on_progress: 每处理完一个 hub 报一次,参数是(已完成,总数).
        should_stop: 每个 hub 开始之前问一次;返回真即停下,已处理的那几个保持不变.

    Returns:
        这一趟的数字.
    """
    scanned = tuple(_scan(engine))
    bytes_before = sum(_pack_bytes(path, slots) for _hub, path, slots in scanned)
    packs_before = len(scanned)
    slots_before = sum(len(slots) for _hub, _path, slots in scanned)
    names = tuple(sorted({hub for hub, _path, _slots in scanned}))
    live = _live_slots(engine)
    moved: dict[_Where, tuple[str, int]] = {}
    cancelled = False
    for done, hub_name in enumerate(names, start=1):
        if should_stop is not None and should_stop():
            cancelled = True
            break
        moved.update(_rewrite(engine, hub_name, scanned, live))
        live.update(_live_slots(engine))
        if on_progress is not None:
            on_progress(done, len(names))
    _reindex(engine, moved)
    # **再收一次活口**:重写这一趟自己也会写新槽(搬运的活槽,扶正后的索引行),
    # 它们落进新载体,而开头那一份抄本里没有它们——照旧抄本判死活会把自己刚写的丢掉.
    live = _live_slots(engine)
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
    """活口清单:**全部行的位置段** + **全部块的摘要链引用到的正文位置**.

    库是权威视角,故清单只从库里来:

    - 每一行的位置段给出这个块**自己**占的槽(自带正文的块,正文槽就在其中;
      引用型的块,那几格不在其中,因为它们在别的 pack 里);
    - 每一个块摘要链里的每一代摘要,去正文索引的位置行上查坐标——**那是活口的第二来源**,
      也正是"删一个块不断别人的正文"这条的实现方式.

    **正文索引行自己的槽也算活口**:行是索引块的槽,摘掉它之前它一直算数.
    """
    live: set[_Where] = set()
    for table in _identity_tables(engine):
        for row in engine.index.rows(table):
            hub_name = str(row.get("in_hub") or "")
            pack_name = str(row.get("in_hub_pack") or "")
            if not hub_name or not pack_name:
                continue
            for slot in _slots_of(parse_segments(str(row.get("in_pack_slot") or ""))):
                live.add((hub_name, pack_name, slot))
    wanted = _wanted_bodies(engine)
    for digest_value, _slot, _row_hub, _row_pack, placement in _each_body_placement(engine):
        if digest_value not in wanted:
            continue
        body_hub = str(placement.get(HUB_KEY) or "")
        body_pack = str(placement.get(PACK_KEY) or "")
        for slot in _slots_of(decode_segments(placement.get(SEGMENTS_KEY))):
            live.add((body_hub, body_pack, slot))
    live.update(_body_row_slots(engine))
    return live


def _wanted_bodies(engine: Engine) -> set[str]:
    """**还有块在要的**正文摘要(**库里的写法**:带类型名的文本形).

    判据就是各块的摘要链:一个摘要出现在任何一张身份表的 `body_history` 里,那一份正文
    就算活口(最新那一代是当前用的那一份,其余是保留范围之内的旧世代).

    **写法与库对齐**:位置行里那一列存的是 `index_text` 之后的文本(`str:<十六进制>`),
    故这里也照同一处口径化一次,才对得上.
    """
    wanted: set[str] = set()
    for table in _identity_tables(engine):
        for row in engine.index.rows(table):
            for digest_value in parse_body_history(str(row.get("body_history") or "")):
                wanted.add(index_text(digest_value))
    return wanted


def _each_body_placement(
    engine: Engine,
) -> Iterator[tuple[str, int, str, str, dict[str, object]]]:
    """正文索引里的**每一条**位置行:(摘要,行自己那一格,它所在的 hub,载体,内容).

    **只读那些行自己占的槽**:位置行的坐标写在索引块自己的位置段里,故不必顺扫全库.
    """
    for row in _body_index_rows(engine):
        hub_name = str(row.get("in_hub") or "")
        pack_name = str(row.get("in_hub_pack") or "")
        if not hub_name or not pack_name:
            continue
        try:
            pack = Hub.open(engine.root / hub_name).pack(pack_name)
        except HubNotFoundError, HubShapeError:  # pragma: no cover — 库刚开过
            continue
        for slot in _slots_of(parse_segments(str(row.get("in_pack_slot") or ""))):
            parsed = decode_index_row(pack.content_at(slot))
            if parsed is None or str(parsed.get(COLUMN_KEY) or "") != _body_column():
                continue
            yield str(parsed.get("value") or ""), slot, hub_name, pack_name, parsed


def _all_body_placements(engine: Engine) -> dict[str, dict[str, object]]:
    """正文索引里**全部**位置行:摘要 → 位置行(不管还有没有人在要它)."""
    placement: dict[str, dict[str, object]] = {}
    for digest_value, _slot, _hub_name, _pack_name, parsed in _each_body_placement(engine):
        placement.setdefault(digest_value, parsed)
    return placement


def _body_row_slots(engine: Engine) -> set[_Where]:
    """正文索引**位置行自己占的槽**:它们是索引块的槽,一直算活口."""
    found: set[_Where] = set()
    for row in _body_index_rows(engine):
        hub_name = str(row.get("in_hub") or "")
        pack_name = str(row.get("in_hub_pack") or "")
        for slot in _slots_of(parse_segments(str(row.get("in_pack_slot") or ""))):
            found.add((hub_name, pack_name, slot))
    return found


def _body_index_rows(engine: Engine) -> Iterator[dict[str, object]]:
    """正文索引块在库里的行(一块一行);缺表即空.

    **运行期导入**(本仓不常用的那一档,理由同 `index/index.py` 的 `owners()`):
    正文索引块引 `engine`,故这里不能反过来在模块顶部引它.
    """
    table = _body_index_table()
    if not table:
        return
    try:
        yield from engine.index.rows(table)
    except IndexNotFoundError, IndexSchemaError:  # pragma: no cover — 表由引擎补齐
        return


def _body_index_table() -> str:
    """正文索引块的表名(=它自己的类型名)."""
    from core.storage.index.bodyindex import BodyIndex  # noqa: PLC0415 — 打断环形引用

    return BodyIndex.__name__.lower()


def _body_column() -> str:
    """正文索引里那一列的列名(与写侧同一处声明)."""
    from core.storage.index.index import CONTENT_FIELD  # noqa: PLC0415 — 打断环形引用

    return CONTENT_FIELD


def _identity_tables(engine: Engine) -> tuple[str, ...]:
    """库里的身份表:**库自用的那两张不算**(`hub` 与 `meta` 不是身份表)."""
    return tuple(table for table in engine.index.tables() if table not in {HUB_TABLE, META_TABLE})


def _scan(engine: Engine) -> Iterator[_Scanned]:
    """顺扫全库一遍,连"这一份在哪个 hub"一起收下来."""
    for directory in _hub_dirs(engine):
        for pack in Hub.open(directory).packs():
            yield directory.name, pack.path, tuple(slot for _number, slot in pack.scan())


def _hub_dirs(engine: Engine) -> Iterator[Path]:
    """库根下的 hub 目录(按名字排序):**只认形状**,与 hub 那一层的判据一致."""
    root = engine.root
    if not root.is_dir():
        return
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and (entry / PACKS_DIRNAME).is_dir():
            yield entry


def _pack_bytes(path: Path, slots: tuple[Slot, ...]) -> int:
    """一份载体的字节数.

    **按已写过的格数算**(文件头加格数乘格长):文件尾不会残留不足一格的部分,
    故它与文件的实际长度一致,而格长由文件头的算术得出,不必再读一遍文件头.
    """
    size = path.stat().st_size
    return size if slots else HEADER_SIZE


def _slot_bytes(engine: Engine) -> int:
    """这次装配的格长:报告与自动回收的判据按它计数."""
    return engine.slot_bytes


def _rewrite(
    engine: Engine,
    hub_name: str,
    scanned: tuple[_Scanned, ...],
    live: set[_Where],
) -> dict[_Where, tuple[str, int]]:
    """重写一个 hub 里那些**有死槽**的载体:活的搬进新的一份,旧的删掉.

    新的一份**按需开**(第一条要写的活槽才开);搬动之后位置段改写成规范形,
    故零散段在这一趟收敛成整段.

    Returns:
        搬动过的那几格:旧坐标 → (新载体名,新槽号).**凡是指着旧坐标的行都要改**,
        故它交给调用方去扶正,而不是在这里只改"拥有"那一格的那一行.
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
    """把搬动过的槽写回库里那些行:**位置段照新落点重写,并归成规范形**.

    两类行各扶正一次:

    - **身份表的行**:它的位置段给出这个块自己占的槽(`_rehome`);
    - **正文索引的位置行**:它给出的是**一份正文的坐标**,而那份正文可能属于别的块,
      别的 pack,别的 hub——照旧坐标定位,读侧就再也找不到那份正文(`_rehome_body`).
    """
    for table in _identity_tables(engine):
        for row in tuple(engine.index.rows(table)):
            _rehome(engine, table, row, moved)
    _rehome_body(engine, moved)


def _rehome(
    engine: Engine, table: str, row: dict[str, object], moved: dict[_Where, tuple[str, int]]
) -> None:
    """扶正一行:它位置段里被搬动的槽都换成新坐标.

    **载体名也要跟着换**:旧的载体这一趟就被删了,只换格号不换名字,下一趟读就指向一个
    已经不存在的文件——而**不报错**,只是读不出来.

    **位置段照写侧的约定重铺**(属性槽在前,正文槽在后,组内相邻者并段,组与组之间不并):
    哪一格是什么由槽头给出,故两段不必靠"组"来表达种类,但**次序**照旧要留住.
    """
    hub_name = str(row.get("in_hub") or "")
    pack_name = str(row.get("in_hub_pack") or "")
    if not hub_name or not pack_name:
        return
    identity = ID.from_row(row)
    bodies_here = _body_slots(engine, row)
    attrs: list[int] = []
    bodies: list[int] = []
    new_pack = pack_name
    changed = False
    for slot in _slots_of(identity.in_pack_slot):
        where = moved.get((hub_name, pack_name, slot))
        target = slot if where is None else where[1]
        if where is not None:
            changed = True
            new_pack = where[0]
        (bodies if slot in bodies_here else attrs).append(target)
    if not changed:
        return
    row["in_hub_pack"] = new_pack
    row["in_pack_slot"] = _text_of_segments(_merge_groups([bodies, attrs]))
    engine.index.put(table, row)


def _body_slots(engine: Engine, row: Mapping[str, object]) -> set[int]:
    """库里那一行里**正文槽**占的那几格(种类只从槽头读)."""
    hub_name = str(row.get("in_hub") or "")
    pack_name = str(row.get("in_hub_pack") or "")
    if not hub_name or not pack_name:
        return set()
    try:
        pack = Hub.open(engine.root / hub_name).pack(pack_name)
    except HubNotFoundError, HubShapeError:  # pragma: no cover — 库刚开过
        return set()
    found: set[int] = set()
    for slot in _slots_of(parse_segments(str(row.get("in_pack_slot") or ""))):
        if pack.read(slot).kind == BODY_SLOT:
            found.add(slot)
    return found


def _rehome_body(engine: Engine, moved: dict[_Where, tuple[str, int]]) -> None:
    """扶正**正文索引的位置行**:它答的那份正文被搬动之后,那一行也得改.

    行自己落在索引块的槽里(由 `_rehome` 那一侧扶正),这里只改它答的**坐标**,
    并把新内容写回**同一格**——行不搬,故索引块的槽一个都不多.

    **没人要的行在这一趟摘掉**:位置行是推导出来的坐标,不是内容本身,故
    "还有没有摘要链指着它"是它该不该在的唯一判据.**摘掉一个块时行留着**,
    由这一趟按引用判活;摘的是**装着没人要的那几行的索引块**(一块一行,
    行本身没有独立身份).
    """
    wanted = _wanted_bodies(engine)
    stale: set[tuple[str, str]] = set()
    for digest_value, slot, row_hub, row_pack, placement in _each_body_placement(engine):
        if digest_value not in wanted:
            stale.add((row_hub, row_pack))
            continue
        if not _rehome_one_body(placement, moved):
            continue
        content = encode_index_row(placement | {COLUMN_KEY: _body_column()})
        pack = Hub.open(engine.root / row_hub).pack(row_pack)
        if len(content) > pack.content_room:  # pragma: no cover — 行只换坐标,长度不涨
            raise SlotTooLargeError(
                f"一条索引行装不下: {len(content)} 字节（可用 {pack.content_room}）"
            )
        pack.overwrite(slot, ATTR_SLOT, content)
    _drop_body_index_blocks(engine, stale)


def _drop_body_index_blocks(engine: Engine, stale: set[tuple[str, str]]) -> None:
    """摘掉**只剩没人要的位置行**的索引块:位置行是推导出来的坐标,不是内容本身."""
    if not stale:
        return
    table = _body_index_table()
    for row in tuple(engine.index.rows(table)):
        hub_name = str(row.get("in_hub") or "")
        pack_name = str(row.get("in_hub_pack") or "")
        if (hub_name, pack_name) not in stale:
            continue
        engine.delete(ID(table, value_uuid=str(row.get("value_uuid") or "")))


def _rehome_one_body(placement: dict[str, object], moved: dict[_Where, tuple[str, int]]) -> bool:
    """把一份正文的坐标换成新落点;真改了才返回真."""
    hub_name = str(placement.get(HUB_KEY) or "")
    pack_name = str(placement.get(PACK_KEY) or "")
    segments = decode_segments(placement.get(SEGMENTS_KEY))
    if not hub_name or not pack_name or not segments:
        return False
    targets: list[int] = []
    new_pack = pack_name
    changed = False
    for slot in _slots_of(segments):
        where = moved.get((hub_name, pack_name, slot))
        if where is None:
            targets.append(slot)
            continue
        changed = True
        new_pack = where[0]
        targets.append(where[1])
    if not changed:
        return False
    placement[PACK_KEY] = new_pack
    placement[SEGMENTS_KEY] = encode_segments(canonical_segments(targets))
    return True


def _merge_groups(groups: Iterable[Iterable[int]]) -> list[int | tuple[int, int]]:
    """按分组把槽号折成段列表(组内相邻者并段,组与组之间不并)."""
    return [item for group in groups for item in _merge(group)]


def _merge(slots: Iterable[int]) -> list[int | tuple[int, int]]:
    """把一串槽号折成段(相邻者并段),次序照给的次序."""
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


def _text_of_segments(spans: Iterable[int | tuple[int, int]]) -> str:
    """把段列表折成文本:单格写一个数,连续的一段写 `起-止`."""
    parts: list[str] = []
    for item in spans:
        if isinstance(item, int):
            parts.append(str(item))
            continue
        parts.append(f"{item[0]}-{item[1]}")
    return ",".join(parts)


def _forget_the_dead(engine: Engine, live: set[_Where]) -> None:
    """摘掉位置段已全部不在活口里的行:**那些身份已经没有字节了**.

    **只动身份表**:库自用的那两张(`hub` 与 `meta`)不动.
    """
    for table in _identity_tables(engine):
        for row in tuple(engine.index.rows(table)):
            identity = ID.from_row(row)
            if not identity.in_hub or not identity.in_hub_pack:
                continue
            if any(
                (identity.in_hub, identity.in_hub_pack, slot) in live
                for slot in _slots_of(identity.in_pack_slot)
            ):
                continue
            engine.index.drop_row(table, identity.value_uuid)


def _slots_of(spans: Iterable[int | tuple[int, int]]) -> tuple[int, ...]:
    """把段列表展开成升序的一串槽号."""
    found: list[int] = []
    for item in spans:
        if isinstance(item, int):
            found.append(item)
            continue
        found.extend(range(item[0], item[1] + 1))
    return tuple(found)


def _int(value: object) -> int:
    """把整数字段读回:缺失取 0."""
    return 0 if value in {None, ""} else int(str(value))


__all__ = ["SweepReport", "reclaimable_bytes", "sweep"]

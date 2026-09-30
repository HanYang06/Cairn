# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""索引库的行层：块行、内容行、hub 登记与关系边。

**两张身份表**（设计篇 §8.1.2）：`block` 管"块在哪儿、它指向哪份内容"，
`body` 管"那份内容在哪儿"。表结构与建表语句全在声明层（`tables.py` 与 `tablegen.py`）；
本模块只**按声明的列名读写**，故这里出现的表名只是"行层用到的对象"，不是结构本体。

四条与设计篇对齐的口径：

- **定位行是投影**（§8.1、§9.2）：一行交出"身份 → 在哪儿"，正文一律不进库。
  一条记录占一行：块记录进 `block` 表、内容记录进 `body` 表，故顺扫能逐条补行；
- **指针落成两列**（§3.2.1）：块行带 `body_value_uuid` / `body_value_hash`，
  于是"这份内容被哪些块引用"在块表里一次查得到，不必读载荷；
- **hub 登记是登记**（§6）：同一个 hub 再登记**不改写**它——登记记的是"第一次见到它"，
  真源是目录本身；
- **边身份是摘要**（§8.2）：同一关系重复写不产生第二行，主键即身份，故写入是幂等的。

**提交口径**：每个写方法自己提交一次（一次写入即一次落盘）。本层不做跨行事务——
批量写入要合并成一次提交时，由上层显式包一层（:meth:`Rows.batch`）；
档一重建（:func:`rebuild`）正是这样的批量场景，整轮补行只提交一次。

**档一重建**（§8.5）也在此：以载体为真源，**只补缺行**，已有行一律不动；
重扫补回的是"身份＋位置"，`kind` 与落盘时刻不在记录头里，只能给空值（未知即降级）。
判据落在载荷上（带指针的是块），故类型为空也认得出。坏点即停：:meth:`Hub.scan`
自己抛，已补的行留在库里，重跑幂等。
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.clock import now_ms

from .carrier import SlotRange
from .format.block import body_ref_of
from .format.record import decode
from .registry import BLOCK_TABLE, BODY_TABLE
from .tables import quote_identifier

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Iterator

    from .hub import Hub

HUB_TABLE = "hub"
"""hub 登记所在表。"""

EDGE_TABLE = "edge"
"""关系边所在表。"""

DEFAULT_HUB_ROLE = "main"
"""默认 hub 角色：主 hub。短命 hub 与合并为未来项。"""

DEFAULT_HUB_STATE = "active"
"""默认登记状态：在用。"""

_BLOCK_COLUMNS = (
    "value_uuid, value_hash, body_value_uuid, body_value_hash, kind, hub, pack, "
    "slot_first, slot_last, size, birth_time, created, updated"
)
_BODY_COLUMNS = (
    "value_uuid, value_hash, hub, pack, slot_first, slot_last, size, birth_time, created, updated"
)
_HUB_COLUMNS = "name, role, state, created"
_EDGE_COLUMNS = "id, src_value_uuid, dst_value_uuid, kind, domain, created"

# 语句一律在这里拼好：表名来自登记表并经 quote_identifier 加引号，值全部参数化。
# 调用点只传常量，故没有"现场拼 SQL"的地方（也就没有注入面）。
_INSERT_BLOCK = f"""
INSERT INTO {quote_identifier(BLOCK_TABLE)} ({_BLOCK_COLUMNS})
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(value_uuid) DO UPDATE SET
    value_hash = excluded.value_hash,
    body_value_uuid = excluded.body_value_uuid,
    body_value_hash = excluded.body_value_hash,
    kind = excluded.kind,
    hub = excluded.hub,
    pack = excluded.pack,
    slot_first = excluded.slot_first,
    slot_last = excluded.slot_last,
    size = excluded.size,
    updated = excluded.updated
"""
"""同身份重写：位置、摘要与指针跟着更新；`birth_time` 与 `created` 保持第一次写下的值。"""

_INSERT_BODY = f"""
INSERT INTO {quote_identifier(BODY_TABLE)} ({_BODY_COLUMNS})
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(value_uuid) DO UPDATE SET
    value_hash = excluded.value_hash,
    hub = excluded.hub,
    pack = excluded.pack,
    slot_first = excluded.slot_first,
    slot_last = excluded.slot_last,
    size = excluded.size,
    updated = excluded.updated
"""
"""同身份重写：位置与摘要跟着更新；`birth_time` 与 `created` 保持第一次写下的值。"""

_SELECT_BLOCK = f"SELECT {_BLOCK_COLUMNS} FROM {quote_identifier(BLOCK_TABLE)} WHERE value_uuid = ?"
_SELECT_BODY = f"SELECT {_BODY_COLUMNS} FROM {quote_identifier(BODY_TABLE)} WHERE value_uuid = ?"
_SELECT_BODIES_BY_HASH = (
    f"SELECT {_BODY_COLUMNS} FROM {quote_identifier(BODY_TABLE)} "
    "WHERE value_hash = ? ORDER BY birth_time, value_uuid"
)
"""按内容地址反查内容行：内容寻址与去重共用这一处。"""
_SELECT_BLOCKS_BY_BODY = (
    f"SELECT {_BLOCK_COLUMNS} FROM {quote_identifier(BLOCK_TABLE)} "
    "WHERE body_value_hash = ? ORDER BY birth_time, value_uuid"
)
"""按内容地址反查块行：这份内容被哪些块引用（指针落成两列才查得到）。"""
_COUNT_BLOCKS = f"SELECT COUNT(*) AS n FROM {quote_identifier(BLOCK_TABLE)}"
_COUNT_BODIES = f"SELECT COUNT(*) AS n FROM {quote_identifier(BODY_TABLE)}"
_SELECT_ALL_BLOCKS = (
    f"SELECT {_BLOCK_COLUMNS} FROM {quote_identifier(BLOCK_TABLE)} "
    "ORDER BY hub, pack, slot_first, value_uuid"
)
_SELECT_ALL_BODIES = (
    f"SELECT {_BODY_COLUMNS} FROM {quote_identifier(BODY_TABLE)} "
    "ORDER BY hub, pack, slot_first, value_uuid"
)
_DELETE_BLOCK = f"DELETE FROM {quote_identifier(BLOCK_TABLE)} WHERE value_uuid = ?"
_DELETE_BODY = f"DELETE FROM {quote_identifier(BODY_TABLE)} WHERE value_uuid = ?"
_MOVE_BLOCK = (
    f"UPDATE {quote_identifier(BLOCK_TABLE)} "
    "SET hub = ?, pack = ?, slot_first = ?, slot_last = ?, size = ?, updated = ? "
    "WHERE value_uuid = ?"
)
"""只改坐标：身份、类型标号与三个时刻都不动。"""
_MOVE_BODY = (
    f"UPDATE {quote_identifier(BODY_TABLE)} "
    "SET hub = ?, pack = ?, slot_first = ?, slot_last = ?, size = ?, updated = ? "
    "WHERE value_uuid = ?"
)
"""只改坐标：身份与两个时刻都不动。"""

_INSERT_HUB = (
    f"INSERT INTO {quote_identifier(HUB_TABLE)} ({_HUB_COLUMNS}) VALUES (?, ?, ?, ?) "
    "ON CONFLICT(name) DO NOTHING"
)
"""登记一旦写下就不改写：重复登记是空操作。"""

_SELECT_HUB = f"SELECT {_HUB_COLUMNS} FROM {quote_identifier(HUB_TABLE)} WHERE name = ?"
_SELECT_HUBS = f"SELECT {_HUB_COLUMNS} FROM {quote_identifier(HUB_TABLE)} ORDER BY name"

_INSERT_EDGE = (
    f"INSERT INTO {quote_identifier(EDGE_TABLE)} ({_EDGE_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(id) DO NOTHING"
)
"""边身份即主键：同一关系重复写不产生第二行。"""

_EDGES_FROM = (
    f"SELECT {_EDGE_COLUMNS} FROM {quote_identifier(EDGE_TABLE)} "
    "WHERE src_value_uuid = ? AND kind = ? ORDER BY created, id"
)
_EDGES_TO = (
    f"SELECT {_EDGE_COLUMNS} FROM {quote_identifier(EDGE_TABLE)} "
    "WHERE dst_value_uuid = ? AND kind = ? ORDER BY created, id"
)


@dataclass(frozen=True, slots=True)
class BlockRow:
    """一条块行：块的身份、它指向的 body、以及它自己那份记录的位置。

    Attributes:
        value_uuid: 块的分配形态凭证（主键）。
        value_hash: 块的摘要形态凭证（块记录载荷的摘要）。
        body_value_uuid: 指针指向的 body 的分配形态凭证。
        body_value_hash: 指针指向的 body 的摘要形态凭证（内容地址）。
        hub: 所属 hub。
        pack: 载体文件名。
        span: 载体内的格区间。
        size: 记录字节数。
        kind: 类型标号；由程序给出，重建补行时只能是空串（未知）。
        birth_time: ID 签发时刻（unix 纳秒）；记录头不带它，重建补行时为 0。
        created: 落盘时刻（unix 毫秒）；重建补行时为 0（未知）。
        updated: 最近一次改写时刻（unix 毫秒）。
    """

    value_uuid: str
    value_hash: str
    body_value_uuid: str
    body_value_hash: str
    hub: str
    pack: str
    span: SlotRange
    size: int
    kind: str = ""
    birth_time: int = 0
    created: int = 0
    updated: int = 0


@dataclass(frozen=True, slots=True)
class BodyRow:
    """一条内容行：body 的身份与它自己那份记录的位置。

    Attributes:
        value_uuid: body 的分配形态凭证（主键）。
        value_hash: body 的摘要形态凭证（内容地址，去重与反查都走它）。
        hub: 所属 hub。
        pack: 载体文件名。
        span: 载体内的格区间。
        size: 记录字节数。
        birth_time: ID 签发时刻（unix 纳秒）。
        created: 落盘时刻（unix 毫秒）。
        updated: 最近一次改写时刻（unix 毫秒）。
    """

    value_uuid: str
    value_hash: str
    hub: str
    pack: str
    span: SlotRange
    size: int
    birth_time: int = 0
    created: int = 0
    updated: int = 0


@dataclass(frozen=True, slots=True)
class HubRow:
    """一条 hub 登记。

    Attributes:
        name: hub 名（目录名，主键）。
        role: 角色；主 hub / 短命 hub（后者为未来项）。
        state: 状态；在用 / 已合并（后者为未来项）。
        created: 第一次见到它的时刻（unix 毫秒）。
    """

    name: str
    role: str = DEFAULT_HUB_ROLE
    state: str = DEFAULT_HUB_STATE
    created: int = 0


@dataclass(frozen=True, slots=True)
class EdgeRow:
    """一条关系边。

    Attributes:
        id: 边身份摘要（主键，由 ``(src, dst, kind, domain)`` 算出）。
        src: 起点 ID。
        dst: 终点 ID。
        kind: 关系种类。
        domain: 所属领域。
        created: 建立时刻（unix 毫秒）。
    """

    id: str
    src: str
    dst: str
    kind: str
    domain: str = ""
    created: int = 0


@dataclass(frozen=True, slots=True)
class RebuildReport:
    """一次档一重建的结果。

    Attributes:
        registered_hubs: 本次补登记的 hub。
        added_blocks: 本次补回的块行（按 value_uuid）。
        added_bodies: 本次补回的内容行（按 value_uuid）。
        scanned: 扫过的记录条数。
    """

    registered_hubs: tuple[str, ...] = ()
    added_blocks: tuple[str, ...] = ()
    added_bodies: tuple[str, ...] = ()
    scanned: int = 0

    @property
    def changed(self) -> bool:
        """本次重建有没有真的补上东西。"""
        return bool(self.registered_hubs or self.added_blocks or self.added_bodies)


class Rows:
    """索引库的行层：一条已对齐连接上的读写。

    由 :attr:`Index.rows` 构造，不单独开连接。
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        """绑定一个已对齐的连接。"""
        self._connection = connection
        self._batch_depth = 0

    # ---- 批量：把一批写合并成一次提交 ----

    @contextlib.contextmanager
    def batch(self) -> Iterator[None]:
        """进入批量：块内的写方法不再各自提交，退出时**统一提交一次**。

        模块口径是"每个写方法自己提交一次"，跨行事务由上层显式包——批量场景（档一重建、
        将来的压实与合并）正是那个上层。嵌套进入按外层记账，只有最外层退出才落盘。

        中途抛出时**照样提交已写的部分**：本层的批量场景承诺"已补的行留在库里、重跑幂等"，
        回滚反而把这次已核对过的结果一并丢掉。
        """
        self._batch_depth += 1
        try:
            yield
        finally:
            self._batch_depth -= 1
            if self._batch_depth == 0:
                self._connection.commit()

    def _commit(self) -> None:
        """提交一次；批量块（:meth:`batch`）内先记账，等整批退出时统一提交。"""
        if self._batch_depth == 0:
            self._connection.commit()

    # ---- 块行 ----

    def put_block(self, row: BlockRow) -> None:
        """写入或改写一条块行（同一 `value_uuid` 即同一身份）。"""
        self._connection.execute(_INSERT_BLOCK, _block_values(row))
        self._commit()

    def block(self, value_uuid: str) -> BlockRow | None:
        """按身份取一条块行；没有即 ``None``。"""
        found = self._connection.execute(_SELECT_BLOCK, (value_uuid,)).fetchone()
        return None if found is None else _block(found)

    def blocks_by_body(self, body_hash: str) -> tuple[BlockRow, ...]:
        """按内容地址反查块行：这份内容被哪些块引用。"""
        found = self._connection.execute(_SELECT_BLOCKS_BY_BODY, (body_hash,)).fetchall()
        return tuple(_block(row) for row in found)

    def drop_block(self, value_uuid: str) -> bool:
        """摘掉一条块行；返回是否确实摘掉了一行。"""
        cursor = self._connection.execute(_DELETE_BLOCK, (value_uuid,))
        self._commit()
        return cursor.rowcount > 0

    def move_block(self, row: BlockRow, *, updated: int | None = None) -> bool:
        """**只改坐标**：按 `row` 里的位置挪这一行；返回是否确实改到了一行。

        处置"坐标不符"用它：把行挪到载体里的实际位置，而不是整行重写——整行重写会把
        类型标号冲掉，而类型是程序给的信息，重扫补不回来（§3.5、§8.7）。身份、类型标号
        与 `birth_time` / `created` 一律不动，只刷新 `updated`。
        """
        cursor = self._connection.execute(
            _MOVE_BLOCK, (*_coordinates(row, updated), row.value_uuid)
        )
        self._commit()
        return cursor.rowcount > 0

    # ---- 内容行 ----

    def put_body(self, row: BodyRow) -> None:
        """写入或改写一条内容行（同一 `value_uuid` 即同一身份）。"""
        self._connection.execute(_INSERT_BODY, _body_values(row))
        self._commit()

    def body(self, value_uuid: str) -> BodyRow | None:
        """按身份取一条内容行；没有即 ``None``。"""
        found = self._connection.execute(_SELECT_BODY, (value_uuid,)).fetchone()
        return None if found is None else _body(found)

    def bodies_by_hash(self, value_hash: str) -> tuple[BodyRow, ...]:
        """按内容地址反查内容行；去重与"按地址读内容"都走它。"""
        found = self._connection.execute(_SELECT_BODIES_BY_HASH, (value_hash,)).fetchall()
        return tuple(_body(row) for row in found)

    def move_body(self, row: BodyRow, *, updated: int | None = None) -> bool:
        """**只改坐标**：按 `row` 里的位置挪这一行；身份与两个时刻都不动。"""
        cursor = self._connection.execute(_MOVE_BODY, (*_coordinates(row, updated), row.value_uuid))
        self._commit()
        return cursor.rowcount > 0

    # ---- 两张表合起来看 ----

    def blocks(self) -> tuple[BlockRow, ...]:
        """全部块行，按 ``(hub, 载体, 起始格, 身份)`` 排序（巡检与诊断用）。"""
        return tuple(_block(row) for row in self._connection.execute(_SELECT_ALL_BLOCKS).fetchall())

    def bodies(self) -> tuple[BodyRow, ...]:
        """全部内容行，按 ``(hub, 载体, 起始格, 身份)`` 排序（巡检与诊断用）。"""
        return tuple(_body(row) for row in self._connection.execute(_SELECT_ALL_BODIES).fetchall())

    def count_blocks(self) -> int:
        """块行总数（诊断与巡检用）。"""
        return _count(self._connection, _COUNT_BLOCKS)

    def count_bodies(self) -> int:
        """内容行总数（诊断与巡检用）。"""
        return _count(self._connection, _COUNT_BODIES)

    def count_locations(self) -> int:
        """定位行总数：两张身份表之和（诊断用）。"""
        return self.count_blocks() + self.count_bodies()

    # ---- hub 登记 ----

    def register_hub(
        self,
        name: str,
        *,
        role: str = DEFAULT_HUB_ROLE,
        state: str = DEFAULT_HUB_STATE,
        created: int | None = None,
    ) -> bool:
        """登记一个 hub；**已经登记过就不改写它**，返回是否新登记。

        登记记的是"第一次见到它"；改形态是另一个显式动作（尚未落地）。
        """
        cursor = self._connection.execute(
            _INSERT_HUB,
            (name, role, state, now_ms() if created is None else created),
        )
        self._commit()
        return cursor.rowcount > 0

    def hub(self, name: str) -> HubRow | None:
        """按名取一条 hub 登记；没有即 ``None``。"""
        row = self._connection.execute(_SELECT_HUB, (name,)).fetchone()
        return None if row is None else _hub(row)

    def hubs(self) -> tuple[HubRow, ...]:
        """全部 hub 登记，按名排序。"""
        return tuple(_hub(row) for row in self._connection.execute(_SELECT_HUBS).fetchall())

    # ---- 关系边 ----

    def put_edge(self, edge: EdgeRow) -> bool:
        """写入一条关系边；同一身份（`id`）重复写不产生第二行。返回是否新写入。"""
        cursor = self._connection.execute(
            _INSERT_EDGE,
            (
                edge.id,
                edge.src,
                edge.dst,
                edge.kind,
                edge.domain,
                now_ms() if edge.created == 0 else edge.created,
            ),
        )
        self._commit()
        return cursor.rowcount > 0

    def edges_from(self, src: str, kind: str) -> tuple[EdgeRow, ...]:
        """出边：按 ``(src, kind)`` 查。"""
        return self._edges(_EDGES_FROM, src, kind)

    def edges_to(self, dst: str, kind: str) -> tuple[EdgeRow, ...]:
        """入边（反查）：按 ``(dst, kind)`` 查。"""
        return self._edges(_EDGES_TO, dst, kind)

    def _edges(self, statement: str, value: str, kind: str) -> tuple[EdgeRow, ...]:
        """按起点或终点查边；两条语句都在模块级拼好，列名不在这里出现。"""
        rows = self._connection.execute(statement, (value, kind)).fetchall()
        return tuple(_edge(row) for row in rows)


def rebuild(rows: Rows, hubs: Iterable[Hub], *, now: int | None = None) -> RebuildReport:
    """档一重建：以载体为真源，**只补缺行**。

    - hub 目录在、登记缺 → 补登记（登记是投影，真源是目录）；
    - 盘上有记录、库里没有行 → 按记录补行：身份与位置照实填，`kind` 与落盘时刻给空值
      （它们不在记录头里，编不出来）；
    - **已有行一律不动**：清空重扫要由程序按 ID 给出类型，属 ID 专项（§12）。

    进哪张表**由载荷判断**（§3.2.1）：带指针的是块记录，进 `block`；其余是内容记录，进
    `body`。判据落在载荷上，故类型为空也认得出。坏点即停：遇到读不出底来的载体即抛，
    已补的行照旧留在库里（整批提交一次），重跑幂等。

    两类开销在这一层各自消掉：**已有身份集合进循环前一次预载**——逐条 `SELECT` 在大库里是
    N+1 查询；**整轮补行包在一层 :meth:`Rows.batch` 里**——逐行提交就是逐行 fsync。
    """
    stamp = now_ms() if now is None else now
    registered: list[str] = []
    blocks: list[str] = []
    bodies: list[str] = []
    scanned = 0

    # 进循环前一次读全：判"缺不缺"用集合，O(1)；扫描中补上的身份同样记进集合，
    # 免得同一身份在两处出现时被补成两行。
    known_blocks = {row.value_uuid for row in rows.blocks()}
    known_bodies = {row.value_uuid for row in rows.bodies()}
    with rows.batch():
        for hub in hubs:
            if rows.hub(hub.name) is None:
                rows.register_hub(hub.name, created=stamp)
                registered.append(hub.name)
            for pack, span, raw in hub.scan():
                scanned += 1
                record = decode(raw)
                pointer = body_ref_of(record.payload)
                value_uuid = record.id.value_uuid
                if pointer is None:
                    if value_uuid not in known_bodies:
                        rows.put_body(
                            BodyRow(
                                value_uuid=value_uuid,
                                value_hash=record.id.value_hash,
                                hub=hub.name,
                                pack=pack,
                                span=span,
                                size=len(raw),
                                birth_time=record.id.birth_time,
                            )
                        )
                        known_bodies.add(value_uuid)
                        bodies.append(value_uuid)
                    continue
                if value_uuid not in known_blocks:
                    rows.put_block(
                        BlockRow(
                            value_uuid=value_uuid,
                            value_hash=record.id.value_hash,
                            body_value_uuid=pointer.value_uuid,
                            body_value_hash=pointer.value_hash,
                            hub=hub.name,
                            pack=pack,
                            span=span,
                            size=len(raw),
                            birth_time=record.id.birth_time,
                        )
                    )
                    known_blocks.add(value_uuid)
                    blocks.append(value_uuid)

    return RebuildReport(
        registered_hubs=tuple(registered),
        added_blocks=tuple(blocks),
        added_bodies=tuple(bodies),
        scanned=scanned,
    )


def _coordinates(row: BlockRow | BodyRow, updated: int | None) -> tuple[object, ...]:
    """挪行要写的那几个坐标值（两张表共用同一套）。"""
    return (
        row.hub,
        row.pack,
        row.span.first,
        row.span.last,
        row.size,
        now_ms() if updated is None else updated,
    )


def _count(connection: sqlite3.Connection, statement: str) -> int:
    """跑一条计数语句。"""
    row = connection.execute(statement).fetchone()
    return 0 if row is None else int(row["n"])


def _block_values(row: BlockRow) -> tuple[object, ...]:
    """块行写库时的参数顺序，与 `_BLOCK_COLUMNS` 逐一对应。"""
    return (
        row.value_uuid,
        row.value_hash,
        row.body_value_uuid,
        row.body_value_hash,
        row.kind,
        row.hub,
        row.pack,
        row.span.first,
        row.span.last,
        row.size,
        row.birth_time,
        row.created,
        row.updated,
    )


def _body_values(row: BodyRow) -> tuple[object, ...]:
    """内容行写库时的参数顺序，与 `_BODY_COLUMNS` 逐一对应。"""
    return (
        row.value_uuid,
        row.value_hash,
        row.hub,
        row.pack,
        row.span.first,
        row.span.last,
        row.size,
        row.birth_time,
        row.created,
        row.updated,
    )


def _block(row: sqlite3.Row) -> BlockRow:
    """把一行读成块行。"""
    return BlockRow(
        value_uuid=str(row["value_uuid"]),
        value_hash=str(row["value_hash"]),
        body_value_uuid=str(row["body_value_uuid"] or ""),
        body_value_hash=str(row["body_value_hash"] or ""),
        hub=str(row["hub"]),
        pack=str(row["pack"]),
        span=SlotRange(first=int(row["slot_first"]), last=int(row["slot_last"])),
        size=int(row["size"]),
        kind=str(row["kind"] or ""),
        birth_time=int(row["birth_time"] or 0),
        created=int(row["created"] or 0),
        updated=int(row["updated"] or 0),
    )


def _body(row: sqlite3.Row) -> BodyRow:
    """把一行读成内容行。"""
    return BodyRow(
        value_uuid=str(row["value_uuid"]),
        value_hash=str(row["value_hash"]),
        hub=str(row["hub"]),
        pack=str(row["pack"]),
        span=SlotRange(first=int(row["slot_first"]), last=int(row["slot_last"])),
        size=int(row["size"]),
        birth_time=int(row["birth_time"] or 0),
        created=int(row["created"] or 0),
        updated=int(row["updated"] or 0),
    )


def _hub(row: sqlite3.Row) -> HubRow:
    """把一行读成 hub 登记。"""
    return HubRow(
        name=str(row["name"]),
        role=str(row["role"] or ""),
        state=str(row["state"] or ""),
        created=int(row["created"] or 0),
    )


def _edge(row: sqlite3.Row) -> EdgeRow:
    """把一行读成关系边。"""
    return EdgeRow(
        id=str(row["id"]),
        src=str(row["src_value_uuid"]),
        dst=str(row["dst_value_uuid"]),
        kind=str(row["kind"]),
        domain=str(row["domain"] or ""),
        created=int(row["created"] or 0),
    )


__all__ = [
    "BLOCK_TABLE",
    "BODY_TABLE",
    "DEFAULT_HUB_ROLE",
    "DEFAULT_HUB_STATE",
    "EDGE_TABLE",
    "HUB_TABLE",
    "BlockRow",
    "BodyRow",
    "EdgeRow",
    "HubRow",
    "RebuildReport",
    "Rows",
    "rebuild",
]

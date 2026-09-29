# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""索引库的行层：定位行、hub 登记与关系边。

表结构与建表语句全在声明层（`tables.py`）；本模块只**按声明的列名读写**，
故这里出现的表名只是"行层用到的对象"，不是结构本体。三条与设计篇对齐的口径：

- **定位行是投影**（§8.1、§9.2）：一行交出"身份 → 在哪儿"，正文一律不进库。
  位置是 ``(hub, pack, slot_first, slot_last)`` 四项加两套凭证；同内容可有多行
  （同 `value_hash`、不同 `value_uuid`），故按 `value_hash` 建的是**非唯一**索引；
- **hub 登记是登记**（§6）：同一个 hub 再登记**不改写**它——登记记的是"第一次见到它"，
  真源是目录本身；
- **边身份是摘要**（§8.2）：同一关系重复写不产生第二行，主键即身份，故写入是幂等的。

**提交口径**：每个写方法自己提交一次（一次写入即一次落盘）。本层不做跨行事务——
批量写入要合并成一次提交时，由上层显式包一层（设计篇 §12 的批量与压实见未来项）。

**档一重建**（§8.5）也在此：以载体为真源，**只补缺行**，已有行一律不动；
重扫补回的是"身份＋位置"，`kind` 与落盘时刻不在记录头里，只能给空值（未知即降级）。
坏点即停（:meth:`Hub.scan` 自己抛），已补的行留在库里，重跑幂等。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.clock import now_ms

from .carrier import SlotRange
from .format.record import decode
from .tables import quote_identifier

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable

    from .hub import Hub

RECORD_TABLE = "record"
"""定位行所在表（表名来自声明层，这里只是常量）。"""

HUB_TABLE = "hub"
"""hub 登记所在表。"""

EDGE_TABLE = "edge"
"""关系边所在表。"""

DEFAULT_HUB_ROLE = "main"
"""默认 hub 角色：主 hub。短命 hub 与合并为未来项。"""

DEFAULT_HUB_STATE = "active"
"""默认登记状态：在用。"""

_LOCATION_COLUMNS = (
    "name, value_uuid, value_hash, kind, hub, pack, "
    "slot_first, slot_last, size, birth_time, created, updated"
)
_HUB_COLUMNS = "name, role, state, created"
_EDGE_COLUMNS = "id, src, dst, kind, domain, created"

# 语句一律在这里拼好：表名来自声明层并经 quote_identifier 加引号，值全部参数化。
# 调用点只传常量，故没有"现场拼 SQL"的地方（也就没有注入面）。
_INSERT_LOCATION = f"""
INSERT INTO {quote_identifier(RECORD_TABLE)} ({_LOCATION_COLUMNS})
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(name, value_uuid) DO UPDATE SET
    value_hash = excluded.value_hash,
    kind = excluded.kind,
    hub = excluded.hub,
    pack = excluded.pack,
    slot_first = excluded.slot_first,
    slot_last = excluded.slot_last,
    size = excluded.size,
    updated = excluded.updated
"""
"""同身份重写：位置与摘要跟着更新，`birth_time` 与 `created` 保持第一次写下的值。"""

_SELECT_LOCATION = (
    f"SELECT {_LOCATION_COLUMNS} FROM {quote_identifier(RECORD_TABLE)} "
    "WHERE value_uuid = ? ORDER BY name"
)
_SELECT_BY_HASH = (
    f"SELECT {_LOCATION_COLUMNS} FROM {quote_identifier(RECORD_TABLE)} "
    "WHERE value_hash = ? ORDER BY birth_time, value_uuid"
)
_COUNT_LOCATIONS = f"SELECT COUNT(*) AS n FROM {quote_identifier(RECORD_TABLE)}"
_SELECT_ALL_LOCATIONS = (
    f"SELECT {_LOCATION_COLUMNS} FROM {quote_identifier(RECORD_TABLE)} "
    "ORDER BY hub, pack, slot_first, value_uuid"
)
_DELETE_LOCATION = f"DELETE FROM {quote_identifier(RECORD_TABLE)} WHERE name = ? AND value_uuid = ?"
_DELETE_LOCATION_ANY_NAME = f"DELETE FROM {quote_identifier(RECORD_TABLE)} WHERE value_uuid = ?"
"""不带作用域名的摘除：一个凭证只该有一个身份，故通常也就一行。"""
_MOVE_LOCATION = (
    f"UPDATE {quote_identifier(RECORD_TABLE)} "
    "SET hub = ?, pack = ?, slot_first = ?, slot_last = ?, size = ?, updated = ? "
    "WHERE name = ? AND value_uuid = ?"
)
"""只改坐标：身份、类型标号与三个时刻都不动。"""

_MOVE_LOCATION_ANY_NAME = (
    f"UPDATE {quote_identifier(RECORD_TABLE)} "
    "SET hub = ?, pack = ?, slot_first = ?, slot_last = ?, size = ?, updated = ? "
    "WHERE value_uuid = ?"
)
"""不带作用域名的挪行：巡检只知道凭证（作用域名读不出来），照旧把这一行挪对。"""

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
    "WHERE src = ? AND kind = ? ORDER BY created, id"
)
_EDGES_TO = (
    f"SELECT {_EDGE_COLUMNS} FROM {quote_identifier(EDGE_TABLE)} "
    "WHERE dst = ? AND kind = ? ORDER BY created, id"
)


@dataclass(frozen=True, slots=True)
class Location:
    """一条定位行：身份＋位置。

    Attributes:
        name: 作用域名（引用方写下的名字，如 `block` / `body`）；与 `value_uuid` 合成主键。
        value_uuid: 分配形态凭证（主键的一半）。
        value_hash: 摘要形态凭证（非唯一索引：同内容可有多行）。
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
    hub: str
    pack: str
    span: SlotRange
    size: int
    name: str = ""
    kind: str = ""
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
        added_rows: 本次补回的定位行（按 value_uuid）。
        scanned: 扫过的记录条数。
    """

    registered_hubs: tuple[str, ...] = ()
    added_rows: tuple[str, ...] = ()
    scanned: int = 0

    @property
    def changed(self) -> bool:
        """本次重建有没有真的补上东西。"""
        return bool(self.registered_hubs or self.added_rows)


class Rows:
    """索引库的行层：一条已对齐连接上的读写。

    由 :attr:`Index.rows` 构造，不单独开连接。
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        """绑定一个已对齐的连接。"""
        self._connection = connection

    # ---- 定位行 ----

    def put_location(self, location: Location) -> None:
        """写入或改写一条定位行（同一 `(name, value_uuid)` 即同一身份）。"""
        self._connection.execute(
            _INSERT_LOCATION,
            (
                location.name,
                location.value_uuid,
                location.value_hash,
                location.kind,
                location.hub,
                location.pack,
                location.span.first,
                location.span.last,
                location.size,
                location.birth_time,
                location.created,
                location.updated,
            ),
        )
        self._connection.commit()

    def location(self, value_uuid: str) -> Location | None:
        """按身份取一条定位行；没有即 ``None``。

        只按凭证查、**不带作用域名**：凭证是签发时分配的，一个值只对应一个身份。
        同一个值真的出现在两个作用域下时，取按名字排序的第一行（诊断口径，够用）。
        """
        row = self._connection.execute(_SELECT_LOCATION, (value_uuid,)).fetchone()
        return None if row is None else _location(row)

    def locations_by_hash(self, value_hash: str) -> tuple[Location, ...]:
        """按摘要反查：这份内容被哪些身份引用（去重与反查是同一处）。"""
        rows = self._connection.execute(_SELECT_BY_HASH, (value_hash,)).fetchall()
        return tuple(_location(row) for row in rows)

    def drop_location(self, value_uuid: str, *, name: str = "") -> bool:
        """摘掉一条定位行；返回是否确实摘掉了一行。

        `name` 给定即按作用域名精确摘；不给则摘该凭证名下的**全部**行
        （一个凭证只该有一个身份，故通常就是一行）。
        """
        if name:
            cursor = self._connection.execute(_DELETE_LOCATION, (name, value_uuid))
        else:
            cursor = self._connection.execute(_DELETE_LOCATION_ANY_NAME, (value_uuid,))
        self._connection.commit()
        return cursor.rowcount > 0

    def move_location(self, location: Location, *, updated: int | None = None) -> bool:
        """**只改坐标**：按 `location` 里的位置挪这一行；返回是否确实改到了一行。

        处置"坐标不符"用它：把行挪到载体里的实际位置，而不是整行重写——整行重写会把
        类型标号冲掉，而类型是程序给的信息，重扫补不回来（§3.5、§8.7）。身份、类型标号
        与 `birth_time` / `created` 一律不动，只刷新 `updated`。

        `location.name` 为空时按凭证挪（巡检从载体上读不出作用域名，见 §8.5）。
        """
        coordinates = (
            location.hub,
            location.pack,
            location.span.first,
            location.span.last,
            location.size,
            now_ms() if updated is None else updated,
        )
        if location.name:
            cursor = self._connection.execute(
                _MOVE_LOCATION, (*coordinates, location.name, location.value_uuid)
            )
        else:
            cursor = self._connection.execute(
                _MOVE_LOCATION_ANY_NAME, (*coordinates, location.value_uuid)
            )
        self._connection.commit()
        return cursor.rowcount > 0

    def locations(self) -> tuple[Location, ...]:
        """全部定位行，按 ``(hub, 载体, 起始格, 身份)`` 排序（巡检与诊断用）。"""
        return tuple(
            _location(row) for row in self._connection.execute(_SELECT_ALL_LOCATIONS).fetchall()
        )

    def count_locations(self) -> int:
        """定位行总数（诊断与巡检用）。"""
        row = self._connection.execute(_COUNT_LOCATIONS).fetchone()
        return 0 if row is None else int(row["n"])

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
        self._connection.commit()
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
        self._connection.commit()
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

    坏点即停：遇到读不出底来的载体即抛，已补的行留在库里，重跑幂等。
    """
    stamp = now_ms() if now is None else now
    registered: list[str] = []
    added: list[str] = []
    scanned = 0

    for hub in hubs:
        if rows.hub(hub.name) is None:
            rows.register_hub(hub.name, created=stamp)
            registered.append(hub.name)
        for pack, span, raw in hub.scan():
            scanned += 1
            record = decode(raw)
            if rows.location(record.id.value_uuid) is not None:
                continue
            rows.put_location(
                Location(
                    value_uuid=record.id.value_uuid,
                    value_hash=record.id.value_hash,
                    hub=hub.name,
                    pack=pack,
                    span=span,
                    size=len(raw),
                    birth_time=record.id.birth_time,
                )
            )
            added.append(record.id.value_uuid)

    return RebuildReport(
        registered_hubs=tuple(registered),
        added_rows=tuple(added),
        scanned=scanned,
    )


def _location(row: sqlite3.Row) -> Location:
    """把一行读成定位行。"""
    return Location(
        value_uuid=str(row["value_uuid"]),
        value_hash=str(row["value_hash"]),
        hub=str(row["hub"]),
        pack=str(row["pack"]),
        span=SlotRange(first=int(row["slot_first"]), last=int(row["slot_last"])),
        size=int(row["size"]),
        name=str(row["name"] or ""),
        kind=str(row["kind"] or ""),
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
        src=str(row["src"]),
        dst=str(row["dst"]),
        kind=str(row["kind"]),
        domain=str(row["domain"] or ""),
        created=int(row["created"] or 0),
    )


__all__ = [
    "DEFAULT_HUB_ROLE",
    "DEFAULT_HUB_STATE",
    "EDGE_TABLE",
    "HUB_TABLE",
    "RECORD_TABLE",
    "EdgeRow",
    "HubRow",
    "Location",
    "RebuildReport",
    "Rows",
    "rebuild",
]

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
重扫能把行上的每一列都补回来——身份字段与类型标号都在记录里（§3.5），
位置由"在哪个载体的哪一格被扫到"给出。判据落在载荷上（带指针的是块），
故类型为空也认得出。坏点即停：:meth:`Hub.scan`
自己抛，已补的行留在库里，重跑幂等。
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

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

#: 身份列的书写顺序 = `ID` 的字段顺序（`ID_FIELDS`）：库里的行是 ID 的镜像，逐列照搬。
_ID_COLUMNS = "name, value_uuid, value_hash, birth_time, in_hub, in_hub_pack, in_pack_slot"

_BLOCK_COLUMNS = f"{_ID_COLUMNS}, body_value_uuid, body_value_hash, kind"
_BODY_COLUMNS = _ID_COLUMNS
_HUB_COLUMNS = "name"

# 语句一律在这里拼好：表名来自登记表并经 quote_identifier 加引号，值全部参数化。
# 调用点只传常量，故没有"现场拼 SQL"的地方（也就没有注入面）。
_INSERT_BLOCK = f"""
INSERT INTO {quote_identifier(BLOCK_TABLE)} ({_BLOCK_COLUMNS})
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(value_uuid) DO UPDATE SET
    name = excluded.name,
    value_hash = excluded.value_hash,
    in_hub = excluded.in_hub,
    in_hub_pack = excluded.in_hub_pack,
    in_pack_slot = excluded.in_pack_slot,
    body_value_uuid = excluded.body_value_uuid,
    body_value_hash = excluded.body_value_hash,
    kind = excluded.kind
"""
"""同身份重写：ID 的可变字段（名字、摘要、位置段）与指针、类型标号都跟着更新；
`birth_time` 是签发时刻，一写定就不再改写——那会让一个旧身份看起来变年轻。"""

_INSERT_BODY = f"""
INSERT INTO {quote_identifier(BODY_TABLE)} ({_BODY_COLUMNS})
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(value_uuid) DO UPDATE SET
    name = excluded.name,
    value_hash = excluded.value_hash,
    in_hub = excluded.in_hub,
    in_hub_pack = excluded.in_hub_pack,
    in_pack_slot = excluded.in_pack_slot
"""
"""同身份重写：ID 的可变字段跟着更新；`birth_time` 同上，不动。"""

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
    "ORDER BY in_hub, in_hub_pack, value_uuid"
)
"""全部块行。**格号不参与排序**：它存成文本，字典序与数值序不是一回事；
排序键取 hub、载体与身份，够定位、也够稳定。"""
_SELECT_ALL_BODIES = (
    f"SELECT {_BODY_COLUMNS} FROM {quote_identifier(BODY_TABLE)} "
    "ORDER BY in_hub, in_hub_pack, value_uuid"
)
_DELETE_BLOCK = f"DELETE FROM {quote_identifier(BLOCK_TABLE)} WHERE value_uuid = ?"
_DELETE_BODY = f"DELETE FROM {quote_identifier(BODY_TABLE)} WHERE value_uuid = ?"
_MOVE_BLOCK = (
    f"UPDATE {quote_identifier(BLOCK_TABLE)} "
    "SET in_hub = ?, in_hub_pack = ?, in_pack_slot = ? "
    "WHERE value_uuid = ?"
)
"""只改坐标：身份、摘要、指针与类型标号都不动，只把位置段换成实际位置。"""
_MOVE_BODY = (
    f"UPDATE {quote_identifier(BODY_TABLE)} "
    "SET in_hub = ?, in_hub_pack = ?, in_pack_slot = ? "
    "WHERE value_uuid = ?"
)
"""只改坐标：身份与摘要都不动。"""

_INSERT_HUB = (
    f"INSERT INTO {quote_identifier(HUB_TABLE)} ({_HUB_COLUMNS}) VALUES (?) "
    "ON CONFLICT(name) DO NOTHING"
)
"""登记一旦写下就不改写：重复登记是空操作。**只记名字**——
它是"这个 hub 存在过"的索引，真源始终是那个目录（§三：索引不得揣着推不回来的值）。"""

_SELECT_HUB = f"SELECT {_HUB_COLUMNS} FROM {quote_identifier(HUB_TABLE)} WHERE name = ?"
_SELECT_HUBS = f"SELECT {_HUB_COLUMNS} FROM {quote_identifier(HUB_TABLE)} ORDER BY name"


@dataclass(frozen=True, slots=True)
class BlockRow:
    """一条块行：**ID 的镜像** ＋ 它指向哪份内容 ＋ 类型标号。

    字段与顺序照 `ID` 的声明搬（`ID_FIELDS`），故"ID 里的某个字段进不了库"不成立：
    位置段三列就是 `in_hub` / `in_hub_pack` / `in_pack_slot`，不再改名另立一套。
    位置段里的那对格号在库里写成文本（`头格:末格`），进出各转一次。

    Attributes:
        name: 可读名称；由所在容器给出，可为空。
        value_uuid: 块的分配形态凭证（主键）。
        value_hash: 块的摘要形态凭证（块记录载荷的摘要）。
        birth_time: ID 签发时刻（unix 纳秒）；记录头不带它，重建补行时为 0。
        in_hub: 所属 hub（目录名）。
        in_hub_pack: hub 内的载体文件名。
        in_pack_slot: 载体内的格区间（头格，末格），闭区间。
        body_value_uuid: 指针指向的 body 的分配形态凭证。
        body_value_hash: 指针指向的 body 的摘要形态凭证（内容地址）。
        kind: 类型标号；由程序给出，重建补行时只能是空串（未知）。
    """

    name: str
    value_uuid: str
    value_hash: str
    birth_time: int
    in_hub: str
    in_hub_pack: str
    in_pack_slot: tuple[int, int]
    body_value_uuid: str
    body_value_hash: str
    kind: str = ""

    @property
    def span(self) -> SlotRange:
        """格区间（载体层要的形态）：库里那份文本在这里还原。"""
        return SlotRange(first=self.in_pack_slot[0], last=self.in_pack_slot[1])


@dataclass(frozen=True, slots=True)
class BodyRow:
    """一条内容行：**ID 的镜像**，没有指针也没有类型标号。

    字段与顺序同上，故两张身份表的形状差就是"块多一个指向与一个类型标号"。

    Attributes:
        name: 可读名称；由所在容器给出，可为空。
        value_uuid: body 的分配形态凭证（主键）。
        value_hash: body 的摘要形态凭证（内容地址，去重与反查都走它）。
        birth_time: ID 签发时刻（unix 纳秒）；记录头不带它，重建补行时为 0。
        in_hub: 所属 hub（目录名）。
        in_hub_pack: hub 内的载体文件名。
        in_pack_slot: 载体内的格区间（头格，末格），闭区间。
    """

    name: str
    value_uuid: str
    value_hash: str
    birth_time: int
    in_hub: str
    in_hub_pack: str
    in_pack_slot: tuple[int, int]

    @property
    def span(self) -> SlotRange:
        """格区间（载体层要的形态）：库里那份文本在这里还原。"""
        return SlotRange(first=self.in_pack_slot[0], last=self.in_pack_slot[1])


@dataclass(frozen=True, slots=True)
class HubRow:
    """一条 hub 登记：**只有名字**。

    它是"存在过哪些 hub"的索引，真源是 vault 下那些目录（扫一遍即得）。
    角色、状态、第一次见到的时刻都推不出来，故**不进这张表**——索引不得揣着推不回来的值
    （短命 hub 与合并落地时，那些事实的真源要放在 hub 目录里，再由索引投影）。

    Attributes:
        name: hub 名（目录名，主键）。
    """

    name: str


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

    def move_block(self, row: BlockRow) -> bool:
        """**只改坐标**：按 `row` 的位置段挪这一行；返回是否确实改到了一行。

        处置"坐标不符"用它：把行挪到载体里的实际位置，而不是整行重写——整行重写会把
        类型标号冲掉，而类型是程序给的信息，重扫补不回来（§3.5、§8.7）。
        身份、摘要、指针与 `birth_time` 一律不动。
        """
        cursor = self._connection.execute(_MOVE_BLOCK, (*_coordinates(row), row.value_uuid))
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

    def move_body(self, row: BodyRow) -> bool:
        """**只改坐标**：按 `row` 的位置段挪这一行；身份与摘要都不动。"""
        cursor = self._connection.execute(_MOVE_BODY, (*_coordinates(row), row.value_uuid))
        self._commit()
        return cursor.rowcount > 0

    def drop_body(self, value_uuid: str) -> bool:
        """摘掉一条内容行；返回是否确实摘掉了一行。

        整理（`storage/compact.py`）用它：一份内容没有块再引用它时，回收记录与摘掉这一行
        是同一件事的两面——只回收记录会留下一条读不出来的行，巡检会照报。
        """
        cursor = self._connection.execute(_DELETE_BODY, (value_uuid,))
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

    def register_hub(self, name: str) -> bool:
        """登记一个 hub；**已经登记过就不改写它**，返回是否新登记。

        只写名字：这张表回答的是"存在过哪些 hub"，真源是那个目录。
        """
        cursor = self._connection.execute(_INSERT_HUB, (name,))
        self._commit()
        return cursor.rowcount > 0

    def hub(self, name: str) -> HubRow | None:
        """按名取一条 hub 登记；没有即 ``None``。"""
        row = self._connection.execute(_SELECT_HUB, (name,)).fetchone()
        return None if row is None else _hub(row)

    def hubs(self) -> tuple[HubRow, ...]:
        """全部 hub 登记，按名排序。"""
        return tuple(_hub(row) for row in self._connection.execute(_SELECT_HUBS).fetchall())


def rebuild(rows: Rows, hubs: Iterable[Hub]) -> RebuildReport:
    """档一重建：以载体为真源，**只补缺行**。

    - hub 目录在、登记缺 → 补登记（登记是投影，真源是目录）；
    - 盘上有记录、库里没有行 → 按记录补行：**行上的每一列都从记录还原**
      （身份字段与类型标号在记录里，位置由扫到的位置给出）；
    - **已有行一律不动**：清空重扫要走显式授权。

    进哪张表**由载荷判断**（§3.2.1）：带指针的是块记录，进 `block`；其余是内容记录，进
    `body`。判据落在载荷上，故类型为空也认得出。坏点即停：遇到读不出底来的载体即抛，
    已补的行照旧留在库里（整批提交一次），重跑幂等。

    两类开销在这一层各自消掉：**已有身份集合进循环前一次预载**——逐条 `SELECT` 在大库里是
    N+1 查询；**整轮补行包在一层 :meth:`Rows.batch` 里**——逐行提交就是逐行 fsync。
    """
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
                rows.register_hub(hub.name)
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
                                name=record.id.name,
                                value_uuid=value_uuid,
                                value_hash=record.id.value_hash,
                                birth_time=record.id.birth_time,
                                in_hub=hub.name,
                                in_hub_pack=pack,
                                in_pack_slot=(span.first, span.last),
                            )
                        )
                        known_bodies.add(value_uuid)
                        bodies.append(value_uuid)
                    continue
                if value_uuid not in known_blocks:
                    rows.put_block(
                        BlockRow(
                            name=record.id.name,
                            value_uuid=value_uuid,
                            value_hash=record.id.value_hash,
                            birth_time=record.id.birth_time,
                            in_hub=hub.name,
                            in_hub_pack=pack,
                            in_pack_slot=(span.first, span.last),
                            body_value_uuid=pointer.value_uuid,
                            body_value_hash=pointer.value_hash,
                            kind=record.kind,
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


def _coordinates(row: BlockRow | BodyRow) -> tuple[object, ...]:
    """挪行要写的那三个坐标值（两张表共用同一套 = ID 的位置段）。"""
    return (row.in_hub, row.in_hub_pack, _slot_text(row.in_pack_slot))


def _count(connection: sqlite3.Connection, statement: str) -> int:
    """跑一条计数语句。"""
    row = connection.execute(statement).fetchone()
    return 0 if row is None else int(row["n"])


def _slot_text(slot: tuple[int, int]) -> str:
    """格区间落库的写法：`头格:末格`（两数即精确位置，见 `carrier.SlotRange`）。

    库里存文本而不是两列，是因为"一对格号"在 `ID` 里本来就是一个字段；
    要还原成两列，等于把一个字段拆成两个列名。范围查询本来也不落在格号上
    （位置只用于按主键定位），故这一层的取舍没有代价。
    """
    return f"{slot[0]}:{slot[1]}"


def _slot_pair(text: object) -> tuple[int, int]:
    """把库里的 `头格:末格` 还原成一对格号；写坏了即抛，不猜。"""
    first, _, last = str(text).partition(":")
    return (int(first), int(last))


def _block_values(row: BlockRow) -> tuple[object, ...]:
    """块行写库时的参数顺序，与 `_BLOCK_COLUMNS` 逐一对应。"""
    return (
        row.name,
        row.value_uuid,
        row.value_hash,
        row.birth_time,
        row.in_hub,
        row.in_hub_pack,
        _slot_text(row.in_pack_slot),
        row.body_value_uuid,
        row.body_value_hash,
        row.kind,
    )


def _body_values(row: BodyRow) -> tuple[object, ...]:
    """内容行写库时的参数顺序，与 `_BODY_COLUMNS` 逐一对应。"""
    return (
        row.name,
        row.value_uuid,
        row.value_hash,
        row.birth_time,
        row.in_hub,
        row.in_hub_pack,
        _slot_text(row.in_pack_slot),
    )


def _block(row: sqlite3.Row) -> BlockRow:
    """把一行读成块行。"""
    return BlockRow(
        name=str(row["name"] or ""),
        value_uuid=str(row["value_uuid"]),
        value_hash=str(row["value_hash"]),
        birth_time=int(row["birth_time"] or 0),
        in_hub=str(row["in_hub"]),
        in_hub_pack=str(row["in_hub_pack"]),
        in_pack_slot=_slot_pair(row["in_pack_slot"]),
        body_value_uuid=str(row["body_value_uuid"] or ""),
        body_value_hash=str(row["body_value_hash"] or ""),
        kind=str(row["kind"] or ""),
    )


def _body(row: sqlite3.Row) -> BodyRow:
    """把一行读成内容行。"""
    return BodyRow(
        name=str(row["name"] or ""),
        value_uuid=str(row["value_uuid"]),
        value_hash=str(row["value_hash"]),
        birth_time=int(row["birth_time"] or 0),
        in_hub=str(row["in_hub"]),
        in_hub_pack=str(row["in_hub_pack"]),
        in_pack_slot=_slot_pair(row["in_pack_slot"]),
    )


def _hub(row: sqlite3.Row) -> HubRow:
    """把一行读成 hub 登记。"""
    return HubRow(name=str(row["name"]))


__all__ = [
    "BLOCK_TABLE",
    "BODY_TABLE",
    "HUB_TABLE",
    "BlockRow",
    "BodyRow",
    "HubRow",
    "RebuildReport",
    "Rows",
    "rebuild",
]

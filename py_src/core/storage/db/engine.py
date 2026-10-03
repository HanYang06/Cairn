# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""数据库引擎:管索引库,把身份译成一行定位.

**与存储引擎的区别**(两者同名"引擎",但面向的东西不同):

- `core.storage.engine` 面向载体:管 hub,写字节,读字节,**不认识数据库**;
- 本引擎面向索引库:管行,建表,按身份查位置,**不认识 pack / hub**.

它的复杂度来自一个明确的关系:**它与 ID 有直接关系**.库里的表不是"描述数据结构的表",
而是**身份表**——一个类型用了 ID,库里就为它产生一张真正意义上的索引表;不用 ID,
那张表自然不产生.故库的结构只有一条来路:**ID**.

库的形状定死了,就三样:

| 库里的东西 | 来路 |
|---|---|
| 每个用 ID 的类型一张**身份表** | 表名 = 类型名;列见 `columns_of()` |
| `hub` 登记 | 目录是事实,登记是库的一列 |
| `meta` | 库自用(记录本库属于本设计) |

**锚定是"用没用 ID",不是"是不是 Block"**:`Block` 只是契约,故 `NoteData` 继承了它,
又用了 ID,库里就有一张 `notedata` 表;`attrindex` 与它完全同路,没有第二套机制.

**列不再等于 `ID` 的字段**:身份的字段有几个就有几列,**另加正文历史那一列**——
布点(hub,载体,段列表)与正文历史都是库里的事实,载体上没有一个字节承载它们.
**故一张身份表恰好七列**:`name` / `value_uuid` / `birth_time` / `in_hub` / `in_hub_pack` /
`in_pack_slot` / `body_history`.列清单由 :func:`columns_of` 现算,没有第二份列清单.

**"哪几格是属性槽"不进库**:属性槽与正文槽靠槽头种类分辨,载体上每一格本来就写着
(2026-10-02 修正裁定).

**载荷不进库**:属性值与正文分片都在载体的槽里.库只回答三件事——
"这个身份在哪儿","它的正文有哪几代",以及由索引块提供的"按这个值能查到谁".

**库是权威视角**:它装身份,位置与正文历史,是这三样的唯一来源.故**没有从载体重算
这条路径**:库丢失即数据缺失,报"对象不在",不回退顺扫,也不静默补一行.

**不再有表结构声明文件**:表由"类型用了 ID"这件事诞生,不由文件声明.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from core.exc import IndexNotFoundError, IndexSchemaError

from .id import BODY_HISTORY_FIELD, ID_FIELDS

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping
    from pathlib import Path

HUB_TABLE = "hub"
"""登记表：回答"存在过哪些 hub"。真源是那些目录，登记是库的一列。"""

META_TABLE = "meta"
"""库自用表：记录本库属于本设计，不是别人的 sqlite 文件。"""

META_MARK = "cairn.catalog"
"""`meta` 里那一行的名字：它存在即"这是本设计的库"。"""

#: 列类型:**库里的列一律按文本落**.
#:
#: 凭证,名字,hub 名,载体名本来就是字符串;`birth_time`,段列表与正文历史是整数或映射,
#: 但落成文本不影响"按值相等"的查询,而段列表与正文历史**共用同一种文本编码**,
#: 读侧因此只有一个解析函数.这个取舍是刻意的:**列以身份为事实结构**,
#: 不另立一套类型体系.
_COLUMN = "TEXT"


def columns_of() -> tuple[str, ...]:
    """一张身份表的列:**`ID_FIELDS` 加正文历史一列**,恰好七列,一个不多.

    清单从 `ID` 的字段上现算,故"某个字段进不去库"在代码上不成立;正文历史是库的事实,
    而 `ID` 的字段里没有它——位置之外,库里还装着"这个块的正文是哪一份,经过哪几代".

    **"哪几格是属性槽"不在这里**:属性槽与正文槽靠**槽头种类**分辨(`pack.ATTR_SLOT` /
    `pack.BODY_SLOT`),载体上每一格本来就写着;再落一列就是用 pack 内的坐标去表达
    跨 pack 才能表达的事(2026-10-02 修正裁定).
    """
    return (*ID_FIELDS, BODY_HISTORY_FIELD)


class Index:
    """索引库:一张 `catalog.db`,装身份表,`hub` 登记与 `meta`.

    Args:
        path: 库文件路径.
        connection: 已打开的 sqlite 连接(由 :meth:`open` 或 :meth:`create` 给).
    """

    def __init__(self, path: Path, connection: sqlite3.Connection) -> None:
        """接上一个已打开的连接.**不负责开关库**:那是两个类方法的活."""
        self._path = path
        self._db = connection

    # ---- 开关 ---- #

    @classmethod
    def create(cls, path: Path, tables: Iterable[str] = ()) -> Index:
        """**显式建立**:库文件不存在就建,并保证 `hub` / `meta` 与给定的身份表在."""
        path.parent.mkdir(parents=True, exist_ok=True)
        index = cls(path, sqlite3.connect(path))
        index._ensure_base()
        for table in tables:
            index.ensure_table(table)
        index._db.commit()
        return index

    @classmethod
    def open(cls, path: Path) -> Index:
        """打开一个既有的库.**读路径不建库**:不在即报错.

        Raises:
            IndexNotFoundError: 库文件不在.
            IndexSchemaError: 这不是本设计的库(缺 `meta`)——不把它人的 sqlite 当本库用.
        """
        if not path.is_file():
            raise IndexNotFoundError(f"索引库不在: {path}")
        index = cls(path, sqlite3.connect(path))
        if not index._has_table(META_TABLE):
            raise IndexSchemaError(f"这不是本程序的索引库（缺 {META_TABLE} 表）: {path}")
        index._ensure_base()
        return index

    def close(self) -> None:
        """关掉连接."""
        self._db.close()

    @property
    def path(self) -> Path:
        """库文件路径."""
        return self._path

    @property
    def connection(self) -> sqlite3.Connection:
        """底层的 sqlite 连接(诊断与测试用)."""
        return self._db

    # ---- 身份表 ---- #

    def ensure_table(self, name: str) -> None:
        """保证一个身份表在:**列全部由 :func:`columns_of` 现算**.

        表名就是类型的名字(下方写法).列一个不多,一个不少——`ID` 加一个字段,
        下一趟开库就多一列.

        Args:
            name: 表名(=类型名).
        """
        columns = ", ".join(f"{_quote(field)} {_COLUMN}" for field in columns_of())
        self._db.execute(
            f"CREATE TABLE IF NOT EXISTS {_quote(name)} ({columns}, PRIMARY KEY (value_uuid))"
        )
        self._db.commit()

    def tables(self) -> tuple[str, ...]:
        """库里现有全部表名,按名字排序."""
        rows = self._db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return tuple(sorted(str(row[0]) for row in rows))

    # ---- 行 ---- #

    def put(self, table: str, row: Mapping[str, object]) -> None:
        """把一份身份写成一行(**整行照 :func:`columns_of` 搬**).

        同一身份写两次即覆盖:库里那一行是身份,位置与正文历史的真源,谁最后写谁说了算.

        Args:
            table: 身份表名.
            row: `ID.to_row()` 的产物.
        """
        names = columns_of()
        values = [row.get(field) for field in names]
        placeholders = ", ".join("?" for _ in names)
        columns = ", ".join(_quote(field) for field in names)
        self._db.execute(
            f"INSERT OR REPLACE INTO {_quote(table)} ({columns}) VALUES ({placeholders})",
            [_plain(value) for value in values],
        )
        self._db.commit()

    def get(self, table: str, value_uuid: str) -> dict[str, object] | None:
        """按分配形态凭证取一行;没有即 ``None``."""
        names = columns_of()
        cursor = self._db.execute(
            f"SELECT {', '.join(_quote(field) for field in names)}"
            f" FROM {_quote(table)} WHERE value_uuid = ?",
            (value_uuid,),
        )
        row = cursor.fetchone()
        return None if row is None else dict(zip(names, row, strict=True))

    def rows(self, table: str) -> Iterator[dict[str, object]]:
        """逐行取出——**身份表的取数口**."""
        names = columns_of()
        cursor = self._db.execute(
            f"SELECT {', '.join(_quote(field) for field in names)} FROM {_quote(table)}"
        )
        for row in cursor:
            yield dict(zip(names, row, strict=True))

    def drop_row(self, table: str, value_uuid: str) -> bool:
        """摘掉一行:返回是否确实摘掉了一个."""
        cursor = self._db.execute(
            f"DELETE FROM {_quote(table)} WHERE value_uuid = ?",
            (value_uuid,),
        )
        self._db.commit()
        return cursor.rowcount > 0

    def register_hub(self, name: str) -> None:
        """登记一个 hub:**只认第一次**,重复登记不覆盖."""
        self._db.execute(
            f"INSERT OR IGNORE INTO {_quote(HUB_TABLE)} (name) VALUES (?)",
            (name,),
        )
        self._db.commit()

    def hubs(self) -> tuple[str, ...]:
        """已登记的全部 hub 名,按名字排序."""
        cursor = self._db.execute(f"SELECT name FROM {_quote(HUB_TABLE)} ORDER BY name")
        return tuple(str(row[0]) for row in cursor)

    # ---- 内部 ---- #

    def _ensure_base(self) -> None:
        """保证 `hub` 与 `meta` 在——它们是库自己的骨头,任何库都必须有."""
        self._db.execute(f"CREATE TABLE IF NOT EXISTS {_quote(HUB_TABLE)} (name TEXT PRIMARY KEY)")
        self._db.execute(
            f"CREATE TABLE IF NOT EXISTS {_quote(META_TABLE)} (name TEXT PRIMARY KEY, value TEXT)"
        )
        self._db.execute(
            f"INSERT OR IGNORE INTO {_quote(META_TABLE)} (name, value) VALUES (?, ?)",
            (META_MARK, "1"),
        )
        self._db.commit()

    def _has_table(self, name: str) -> bool:
        """库里有没有这张表."""
        cursor = self._db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        )
        return cursor.fetchone() is not None


def _quote(name: str) -> str:
    """把表名或列名包成标识符:名字来自类名与 `ID_FIELDS`,故只做最基本的转义."""
    return '"' + name.replace('"', '""') + '"'


def _plain(value: object) -> object:
    """把值收进 sqlite 认的那几种:一段列表与一条摘要链一律按文本落.

    `ID` 上需要文本化的字段是位置段(`in_pack_slot`)与正文摘要链(`body_history`);
    两者都由 `db/id.py` 的编码函数交出字符串,故这里只兜住 `None`.
    """
    if value is None:
        return ""
    if isinstance(value, bool | int | float | str | bytes):
        return value
    return str(value)


__all__ = ["HUB_TABLE", "META_MARK", "META_TABLE", "Index", "columns_of"]

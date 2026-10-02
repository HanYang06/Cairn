# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""数据库引擎：管索引库，把身份译成一行定位。

**与存储引擎的区别**（两者同名"引擎"，但面向的东西不同）：

- `core.storage.engine` 面向载体：管 hub、写字节、读字节，**不认识数据库**；
- 本引擎面向索引库：管行、建表、按身份查位置，**不认识 slot / pack / hub**。

它的复杂度来自一个明确的关系：**它与 ID 有直接关系**。库里的表不是"描述数据结构的表"，
而是**身份表**——一个类型用了 ID，库里就为它产生一张真正意义上的索引表；不用 ID，
那张表自然不产生。故库的结构只有一条来路：**ID**。

库的形状定死了，就三样：

| 库里的东西 | 来路 |
|---|---|
| 每个用 ID 的类型一张**身份表**（`notedata` / `attrindex` / …） | 表名 = 类型名；列 = `ID_FIELDS` |
| `hub` 登记 | 目录是事实，登记是投影 |
| `meta` | 库自用（记录本库属于本设计） |

**锚定是"用没用 ID"，不是"是不是 Block"**：`Block` 只是契约，故 `NoteData` 继承了它、
又用了 ID，库里就有一张 `notedata` 表；`attrindex` 与它完全同路，没有第二套机制。

**列全部以 ID 为事实结构**——`ID` 有几个字段就有几列，一个不多、一个不少。
这在列数上是奢侈的，但它换来一条：**库里的行是 ID 的镜像**，"某个字段进不去库"
这个问题在代码上不成立（`ID_FIELDS` 是从 `ID` 上数出来的）。

**载荷不进库**：正文、属性值都在块记录的载荷里（在载体上）。库只回答两件事——
"这个身份在哪儿"，以及由索引块提供的"按这个值能查到谁"。

**库里的一切都能从载体算回来**：库是纯投影——每一行都要能从载体顺扫回来（缺表即建、
缺行即补），故库丢了不是数据丢失，只是"查得慢"。判据：库里出现一个推不回来的值，
它就不再是索引。

**不再有表结构声明文件**：表由"类型用了 ID"这件事诞生，不由文件声明。声明文件
（`type.yml` 一类）即便写出，也只是给人看的参照——**系统不读它**。
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from core.exc import IndexNotFoundError, IndexSchemaError

from .id import ID_FIELDS

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping
    from pathlib import Path

HUB_TABLE = "hub"
"""登记表：回答"存在过哪些 hub"。真源是那些目录，故它是投影。"""

META_TABLE = "meta"
"""库自用表：记录本库属于本设计，不是别人的 sqlite 文件。"""

META_MARK = "cairn.catalog"
"""`meta` 里那一行的名字：它存在即"这是本设计的库"。"""

#: 列类型：**ID 的字段一律按文本落**。
#:
#: 两套凭证、名字、hub 名、载体名本来就是字符串；`birth_time` 与格区间是整数，
#: 但落成文本不影响"按值相等"的查询，而换取的是"加一个 ID 字段不必再想它该是什么类型"。
#: 这个取舍是刻意的：**库里的行是 ID 的镜像**，镜像不该有自己的类型体系。
_COLUMN = "TEXT"


class Index:
    """索引库：一张 `catalog.db`，装身份表、`hub` 登记与 `meta`。

    Args:
        path: 库文件路径。
        connection: 已打开的 sqlite 连接（由 :meth:`open` 或 :meth:`create` 给）。
    """

    def __init__(self, path: Path, connection: sqlite3.Connection) -> None:
        """接上一个已打开的连接。**不负责开关库**：那是两个类方法的活。"""
        self._path = path
        self._db = connection

    # ---- 开关 ---- #

    @classmethod
    def create(cls, path: Path, tables: Iterable[str] = ()) -> Index:
        """**显式建立**：库文件不存在就建，并保证 `hub` / `meta` 与给定的身份表在。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        index = cls(path, sqlite3.connect(path))
        index._ensure_base()
        for table in tables:
            index.ensure_table(table)
        index._db.commit()
        return index

    @classmethod
    def open(cls, path: Path) -> Index:
        """打开一个既有的库。**读路径不建库**：不在即报错。

        Raises:
            IndexNotFoundError: 库文件不在。
            IndexSchemaError: 这不是本设计的库（缺 `meta`）——不把它人的 sqlite 当本库用。
        """
        if not path.is_file():
            raise IndexNotFoundError(f"索引库不在: {path}")
        index = cls(path, sqlite3.connect(path))
        if not index._has_table(META_TABLE):
            raise IndexSchemaError(f"这不是本程序的索引库（缺 {META_TABLE} 表）: {path}")
        index._ensure_base()
        return index

    def close(self) -> None:
        """关掉连接。"""
        self._db.close()

    @property
    def path(self) -> Path:
        """库文件路径。"""
        return self._path

    @property
    def connection(self) -> sqlite3.Connection:
        """底层的 sqlite 连接（诊断与测试用）。"""
        return self._db

    # ---- 身份表 ---- #

    def ensure_table(self, name: str) -> None:
        """保证一个身份表在：**列全部由 `ID_FIELDS` 现算**。

        表名就是类型的名字（下方写法）。列一个不多、一个不少——`ID` 加一个字段，
        下一趟开库就多一列。

        Args:
            name: 表名（＝类型名）。
        """
        columns = ", ".join(f"{field} {_COLUMN}" for field in ID_FIELDS)
        self._db.execute(
            f"CREATE TABLE IF NOT EXISTS {_quote(name)} ({columns}, PRIMARY KEY (value_uuid))"
        )
        self._db.commit()

    def tables(self) -> tuple[str, ...]:
        """库里现有全部表名，按名字排序。"""
        rows = self._db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return tuple(sorted(str(row[0]) for row in rows))

    # ---- 行 ---- #

    def put(self, table: str, identity: Mapping[str, object]) -> None:
        """把一份身份写成一行（**整行照 `ID_FIELDS` 搬**）。

        同一身份写两次即覆盖：库里的行是投影，谁最后写谁说了算。

        Args:
            table: 身份表名。
            identity: `ID.to_record()` 的产物，外加位置段（它由引擎补）。
        """
        values = [identity.get(field) for field in ID_FIELDS]
        placeholders = ", ".join("?" for _ in ID_FIELDS)
        columns = ", ".join(ID_FIELDS)
        self._db.execute(
            f"INSERT OR REPLACE INTO {_quote(table)} ({columns}) VALUES ({placeholders})",
            [_plain(value) for value in values],
        )
        self._db.commit()

    def get(self, table: str, value_uuid: str) -> dict[str, object] | None:
        """按分配形态凭证取一行；没有即 ``None``。"""
        cursor = self._db.execute(
            f"SELECT {', '.join(ID_FIELDS)} FROM {_quote(table)} WHERE value_uuid = ?",
            (value_uuid,),
        )
        row = cursor.fetchone()
        return None if row is None else dict(zip(ID_FIELDS, row, strict=True))

    def rows(self, table: str) -> Iterator[dict[str, object]]:
        """逐行取出——**顺扫的入口**。"""
        cursor = self._db.execute(f"SELECT {', '.join(ID_FIELDS)} FROM {_quote(table)}")
        for row in cursor:
            yield dict(zip(ID_FIELDS, row, strict=True))

    def drop_row(self, table: str, value_uuid: str) -> bool:
        """摘掉一行：返回是否确实摘掉了一个。"""
        cursor = self._db.execute(
            f"DELETE FROM {_quote(table)} WHERE value_uuid = ?",
            (value_uuid,),
        )
        self._db.commit()
        return cursor.rowcount > 0

    def register_hub(self, name: str) -> None:
        """登记一个 hub：**只认第一次**，重复登记不覆盖。"""
        self._db.execute(
            f"INSERT OR IGNORE INTO {_quote(HUB_TABLE)} (name) VALUES (?)",
            (name,),
        )
        self._db.commit()

    def hubs(self) -> tuple[str, ...]:
        """已登记的全部 hub 名，按名字排序。"""
        cursor = self._db.execute(f"SELECT name FROM {_quote(HUB_TABLE)} ORDER BY name")
        return tuple(str(row[0]) for row in cursor)

    # ---- 内部 ---- #

    def _ensure_base(self) -> None:
        """保证 `hub` 与 `meta` 在——它们是库自己的骨头，任何库都必须有。"""
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
        """库里有没有这张表。"""
        cursor = self._db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        )
        return cursor.fetchone() is not None


def _quote(name: str) -> str:
    """把表名包成标识符：表名来自类名，故只做最基本的转义。"""
    return '"' + name.replace('"', '""') + '"'


def _plain(value: object) -> object:
    """把值收进 sqlite 认的那几种：格区间那一对落成 ``头:末``，其余文本化。

    `in_pack_slot` 是 ID 上唯一对不上 sqlite 标量的字段（一对整数），
    它落成 ``"头:末"``；读回来时由需要的调用方切回两个数。
    """
    if isinstance(value, tuple):
        return ":".join(str(item) for item in value)
    if value is None:
        return ""
    if isinstance(value, int | float | str | bytes):
        return value
    return str(value)


__all__ = ["HUB_TABLE", "META_MARK", "META_TABLE", "Index"]

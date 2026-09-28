# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""表：**领域自描述的业务表**的读写封装（受索引库管的普通表）。

上层不需要 import sqlite，也不必手写连接与事务：拿到 ``Table`` 句柄后按方法操作即可。
表结构由调用方（领域）给出：``create_table(conn, name, columns)`` 建，校验在**这一处**——
表名 / 列名 / 列定义都会进 SQL，故用白名单正则卡死，拼错与注入都在解析口被拒。

与索引库声明的关系：内核自己的表由 `config/settings/core/storage/tables.yaml` 声明
（见 `core/storage/tables.py`）；这里管的是**领域表**——落同一个索引库、同一个连接，
但不在内核声明里。所以它们开库时会被如实报成"多出的表"（告警，不删）。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from core.types import CairnError

from .tables import check_ident

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping

_SPEC_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9_]*"
    r"(?:\s*\([0-9,\s]+\))?"
    r"(?:\s+(?:PRIMARY\s+KEY|NOT\s+NULL|UNIQUE))?"
    r"(?:\s+DEFAULT\s+('[^']*'|[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)))?$",
    re.IGNORECASE,
)
"""列定义白名单：``类型[(长度)] [PRIMARY KEY|NOT NULL|UNIQUE] [DEFAULT 值]``，其余一律拒绝。

DEFAULT 收字符串字面量与**真正的数值形态**：``[0-9.+-]+`` 那种松口径会放行
``DEFAULT +`` / ``DEFAULT .`` 这类非法 SQL，把错误推到 ``CREATE TABLE`` 才炸。
"""


def create_table(conn: sqlite3.Connection, name: str, columns: Mapping[str, str]) -> None:
    """建一张领域表（已存在即不动）；表名 / 列名 / 列定义不合法即抛 ``CairnError``。

    **标识符校验与内核声明表共用一处**（`tables.check_ident`）：同一个索引库里的表名，
    规则分家就会漂移成"创建得出、声明校验不过"。列定义的白名单只在这里——领域表
    直接给方言片段，声明表给的是中立类型，两者本就不是一套写法。
    """
    check_ident(name, what="表名")
    for column in columns:
        check_ident(column, what="列名")
    bad_spec = next((spec for spec in columns.values() if not _SPEC_RE.match(spec.strip())), None)
    if bad_spec is not None:
        raise CairnError(f"非法列定义: {bad_spec!r}")
    parts = [f'"{column}" {spec}'.strip() for column, spec in columns.items()]
    conn.execute(f'CREATE TABLE IF NOT EXISTS "{name}" ({", ".join(parts)})')


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _predicates(where: Mapping[str, Any]) -> tuple[str, list[Any]]:
    """把等值过滤编成子句与参数；``None`` 用 ``IS NULL``（``= NULL`` 永不命中）。"""
    clauses: list[str] = []
    values: list[Any] = []
    for key, value in where.items():
        if value is None:
            clauses.append(f"{_quote(key)} IS NULL")
        else:
            clauses.append(f"{_quote(key)} = ?")
            values.append(value)
    return " AND ".join(clauses), values


class Table:
    """一张业务表的读写封装。"""

    def __init__(self, conn: sqlite3.Connection, name: str) -> None:
        self.conn = conn
        self.name = name

    def insert(self, row: Mapping[str, Any]) -> None:
        columns = list(row)
        if not columns:
            raise ValueError("insert 需要至少一列")
        placeholders = ", ".join("?" for _ in columns)
        names = ", ".join(_quote(column) for column in columns)
        self.conn.execute(
            f"INSERT INTO {_quote(self.name)} ({names}) VALUES({placeholders})",
            [row[column] for column in columns],
        )

    def upsert(self, row: Mapping[str, Any], *, conflict: str = "id") -> None:
        """按 ``conflict`` 列做真 upsert（``ON CONFLICT DO UPDATE``），保留未列出的列。

        ``conflict`` 不在行内时退回 ``INSERT OR REPLACE``（兼容按表自身主键去重的旧调用）。
        """
        columns = list(row)
        if not columns:
            raise ValueError("upsert 需要至少一列")
        placeholders = ", ".join("?" for _ in columns)
        names = ", ".join(_quote(column) for column in columns)
        values = [row[column] for column in columns]
        if conflict in columns:
            updates = ", ".join(
                f"{_quote(column)} = excluded.{_quote(column)}"
                for column in columns
                if column != conflict
            )
            action = f"DO UPDATE SET {updates}" if updates else "DO NOTHING"
            sql = (
                f"INSERT INTO {_quote(self.name)} ({names}) VALUES({placeholders}) "
                f"ON CONFLICT({_quote(conflict)}) {action}"
            )
        else:
            sql = f"INSERT OR REPLACE INTO {_quote(self.name)} ({names}) VALUES({placeholders})"
        self.conn.execute(sql, values)

    def select(self, **where: Any) -> list[sqlite3.Row]:
        if where:
            clause, values = _predicates(where)
            sql = f"SELECT * FROM {_quote(self.name)} WHERE {clause}"
        else:
            sql, values = f"SELECT * FROM {_quote(self.name)}", []
        return list(self.conn.execute(sql, values).fetchall())

    def all(self) -> list[sqlite3.Row]:
        return self.select()

    def update(self, values: Mapping[str, Any], **where: Any) -> int:
        if not values:
            raise ValueError("update 需要至少一列")
        if not where:
            raise ValueError("update 需要至少一个过滤条件")
        assignments = ", ".join(f"{_quote(key)} = ?" for key in values)
        clause, filter_values = _predicates(where)
        cursor = self.conn.execute(
            f"UPDATE {_quote(self.name)} SET {assignments} WHERE {clause}",
            [*values.values(), *filter_values],
        )
        return cursor.rowcount

    def delete(self, **where: Any) -> int:
        if not where:
            raise ValueError("delete 需要至少一个过滤条件")
        clause, values = _predicates(where)
        cursor = self.conn.execute(
            f"DELETE FROM {_quote(self.name)} WHERE {clause}",
            values,
        )
        return cursor.rowcount

    def count(self) -> int:
        row = self.conn.execute(f"SELECT COUNT(*) AS n FROM {_quote(self.name)}").fetchone()
        return int(row["n"])


__all__ = ["Table", "create_table"]

# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""索引库：**对比 → 分类 → 处置**，建表语句由表声明编译（源码内无建表 SQL）。

设计见 `docs/architecture/storage-design.md` §8.4。四步：

1. **对比**：把实际结构读回来（`sqlite_master` / `PRAGMA table_info`），与声明逐项比；
2. **分类**：差异分三种——**可原位补齐**（缺表 / 缺列 / 缺索引 / 多出未声明列，只告警）、
   **须重建搬运**（列的型或约束变了：SQLite 改不了）、**拒绝启动**（库比声明新）；
3. **处置**：原位补齐由 :meth:`Index.align` 直接执行；重建搬运是**破坏性**动作，
   必须显式传入 :class:`RebuildPlan` 才执行——默认拒绝，不静默重建；
4. **一致**：处置完成后再比一次，不一致即报错（不假装成功）。

**建表只在开库 / 挂载时发生**，不在读写路径上：热路径反复执行 DDL 与提交是设计事故（§8.4）。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from core.types import RecordFormatError, ValueHash, now_ms
from core.types.errors import IndexSchemaError

from .tables import Column, TableSpec, declared_tables, sql_type_name

if TYPE_CHECKING:
    from collections.abc import Mapping

_logger = logging.getLogger(__name__)

INDEX_NAME = "catalog.db"
"""索引库文件名（**一个 vault 一个库**，桶名是库里的一列）。"""

_META_KEY = "schema.declared"
"""`meta` 里存的那份声明投影（用来发现"库里记的"与"程序认的"不一致）。"""


@dataclass(frozen=True, slots=True)
class Difference:
    """一处差异：分类 + 处置所需的最小信息。"""

    table: str
    kind: str
    """差异种类：``missing_table`` / ``missing_column`` / ``extra_column`` /
    ``missing_index`` / ``column_mismatch`` / ``extra_table``。"""

    detail: str = ""

    @property
    def fixable(self) -> bool:
        """可否原位补齐（**不必重建**）。"""
        return self.kind in {
            "missing_table",
            "missing_column",
            "missing_index",
            "index_mismatch",
            "extra_column",
            "extra_table",
        }

    @property
    def destructive(self) -> bool:
        """是否必须重建表并搬运数据（SQLite 改不了列型 / 约束）。"""
        return self.kind == "column_mismatch"

    @property
    def warning(self) -> bool:
        """是否只是**告警**（多出的列 / 多出的表）。

        这两类**不删不拦**：库里的东西不是我们建的，就不动它（§8.4）。
        它们与"缺表 / 缺列 / 列型不符"性质不同——后者开库必须处置或拒绝，
        故开库时只对非告警的剩余差异报错。
        """
        return self.kind in {"extra_column", "extra_table"}


@dataclass(frozen=True, slots=True)
class RebuildPlan:
    """重建授权：**破坏性动作必须显式给**（不给则拒绝执行）。"""

    tables: tuple[str, ...]
    """要重建的表名；这些表的数据由调用方负责搬运。"""

    reason: str = ""
    """为什么重建（进日志，便于回溯）。"""


@dataclass
class Index:
    """索引库：一个 sqlite 连接 + 一组表声明。"""

    path: Path
    conn: sqlite3.Connection
    declarations: tuple[TableSpec, ...] = field(default_factory=declared_tables)

    # ---- 生命周期 ----
    @classmethod
    def open(cls, path: Path | str) -> Index:
        """打开（不存在即建）索引库；只建 ``meta``，其余表由 :meth:`align` 按声明处置。

        **不接管别人的 SQLite 文件**：库里已有表，却**一张都不是本程序声明的**，
        就说明它不是本程序建的——旧格式的目录也落在这一条上。此时拒开，而不是往里建表：
        与配置端的口径一致，绝不覆盖别人的文件；也免得老库被当成"空库"静默读过去。
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(target))
        conn.row_factory = sqlite3.Row
        try:
            strangers = _stranger_tables(conn)
        except Exception:
            conn.close()  # 库坏掉时认表这一步就会抛：抛之前先关，不得漏连接
            raise
        if strangers:
            conn.close()
            raise IndexSchemaError(
                f"库里已有的表 {strangers} 一张都不是本程序声明的，不接管：{target}"
                "（旧格式的库不予读取；换目录或人工处置）"
            )
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
        except Exception:
            conn.close()
            raise
        return cls(path=target, conn=conn)

    def close(self) -> None:
        """关闭连接。"""
        self.conn.close()

    def commit(self) -> None:
        """提交当前事务。"""
        self.conn.commit()

    # ---- 对比 ----
    def actual_tables(self) -> dict[str, dict[str, str]]:
        """实际表结构：``{表名: {列名: 类型}}``（不含 ``meta`` 与 sqlite 内部表）。"""
        found: dict[str, dict[str, str]] = {}
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for row in rows:
            name = str(row["name"])
            if name == "meta":
                continue
            found[name] = self._columns_of(name)
        return found

    def _columns_of(self, name: str) -> dict[str, str]:
        """按 ``PRAGMA table_info`` 取列与类型（**引号内是表名，来自声明，已校验标识符**）。"""
        quoted = '"' + name.replace('"', '""') + '"'
        return {
            str(row["name"]): str(row["type"]).upper()
            for row in self.conn.execute(f"PRAGMA table_info({quoted})")
        }

    def actual_indexes(self, table: str) -> set[tuple[tuple[str, ...], bool]]:
        """实际索引：``{(列组合, 是否唯一)}``。"""
        return set(self.actual_index_defs(table).values())

    def actual_index_defs(self, table: str) -> dict[str, tuple[tuple[str, ...], bool]]:
        """实际索引：``{索引名: (列组合, 是否唯一)}``（按**名字**索引，比对同名不同定义用）。"""
        quoted = '"' + table.replace('"', '""') + '"'
        found: dict[str, tuple[tuple[str, ...], bool]] = {}
        for row in self.conn.execute(f"PRAGMA index_list({quoted})"):
            index_name = str(row["name"])
            if index_name.startswith("sqlite_autoindex"):
                continue
            columns = tuple(
                str(item["name"])
                for item in self.conn.execute(f'PRAGMA index_info("{index_name}")')
            )
            found[index_name] = (columns, bool(row["unique"]))
        return found

    def differences(self) -> list[Difference]:
        """把实际结构与声明逐项比，返回差异清单（空 = 一致）。"""
        found: list[Difference] = []
        declared = {table.name: table for table in self.declarations}
        actual = self.actual_tables()
        for name, table in declared.items():
            if name not in actual:
                found.append(Difference(name, "missing_table", "声明有、库里没有"))
                continue
            columns = actual[name]
            wanted = {column.name: column for column in table.columns}
            for column in table.columns:
                if column.name not in columns:
                    # 缺列分两种：**能原地补**的（ALTER TABLE ADD COLUMN）与**补不上**的
                    # （主键 / UNIQUE / NOT NULL 无默认值）。后者只能重建，故按破坏性差异报，
                    # 免得落在"可原位补齐"里、对齐时却补不上而卡在"仍有差异"。
                    statement = table.add_column_ddl(column)
                    if statement is None:
                        found.append(
                            Difference(
                                name,
                                "column_mismatch",
                                f"{column.name}: 缺列且无法原地补"
                                "（主键 / UNIQUE / NOT NULL 无默认值），须重建",
                            )
                        )
                    else:
                        found.append(Difference(name, "missing_column", column.name))
                elif columns[column.name] != sql_type_name(column.type):
                    found.append(
                        Difference(
                            name,
                            "column_mismatch",
                            f"{column.name}: 实际 {columns[column.name]}"
                            f" ≠ 声明 {sql_type_name(column.type)}",
                        )
                    )
            found.extend(
                Difference(name, "extra_column", extra)
                for extra in sorted(set(columns) - set(wanted))
            )
            defs = self.actual_index_defs(name)
            for index in table.indexes:
                defined = defs.get(index.name)
                if defined is None:
                    found.append(Difference(name, "missing_index", index.name))
                elif defined != (index.columns, index.unique):
                    # 同名、不同定义（索引名只由列推出，故**唯一性变化**正好落在这里）。
                    # 得先 DROP 再建：`CREATE INDEX IF NOT EXISTS` 见到同名会跳过，
                    # 光靠它永远改不过来，差异就卡在"对齐后仍有"。
                    found.append(
                        Difference(
                            name,
                            "index_mismatch",
                            f"{index.name}: 实际 {defined} ≠ 声明 {(index.columns, index.unique)}",
                        )
                    )
        found.extend(
            Difference(extra_table, "extra_table", "库里有、声明没有")
            for extra_table in sorted(set(actual) - set(declared))
        )
        return found

    def repair_plan(self) -> dict[str, object]:
        """按分类给出处置计划（**只出计划，不动库**）：补齐、重建、拒绝三类。"""
        differences = self.differences()
        fixable = [item for item in differences if item.fixable]
        destructive = [item for item in differences if item.destructive]
        return {
            "fixable": sorted({item.table for item in fixable}),
            "rebuild": sorted({item.table for item in destructive}),
            "details": [
                {"table": item.table, "kind": item.kind, "detail": item.detail}
                for item in differences
            ],
        }

    # ---- 处置 ----
    def align(self, *, rebuild: RebuildPlan | None = None) -> list[Difference]:
        """对齐声明：原位补齐照做（缺表建表、**缺列补列**、缺索引建索引）；破坏性差异无授权即拒绝。

        "缺列补列"由 :meth:`TableSpec.add_column_ddl` 生成 ``ALTER TABLE … ADD COLUMN``：
        ``ddl()`` 里那句 ``CREATE TABLE IF NOT EXISTS`` 对**已存在的表**是空操作，
        只靠它补不上列——那会让"声明加一列"变成"库打不开"。

        返回处置后仍存在的差异（应为空）；非空即抛错——不静默放过。
        """
        differences = self.differences()
        destructive = self._authorize(differences, rebuild)
        for table in self.declarations:
            self._align_table(table, differences, destructive)
        self.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
            (_META_KEY, json.dumps(_canonical_declarations(), ensure_ascii=False, sort_keys=True)),
        )
        self.conn.commit()
        return self.differences()

    def _authorize(self, differences: list[Difference], rebuild: RebuildPlan | None) -> set[str]:
        """破坏性差异的授权检查（**没授权就不动库**）；返回获准重建的表名集合。"""
        destructive = {item.table for item in differences if item.destructive}
        if destructive and rebuild is None:
            raise IndexSchemaError(
                f"以下表的列型或约束与声明不符（或缺列且补不上），SQLite 无法原地修改，"
                f"需重建并搬运：{sorted(destructive)}（调用方须显式给出 RebuildPlan）"
            )
        allowed = set(rebuild.tables) if rebuild is not None else set()
        unauthorized = destructive - allowed
        if unauthorized:
            raise IndexSchemaError(
                f"重建授权未覆盖：{sorted(unauthorized)}（授权 {sorted(allowed)}）"
            )
        if rebuild is not None and rebuild.tables:
            _logger.warning(
                "按授权重建表（数据由调用方搬运）：%s；原因：%s", rebuild.tables, rebuild.reason
            )
        return destructive

    def _align_table(
        self, table: TableSpec, differences: list[Difference], destructive: set[str]
    ) -> None:
        """处置一张表：按授权重建（整表按声明重来），否则**先建表、再补列、最后建索引**。

        三步的顺序不能反：``ddl()`` 把建表与建索引混在一起返回，若整段先跑，
        "这次新增一列、并且给它建了索引"就会先执行 ``CREATE INDEX … ("新列")``——
        那时列还没补上，SQLite 报 ``no such column``，库随即打不开。
        """
        statements = table.ddl()
        if table.name in destructive:
            self.conn.execute(f'DROP TABLE IF EXISTS "{table.name}"')
            for statement in statements:
                self.conn.execute(statement)
            return  # 重建已按声明建好整张表，缺列随之补齐
        self.conn.execute(statements[0])  # 建表
        for column in self._missing_columns(table, differences):
            alter = table.add_column_ddl(column)
            if alter is not None:  # 补不上的那些已在 differences() 里按破坏性报出
                self.conn.execute(alter)
        for index_name in self._stale_indexes(table, differences):
            self.conn.execute(f'DROP INDEX IF EXISTS "{index_name}"')  # 同名不同定义 → 拆掉重建
        for statement in statements[1:]:  # 建索引（必须在补列之后）
            self.conn.execute(statement)

    @staticmethod
    def _stale_indexes(table: TableSpec, differences: list[Difference]) -> list[str]:
        """同名、定义已变的索引（先拆掉，随后按声明重建）。"""
        return [
            item.detail.split(":", 1)[0]
            for item in differences
            if item.kind == "index_mismatch" and item.table == table.name
        ]

    @staticmethod
    def _missing_columns(table: TableSpec, differences: list[Difference]) -> list[Column]:
        """这张表里"缺、且能原地补"的列（顺序即声明顺序）。"""
        missing = {
            item.detail
            for item in differences
            if item.kind == "missing_column" and item.table == table.name
        }
        return [column for column in table.columns if column.name in missing]

    def verify_declarations(self) -> None:
        """校验库里记的声明投影与程序当前声明一致；不一致即报错。

        这是"表声明走配置"的落点之一：配置里那份是**投影**，
        它一旦与声明不符，说明有人手改了生成物或代码与库脱节。
        """
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (_META_KEY,)).fetchone()
        if row is None:
            return
        stored = json.loads(str(row["value"]))
        if stored != _canonical_declarations():
            raise IndexSchemaError("库内记录的声明投影与当前声明不一致（先跑对齐或迁移）")

    def recorded_declarations(self) -> dict[str, object]:
        """库里记录的那份声明投影（供巡检 / 排查）。"""
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (_META_KEY,)).fetchone()
        if row is None:
            return {}
        parsed: object = json.loads(str(row["value"]))
        if not isinstance(parsed, dict):
            raise RecordFormatError("库内声明投影不是映射")
        return {str(key): value for key, value in parsed.items()}

    # ---- 入口四件事（§8.1）：筛 / 计数 / 地址反查 / 边 ----
    def record_row(self, value_uuid: str) -> sqlite3.Row | None:
        """按身份取定位行。"""
        row: sqlite3.Row | None = self.conn.execute(
            "SELECT * FROM record WHERE value_uuid = ?", (value_uuid,)
        ).fetchone()
        return row

    def find_by_hash(self, value_hash: str) -> list[sqlite3.Row]:
        """地址反查：哪些记录的内容是这一份（去重命中时用）。"""
        return list(
            self.conn.execute("SELECT * FROM record WHERE value_hash = ?", (value_hash,)).fetchall()
        )

    def count(self, *, kind: str | None = None) -> int:
        """计数（可按类型）；不扫载体。"""
        if kind is None:
            row = self.conn.execute("SELECT COUNT(*) AS n FROM record").fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM record WHERE kind = ?", (kind,)
            ).fetchone()
        return int(row["n"])

    def upsert_record(self, row: Mapping[str, object]) -> None:
        """写入 / 更新一条定位行（位置永远由载体的实际写入结果给出）。"""
        columns = list(row)
        names = ", ".join(f'"{name}"' for name in columns)
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(f'"{name}" = excluded."{name}"' for name in columns)
        self.conn.execute(
            f"INSERT INTO record ({names}) VALUES({placeholders}) "
            f"ON CONFLICT(value_uuid) DO UPDATE SET {updates}",
            [row[name] for name in columns],
        )

    def remove_record(self, value_uuid: str) -> bool:
        """摘掉一条定位行；返回它此前是否存在。

        **只摘行**：载体里的字节留着，等压实回收——物理坐标是投影，删投影不动事实（§5.2）。
        """
        cursor = self.conn.execute("DELETE FROM record WHERE value_uuid = ?", (value_uuid,))
        return cursor.rowcount > 0

    def edges(self, *, src: str = "", dst: str = "", kind: str = "") -> list[sqlite3.Row]:
        """按来源 / 目标 / 种类查边（拓扑遍历的入口）。"""
        clauses: list[str] = []
        values: list[object] = []
        for name, value in (("src", src), ("dst", dst), ("kind", kind)):
            if value:
                clauses.append(f'"{name}" = ?')
                values.append(value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        # 子句由固定列名与占位符拼成，值全部走参数；唯一动态部分是 AND 的个数。
        sql = f"SELECT * FROM edge{where}"  # noqa: S608
        return list(self.conn.execute(sql, values).fetchall())

    def put_edge(
        self,
        *,
        src: str,
        dst: str,
        kind: str,
        domain: str = "",
        edge_id: str = "",
    ) -> str:
        """写一条边（一等行）；``edge_id`` 不给即按内容算，故同一关系重复写不产生第二行。"""
        identifier = edge_id or _edge_id(src, dst, kind, domain)
        self.conn.execute(
            "INSERT OR REPLACE INTO edge(id, src, dst, kind, domain, created)"
            " VALUES(?, ?, ?, ?, ?, ?)",
            (identifier, src, dst, kind, domain, now_ms()),
        )
        return identifier


def _stranger_tables(conn: sqlite3.Connection) -> list[str]:
    """已有的表里，哪些说明"这不是我们的库"。

    判据：库中已有表（`meta` 除外），却**一张都不是本程序声明的**——那不是我们的库
    （旧格式的目录同样撞在这一条上：它有自己的 packs / contents / blocks）。
    只建过 `meta` 的库**不拦**：那是刚 `open`、还没对齐的样子。
    """
    declared = {table.name for table in declared_tables()}
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    names = {str(row["name"]) for row in rows}
    if names - {"meta"} and not names & declared:
        return sorted(names)
    return []


def _canonical_declarations() -> dict[str, object]:
    """当前声明的规范化投影：按表名归拢的 :meth:`TableSpec.signature`（列与索引有序，摘要稳定）。"""
    return {table.name: table.signature() for table in declared_tables()}


def _edge_id(src: str, dst: str, kind: str, domain: str) -> str:
    """边的身份：由四元组算摘要，故同一关系天然幂等。"""
    payload = f"{src}\x1f{dst}\x1f{kind}\x1f{domain}".encode()
    return str(ValueHash.of(payload, context=b"edge"))


__all__ = ["INDEX_NAME", "Difference", "Index", "RebuildPlan"]

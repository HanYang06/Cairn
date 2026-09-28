# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""存储侧的**引擎角色**：对象进 / 出 / 删（表一里的固定件），坐在新底座上。

分层交代清楚——这一层只是**适配**，不承载任何存储语义：

    引擎（`Signal`）→ 本模块 `Storage` → `BlockStore`（块 ⇄ 记录）→ `Vault`（记录 → 桶 → 载体）

内核的 `Core.put/get/drop` 组出事件包，引擎按 ``role_name="storage"`` 找到它，
调用 :meth:`Storage.store` / :meth:`Storage.fetch` / :meth:`Storage.drop`。
它**不认识领域语义**（不知道什么是笔记、什么是项目），只认识块与库。

与旧实现的三处不同（旧层已退役，见设计篇 §11）：

1. 载体与目录换成了 :class:`~core.storage.vault.Vault` + :class:`~core.storage.blocks.BlockStore`：
   去重键、类型、时间全部由新底座给出，这里不再碰 sqlite 表结构；
2. **没有 mount / bind_tables**：那套"块自描述建表"无人覆写，随旧层一并去掉；
   领域表走 :meth:`Storage.table`（显式拿句柄），或进表声明（`tables.yaml`）；
3. 库级入口从 ``.catalog`` 改成 :attr:`Storage.vault`——巡检、重建、声明对账都从那儿走。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

from core.types import ObjectInfo, ObjectNotFoundError, type_name

from .block import Block
from .blocks import BlockStore, block_fields
from .table import Table, create_table

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator
    from pathlib import Path

    from .vault import Vault


class Storage:
    """引擎调用它完成对象进 / 出 / 删；其余能力一律转交底层库。"""

    name = "storage"

    def __init__(self, blocks: BlockStore) -> None:
        self.id = "storage"
        self.blocks = blocks
        self._tables: set[str] = set()
        """本实例已经确认存在的领域表（免得每次取句柄都重跑一遍建表）。"""

    # ---- 生命周期 ----
    @classmethod
    def open(cls, path: Path | str) -> Storage:
        """开库（不存在即建）；**开库即对齐声明**，失败向外传播，不掩盖。"""
        return cls(BlockStore.open(path))

    def close(self) -> None:
        """关库（释放索引库连接）。"""
        self.blocks.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- 引擎调用的动作面 ----
    def store(self, obj: Block) -> Block:
        """**存**一个对象（写内容记录 ＋ 块记录；去重发生在内容面）。"""
        return self.blocks.store(obj)

    def get[T: Block](self, cls: type[T], oid: str) -> T:
        """**取**一个对象（按类型还原）——与旧调用点对齐的入口。"""
        return self.blocks.get(cls, str(oid))

    def fetch(self, oid: str) -> Block:
        """**取**一个对象（未知类型时按基类还原）。"""
        return self.blocks.fetch(str(oid))

    def drop(self, oid: str) -> bool:
        """**删**一个对象；返回它此前是否存在。"""
        return self.blocks.drop(str(oid))

    # ---- 库级视图 ----
    @property
    def vault(self) -> Vault:
        """底层库。

        巡检（:meth:`Vault.patrol`）、重建（:meth:`Vault.repair`）、声明对账
        （:meth:`Vault.verify`）与表声明都从这儿进。
        """
        return self.blocks.vault

    def commit(self) -> None:
        """提交当前变更（领域表写入后由调用方收口，见 `feature/shared/relation.py`）。"""
        self.vault.index.commit()

    def ids(self) -> Iterator[str]:
        """遍历全部**对象**身份（内容记录不是对象，不在此列）。

        只读定位行与块记录，**不读正文**：列身份不该把全库正文拉进内存。
        """
        for row, _record in self.blocks.iter_block_records():
            yield str(row["value_uuid"])

    def info_of(self, oid: str) -> ObjectInfo:
        """取对象的中立视图（类型 / 标题 / 标签 / 时间）——只读块记录，不读正文。"""
        row = self.vault.index.record_row(str(oid))
        if row is None:
            raise ObjectNotFoundError(str(oid))
        return self._info_of_row(row)

    def infos(self) -> list[ObjectInfo]:
        """**批量**取中立视图（同样不读正文）。

        ``attrs`` / ``author`` 在块记录载荷里、``kind`` 与时间在定位行里，故列举不必碰正文；
        正文长度随块记录存了一份（`body_size`）也是为这件事。**要正文请走** :meth:`fetch`。
        排序按身份：身份是时间有序的，故这一序就是创建顺序（旧实现的表也是这么排的）。
        """
        return [self._info_of_row(row) for row, _record in self.blocks.iter_block_records()]

    def _info_of_row(self, row: sqlite3.Row) -> ObjectInfo:
        """定位行 ＋ 块记录载荷 → 中立视图。

        载荷里**没有** `body_size`（本次改动之前写下的块）时退回到读一次块——
        宁可慢这一条，也不把"长度未知"伪造成 0。
        """
        record = self.vault.get(str(row["value_uuid"]))
        blob = block_fields(record)
        size = blob.get("body_size")
        if not isinstance(size, int):
            return _info_of(self.blocks.fetch(str(row["value_uuid"])))
        return _info_of_parts(
            oid=str(row["value_uuid"]),
            kind=str(row["kind"]),
            attrs=dict(blob.get("attrs") or {}),
            author=str(blob.get("author") or ""),
            size=size,
            created=int(row["created"]),
            updated=int(row["updated"]),
        )

    # ---- 逃生口：上层不 import sqlite ----
    def table(self, name: str, **columns: str) -> Table:
        """按需建一张**领域表**并返回句柄：``storage.table("relation", id="TEXT PRIMARY KEY")``。

        两条纪律（评审指出的两条都在这）：

        - **建表只在本实例第一次取这张表时发生**，之后取句柄是纯读操作——
          调用方（如 `feature/shared/relation.py`）每次读写都传 ``columns``，
          若每次都建表 + 提交，就等于把 DDL 与提交放回了读写路径（§8.4 明令不许）；
        - **不额外提交**：只有真建了表才提交一次。否则调用方尚未提交的写入会被旁路提交，
          回滚就救不回来了。
        列的声明以第一次为准：同一实例里再传一套不同的列不会改结构（改结构是显式动作）。
        """
        if columns and name not in self._tables:
            existed = _table_exists(self.vault.index.conn, name)
            if not existed:
                create_table(self.vault.index.conn, name, columns)
                self.commit()
            self._tables.add(name)
        return Table(self.vault.index.conn, name)

    def query(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> list[sqlite3.Row]:
        """只读查询（应急口：内核自己的表有具名入口，复杂排查才用它）。"""
        return list(self.vault.index.conn.execute(sql, list(params)).fetchall())

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> int:
        """写语句（应急口，口径同 :meth:`query`）。

        **不隐式提交**——与 :meth:`table` 同一纪律：存储的写入口都由调用方
        `commit()` 收口；一条语句一个提交点，会让"回滚"在不同调用路径上表现不一。
        """
        cursor = self.vault.index.conn.execute(sql, list(params))
        return int(cursor.rowcount)

    def __repr__(self) -> str:
        return f"Storage({self.vault.root})"


def _by_id(block: Block) -> str:
    """排序键：对象身份（时间有序，故即创建顺序）。"""
    return block.id


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """库里有没有这张表（`sqlite_master` 是唯一权威）。"""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _info_of(block: Block) -> ObjectInfo:
    """块 → 中立视图。

    ``author`` 是块的**顶层字段**（不在 ``attrs`` 里），故这里读块字段；
    ``title`` / ``tags`` / ``mime`` 是属性，从 ``attrs`` 取。
    """
    return _info_of_parts(
        oid=block.id,
        kind=block.type,
        attrs=block.attrs,
        author=str(block.author or ""),
        size=block.size,
        created=block.created,
        updated=block.updated,
    )


def _info_of_parts(  # noqa: PLR0913 — 视图字段本就这么多，收成一个对象只是换个壳
    *,
    oid: str,
    kind: Any,
    attrs: dict[str, Any],
    author: str,
    size: int,
    created: int,
    updated: int,
) -> ObjectInfo:
    """中立视图的装配（单件与列举共用一处，免得两条路径给出不同形状的视图）。"""
    return ObjectInfo(
        oid=oid,
        type=type_name(kind),
        mime=attrs.get("mime"),
        size=size,
        created=created,
        updated=updated,
        title=attrs.get("title"),
        tags=_tags_of(attrs.get("tags")),
        seq=1,
        author=author,
    )


def _tags_of(raw: Any) -> dict[str, Any]:
    """标签归一：映射原样（键转字符串）、裸字符串算单标签、序列算一组按键存在。"""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {str(key): value for key, value in raw.items()}
    if isinstance(raw, str):
        return {raw: None}
    return {str(tag): None for tag in raw}


__all__ = ["Storage"]

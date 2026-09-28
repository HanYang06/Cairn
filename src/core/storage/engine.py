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

from core.types import ObjectInfo, type_name

from .block import Block
from .blocks import BlockStore
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
        """遍历全部**对象**身份（内容记录不是对象，不在此列）。"""
        for block in self.blocks.iter_blocks():
            yield block.id

    def info_of(self, oid: str) -> ObjectInfo:
        """取对象的中立视图（类型 / 标题 / 标签 / 时间）。"""
        return _info_of(self.blocks.fetch(str(oid)))

    def infos(self) -> list[ObjectInfo]:
        """**批量**取中立视图。

        ``attrs`` 不在索引里（它属于载荷），故整表列举必然要读回每条记录——
        这是"索引只放能被快速筛出来的东西"的直接代价，换来的是索引不必跟着属性走样。
        排序按身份：身份是时间有序的，故这一序就是创建顺序（旧实现的表也是这么排的）。
        """
        return [_info_of(block) for block in sorted(self.blocks.iter_blocks(), key=_by_id)]

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
        """写语句（应急口，口径同 :meth:`query`）。"""
        cursor = self.vault.index.conn.execute(sql, list(params))
        self.commit()
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
    attrs = block.attrs
    return ObjectInfo(
        oid=block.id,
        type=type_name(block.type),
        mime=attrs.get("mime"),
        size=block.size,
        created=block.created,
        updated=block.updated,
        title=attrs.get("title"),
        tags=_tags_of(attrs.get("tags")),
        seq=1,
        author=str(block.author or ""),
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

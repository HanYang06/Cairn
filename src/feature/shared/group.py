# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""组：**存储数据结构**（``GroupData(Block)``），不是域。

- ``GroupData``：域身份 ``gid``（≠ 块 ``oid``）+ 有序子项 ``group`` 列表（结构）。
- 增删 / 重排 / 嵌套解析都是**数据结构自身的操作**，由需要它的域（Note / Project…）使用。

成员关系**两套都存**：``group`` 列表存结构（顺序），``relation`` 表存 ``contains``（反查）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Self

from core.storage import Block, BodyField
from core.types import ValueUuid
from core.types.attr import Attr  # noqa: TC001 — 标注工具在类体里被解析器扫描，运行期必须存在

from .base import DomainError
from .kinds import Kind
from .relation import CONTAINS as _CONTAINS
from .relation import Relation

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

GROUP_KIND = Kind.Data.Group
GROUP_MIME = "application/x-cairn-group"
GROUP_SCHEMA = 1


class GroupError(DomainError):
    """组操作非法（如锁定后编辑）。"""


class GroupData(Block):
    """组数据块：``gid`` 为域身份，``group`` 为有序子项 ID 列表。"""

    type = GROUP_KIND
    mime: ClassVar[str | None] = GROUP_MIME
    body = BodyField()

    schema: Attr[int] = GROUP_SCHEMA
    gid: Attr[str] = ""
    title: Attr[str] = ""
    lock: Attr[bool] = False
    owner: Attr[str] = ""
    key: Attr[str] = ""
    group: list[str] = []  # noqa: RUF012  # 有序子项 ID 列表（结构）
    member: list[str] = []  # noqa: RUF012  # 预留：社区成员（User 系统落地后换类型）

    # ---- 创建 / 查 ----
    @classmethod
    def create(  # noqa: PLR0913 — 构造入口参数面，均有默认值
        cls,
        core: Any,
        title: str = "",
        *,
        parent: GroupData | None = None,
        key: str = "",
        owner: str = "",
        member: Iterable[str] | None = None,
    ) -> Self:
        """新建一个组并落盘；给了 ``parent`` 则同时加入父组。"""
        data = cls()
        data.core = core  # 数据对象身上带内核（它继承 Block，不继承 Managed）
        data.gid = str(ValueUuid.new())
        data.title = title
        data.key = key
        data.owner = owner
        data.member = [str(item) for item in member or ()]
        core.put(data)
        if parent is not None:
            parent.add(data)
        return data

    @classmethod
    def by_gid(cls, core: Any, gid: str) -> GroupData | None:
        """按域 ID 找组。"""
        for group in cls.list(core):
            if group.gid == gid:
                return group
        return None

    # ---- 子项 ----
    def require_unlocked(self) -> None:
        """锁定则拒绝编辑。"""
        if self.lock:
            raise GroupError(f"组已锁定，不可编辑: {self.gid or self.id}")

    @staticmethod
    def ref_of(child: Block | str) -> str:
        """子项在 ``group`` 列表里的 ID：组存 ``gid``，其余存块 ``oid``。"""
        if isinstance(child, GroupData):
            return child.gid or str(child.oid)
        if isinstance(child, Block):
            return str(child.oid)
        return str(child)

    @staticmethod
    def target_of(child: Block | str) -> str:
        """子项在 ``contains`` 关系行里的 ``dst``：块存 ``oid``，裸字符串原样。

        与 ``ref_of`` 不同（组在列表里存 ``gid``）——建边与拆边必须用同一个值，
        故 ``_link`` / ``remove`` 都走这里。
        """
        return str(child.oid) if isinstance(child, Block) else str(child)

    def add(self, child: Block | str) -> Self:
        """把笔记 / 项目 / 组加进本组（去重、保序），并落一条 ``contains`` 关系。"""
        self.require_unlocked()
        ref = self.ref_of(child)
        if ref and ref not in self.group:
            self.group = [*self.group, ref]
            self._link(child)
            self.save()
        return self

    def remove(self, child: Block | str) -> Self:
        """从本组移除子项：摘列表 + 删掉对应的 ``contains`` 关系行。"""
        self.require_unlocked()
        self.group = [ref for ref in self.group if ref != self.ref_of(child)]
        Relation.delete(
            self.core,
            source=self.oid,
            target=self.target_of(child),
            relation=_CONTAINS,
        )
        self.save()
        return self

    def move(self, order: Sequence[int]) -> Self:
        """按旧下标重排子项；``order`` 必须是 ``0..n-1`` 的完整排列。"""
        self.require_unlocked()
        items = list(self.group)
        if sorted(order) != list(range(len(items))):
            raise GroupError(f"重排下标必须是 0..{len(items) - 1} 的完整排列: {list(order)}")
        self.group = [items[index] for index in order]
        self.save()
        return self

    # ---- 解析 ----
    def subgroups(self) -> list[GroupData]:
        """按 ``gid`` 解析出子组（引用不到的忽略），保持列表顺序。"""
        index = {group.gid: group for group in GroupData.list(self.core)}
        return [index[ref] for ref in self.group if ref in index]

    def _link(self, child: Block | str) -> None:
        Relation.create(
            self.core,
            self.oid,
            self.target_of(child),
            relation=_CONTAINS,
            domain="group",
        )


def list_groups(core: Any) -> Iterator[GroupData]:
    """列出全部组。"""
    return GroupData.list(core)


def all_gids(core: Any) -> set[str]:
    """全部组的 ``gid`` 集合（判定子项是组还是普通块）。"""
    return {group.gid for group in GroupData.list(core)}


def roots(core: Any) -> list[GroupData]:
    """没有被任何组包含的组。"""
    groups = list(GroupData.list(core))
    contained: set[str] = set()
    for group in groups:
        contained.update(group.group)
    return [group for group in groups if group.gid not in contained]


__all__ = [
    "GROUP_KIND",
    "GROUP_MIME",
    "GROUP_SCHEMA",
    "GroupData",
    "GroupError",
    "all_gids",
    "list_groups",
    "roots",
]

# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""项目领域：**数据**（``ProjectData``）与**域服务**（``Project``）分离。

- ``ProjectData(Block)``：具名容器数据 + 属性。
- ``Project(Domain)``：域服务——创建 / 载入 / 更新 / 成员关系（``contains``）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.core import Core, Managed
from core.storage import Block, BodyField
from core.types import ValueUuid
from core.types.attr import Attr

from ..shared.base import UNSET, normalize_tags
from ..shared.kinds import Kind
from ..shared.relation import CONTAINS, Relation

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

PROJECT_KIND = Kind.Data.Projectdata
PROJECT_SCHEMA = 1


class ProjectData(Block):
    """项目数据块：承载一组条目（``contains`` 关系）。"""

    type = PROJECT_KIND
    body = BodyField(factory=list)

    schema: Attr[int] = PROJECT_SCHEMA
    title: Attr[str | None] = None
    tags: Attr = Attr(factory=dict, coerce=normalize_tags)

    @property
    def name(self) -> str | None:
        return self.title

    @property
    def description(self) -> str | None:
        value = self.props().get("description")
        return None if value is None else str(value)


class Project(Managed):
    """项目域服务（单例）：创建 / 载入 / 更新 / 成员关系。"""

    type = Kind.Feature.Project
    name = "project"  # 门户上的寻址键
    data = (ProjectData,)  # 本域用到的数据类
    light = [ProjectData]  # noqa: RUF012 — 最小数据单元（可多个）

    def __init__(self, core: Core) -> None:
        super().__init__(core)  # 接门户（登记 + 记住内核）

    def create(
        self,
        name: str,
        *,
        description: str | None = None,
        tags: Iterable[str] | Mapping[str, Any] | None = None,
        props: dict[str, Any] | None = None,
    ) -> ProjectData:
        """新建项目并落盘。"""
        data = ProjectData()
        data.core = self.core  # 数据对象身上带内核（它继承 Block，不继承 Managed）
        data.title = name
        merged = dict(props or {})
        if description is not None:
            merged["description"] = str(description)
        data.attrs["props"] = merged
        data.tags = tags or {}
        self.core.put(data)
        return data

    def load(self, oid: str) -> ProjectData:
        """按 oid 载入项目数据（经内核）。"""
        data: ProjectData = self.core.get(ProjectData, str(oid))
        data.core = self.core
        return data

    def update(
        self,
        data: ProjectData,
        *,
        name: str | None = UNSET,
        description: str | None = UNSET,
        tags: Iterable[str] | Mapping[str, Any] | None = None,
        props: dict[str, Any] | None = None,
    ) -> ProjectData:
        """更新项目属性并落盘。"""
        merged = data.props()
        if props is not None:  # props 先合并（与 create 一致），显式 description 再覆盖
            merged.update(props)
        if description is not UNSET:
            if description is None:
                merged.pop("description", None)
            else:
                merged["description"] = str(description)
        if name is not UNSET:
            data.title = name
        if tags is not None:
            data.tags = tags
        data.attrs["props"] = merged
        self.core.put(data)
        return data

    def add_member(
        self,
        data: ProjectData,
        member: str,
        *,
        relation: str = CONTAINS,
    ) -> Relation:
        """把一个对象加为项目成员（已存在则返回既有边，保证幂等）。"""
        target = str(ValueUuid.parse(str(member)))
        for edge in Relation.outbound(self.core, data.oid, relation=relation):
            if edge.target == target:
                return edge
        return Relation.create(self.core, data.oid, member, relation=relation, domain="project")

    def members(self, data: ProjectData) -> list[str]:
        """项目成员（``contains`` 边的目标）。"""
        return [edge.target for edge in Relation.outbound(self.core, data.oid, relation=CONTAINS)]


__all__ = ["CONTAINS", "PROJECT_KIND", "PROJECT_SCHEMA", "Project", "ProjectData"]

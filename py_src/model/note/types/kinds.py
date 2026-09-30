# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""行类型词表：一行**是什么**。

`linetype` **不装属性**——它只回答"这一行是什么"，同时充当 `data` 的**判别位**：
读 `data` 之前必须先按它分支，故它是闭集枚举，不是自由文本。细分参数（标题级别、
代码语言、列表层级一类）随该行自己的 `data` 走，不塞进枚举。

**引用解析的入口只有这一处**：标题之外的"内容"（媒体资产、画板、别的笔记）在行里
都只以一串 ID 出现，拿到 ID 之后"该查哪张表"由 `REFERENCE_TABLES` 给出。这份映射
必须一处定义——漏了它，"看类型去查"就没有依据。
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["REFERENCE_TABLES", "LineAction", "LineKind", "reference_table"]


class LineKind(StrEnum):
    """行的语义类型：值即落盘字符串（短名、无前缀）。

    枚举成员按"内容类 → 引用类"排列，与 `REFERENCE_TABLES` 的两拨对得上。
    """

    TEXT = "text"
    """纯文本：`data` 是字符串。"""

    HEADING = "heading"
    """文本内标题：`data` 是 `Heading`（级别 + 文字）。缺省即最高一级。"""

    LIST = "list"
    """列表项：`data` 是 `ListItem`（层级 + 有序无序 + 文字）。"""

    CODE = "code"
    """代码：`data` 是 `Code`（语言 + 文字）。"""

    TODO = "todo"
    """待办：`data` 是 `Todo`（勾选状态 + 文字）。"""

    LINK = "link"
    """链接：`data` 是 `Link`。目标两可（站内笔记或站外地址），故不在落点表里。"""

    ASSET = "asset"
    """媒体引用：`data` 是 `Ref`，装一串资产 ID。"""

    CANVAS = "canvas"
    """画板引用：`data` 是 `Ref`，装画板 ID。"""

    NOTE = "note"
    """嵌入的笔记：`data` 是 `Ref`，装笔记 ID。"""


class LineAction(StrEnum):
    """正文变更的**三种形式**：新增 / 修改 / 删除。

    变更记录只记"行 ID + 一个动作"，**不写内容**——内容按行 ID 回当前正文里取。
    """

    INSERT = "insert"
    """新增：这一行是这一步加进来的（内容与位置都在当前正文里）。"""

    CHANGE = "change"
    """修改：这一行的内容在这一步变了。"""

    DELETE = "delete"
    """删除：这一行在这一步被去掉（它已不在正文里，故只剩 ID）。"""


REFERENCE_TABLES: Mapping[LineKind, str] = MappingProxyType(
    {
        LineKind.ASSET: "noteasset",
        LineKind.CANVAS: "notecanvas",
        LineKind.NOTE: "notedata",
    }
)
"""引用类的落点：`linetype` → 目标表名。

**只有目标唯一的那些进来**：`ASSET` / `CANVAS` / `NOTE` 各自指向一张表，故这里是答案；
`LINK` 的目标两可（站内 ID 或站外地址），由它自己的 `data` 说，不在这张表里；
内容类的 `data` 就是正文，没有目标可查。

表名带 `note` 前缀是刻意的：领域专属的类型以**域名开头**，于是 `project` 那边可以做出
同名概念而互不相干（各自一张表、不互相引用），"这是谁的资产"看一眼表名就清楚。
"""


def reference_table(kind: LineKind) -> str | None:
    """这个行类型的目标表名；内容类与 `LINK` 没有唯一答案，返回 `None`。

    Args:
        kind: 行的语义类型。

    Returns:
        目标表名（可拿去问登记表），或 `None`。
    """
    return REFERENCE_TABLES.get(kind)

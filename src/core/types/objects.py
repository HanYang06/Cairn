# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""内核数据结构：对象层结构（元数据视图、巡检报告）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ObjectInfo:
    """对象的元数据视图，不含其内容。

    ``tags`` 是 ``dict``，故标 ``compare=False``：不参与 ``__eq__`` / ``__hash__``，
    ``ObjectInfo`` 才能真的可哈希（否则一放进 set 就 ``TypeError: unhashable``）。
    ``frozen`` 只锁字段本身——``tags`` 的内容仍可就地改，深不可变不在承诺内。

    ``oid`` 是身份的**字符串形态**（`ValueUuid` 就是字符串，故这里不收窄类型）：
    视图是给界面与领域用的，它们不该为此认识身份层的具体类。
    """

    oid: str
    type: str
    mime: str | None
    size: int
    created: int
    updated: int
    title: str | None = None
    tags: dict[str, Any] = field(default_factory=dict, compare=False)
    seq: int = 0
    author: str = ""


@dataclass(frozen=True, slots=True)
class VerifyReport:
    """完整性巡检结果。``problems`` 为空表示健康。"""

    objects: int
    problems: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.problems

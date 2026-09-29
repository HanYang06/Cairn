# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""块与载荷：块是身份壳，body 是块自带的载荷。

块不携带领域语义词，承载类型由继承类给出；body 的承载结构不收窄，
但落盘前必须能给出确定性编码，否则同一逻辑内容会算出不同地址、去重失效。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .id import ID


@dataclass(slots=True)
class Body[T]:
    """数据载荷载体。

    Attributes:
        data: 载荷；字符串、列表、字典、二进制皆可，结构不作收窄。
        id: 载荷的身份；摘要形态由载荷内容算出（见 `ID.of`）。
    """

    data: T | None = None
    id: ID = field(default_factory=ID)


@dataclass(slots=True)
class Block[T]:
    """存储单元：身份壳加自包含属性。

    Attributes:
        id: 块自身的身份。
        body: 块携带的载荷；先立壳、后挂载荷，故默认给一份空载荷。
    """

    id: ID = field(default_factory=ID)
    body: Body[T] = field(default_factory=Body[T])


__all__ = ["Block", "Body"]

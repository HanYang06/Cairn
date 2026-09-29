# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""块与载荷：块是身份壳，body 是块自带的载荷。

块不携带领域语义词，承载类型由继承类给出；body 的承载结构不收窄，
但落盘前必须能给出确定性编码，否则同一逻辑内容会算出不同地址、去重失效。

**一块落成两条记录**（设计篇 §3.2.1、§4.4）：

- **内容记录**：载荷就是 body 字节本身，身份由内容签发，故同内容只存一份；
- **块记录**：载荷是指向 body 的指针，身份是块自己的。

于是"块记录还是内容记录"要靠**载荷里的保留键**分辨（§3.2.1）：保留键带不可打印前缀，
业务数据不可能占用它。若拿一个业务可能用到的普通键（例如 ``body_addr``）当判据，
一份形如 ``{"body_addr": …}`` 的正文就会被误判成块记录，去重失效、列举整体报错。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cbor2

from .id import ID

BODY_ADDR_KEY = "\x00cairn.body_addr"
"""块记录载荷里的保留键：指向 body 的内容地址。前缀即"业务数据不可能占用"的命名空间。"""


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


def encode_block_payload(body_addr: str) -> bytes:
    """把"指向 body 的指针"编成块记录的载荷（canonical CBOR）。

    规范化是必须的：同一份指针每次都要编出同一段字节，否则块身份（载荷摘要）会漂。
    """
    return cbor2.dumps({BODY_ADDR_KEY: body_addr}, canonical=True)


def body_addr_of(payload: bytes) -> str | None:
    """从记录载荷里取出 body 指针；**不是块载荷**即返回 ``None``（那它就是内容）。

    判据只有一条：载荷是不是一个带保留键的映射。解不成映射、映射里没有保留键、
    或键值不是字符串，都算"这是内容记录"，不猜、不降级。
    """
    try:
        decoded = cbor2.loads(payload)
    except cbor2.CBORDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    address = decoded.get(BODY_ADDR_KEY)
    return address if isinstance(address, str) else None


__all__ = ["BODY_ADDR_KEY", "Block", "Body", "body_addr_of", "encode_block_payload"]

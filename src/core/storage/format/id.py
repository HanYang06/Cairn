# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""系统级富信息 ID 结构定义。

ID 是身份证，不是"一个字段加一串内容"：它同时回答两个问题。

- **这是谁**：本体内含两套凭证并存，互不替代——`value_uuid` 是签发时分配的
  唯一标识（比较有效、去重无效），`value_hash` 是由内容算出的摘要
  （去重有效、比较无效）。前者使同内容的两次落盘仍可区分与引用，后者使
  同内容判重成立，两者合起来才构成内容寻址对象池的身份。
- **在哪儿**：`in_hub` / `in_hub_pack` / `in_pack_slot` 记下物理坐标。
  该段允许冗余与可推导值：它的服务对象是人眼排查，不是关键路径。
  落盘只取必需子集（由存储层决定），位置段不随之入库。

`value_hash` 在签发时就由内容算出，故能签发的只有"有内容"的 ID；
不知道内容时留空串，由存储层在写入时补齐——空串是"未绑定内容"的唯一写法，
不得用随机值冒充摘要。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from hashlib import sha256
from uuid import uuid4

_EMPTY_SLOT: tuple[int, int] = (0, 0)


def new_uuid() -> str:
    """签发一个新的唯一标识形态凭证。

    与内容无关，每次调用均得新值。生成规则是 ID 专项的裁定点：此处换实现
    （如换时间有序的 26 字符写法）只影响本函数，不波及调用方。
    """
    return str(uuid4())


def digest(data: bytes) -> str:
    """按内容算出摘要形态凭证（小写十六进制）。

    与内容寻址共用同一口径：同内容同值，内容变则值变。换算法同样只动此处。
    """
    return sha256(data).hexdigest()


def now_ns() -> int:
    """当前时间（unix 纳秒）。"""
    return time.time_ns()


@dataclass(slots=True)
class ID:
    """系统级富信息 ID。

    默认值一律由 `field(default_factory=…)` 给出：dataclass 的普通默认值在
    **类定义时求值一次**，写成 `value_uuid: str = str(uuid4())` 会让所有实例
    共用同一个身份，这一类错误在内容寻址的底座上是致命的。

    位置段可写，故本类型不是冻结的。

    Attributes:
        name: 可读名称，由所在容器给出（body 里叫 body ID，块里叫块 ID），可为空。
        value_uuid: 分配形态凭证；签发时定，与内容无关。
        value_hash: 摘要形态凭证；由内容算出，未绑定内容时为空串。
        birth_time: 该 ID 被签发的时间（unix 纳秒）；不等于块或数据的创建时间。
        in_hub: 所属 hub。
        in_hub_pack: hub 内的载体。
        in_pack_slot: 载体内的槽位坐标 (槽, 槽内偏移)。
    """

    name: str = ""
    value_uuid: str = field(default_factory=new_uuid)
    value_hash: str = ""
    birth_time: int = field(default_factory=now_ns)
    in_hub: str = ""
    in_hub_pack: str = ""
    in_pack_slot: tuple[int, int] = _EMPTY_SLOT

    @classmethod
    def of(cls, data: bytes) -> ID:
        """按内容签发 ID：摘要形态由 `data` 算出，分配形态与内容无关。

        位置段与名称由存储层在写入时补写，故此处不设参数。
        """
        return cls(value_hash=digest(data))

    @property
    def located(self) -> bool:
        """是否已写上物理坐标（hub 与载体都有值）。"""
        return bool(self.in_hub) and bool(self.in_hub_pack)

    def same_content(self, other: ID) -> bool:
        """两者是否指向同一份内容：只比摘要形态，且未绑定内容者恒不相等。"""
        return bool(self.value_hash) and self.value_hash == other.value_hash


__all__ = ["ID", "digest", "new_uuid", "now_ns"]

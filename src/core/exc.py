# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""内核异常声明。

异常层只做一件事：把"哪一层在什么情况下退出"写成一个类型，调用方按类型分流、
日志按类型定级。此处只声明当前确有抛出点的异常；尚无抛出点的层不得预先占位。
"""

from __future__ import annotations


class CairnError(Exception):
    """内核异常基类：跨层兜底只认这一个。"""


class InvalidIdError(CairnError, ValueError):
    """标识符格式非法：唯一标识凭证或内容摘要凭证不满足各自的形态约束。"""


class StorageError(CairnError):
    """存储侧异常的基类：调用方按它兜住整层，再按子类分流。"""


class RecordFormatError(StorageError):
    """载体记录非法：长度自框定不符、校验和不符、截断或 ID 段不可解析。"""


class SlotError(StorageError):
    """槽区间非法：槽长不合法、槽数与记录长度不符，或读越界。"""


__all__ = [
    "CairnError",
    "InvalidIdError",
    "RecordFormatError",
    "SlotError",
    "StorageError",
]

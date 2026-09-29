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
    """槽区间非法：槽长不合法、末格与记录长度不符，或读越界。"""


class HubNotFoundError(StorageError):
    """hub 目录或载体不存在。**读路径不建东西**：不在就报错，不悄悄建一个空的顶上。"""


class HubShapeError(StorageError):
    """hub 的形状或内容不合规：目录缺 `packs/`，或 `packs/` 里混着不是载体的文件。"""


class TableDeclarationError(StorageError):
    """表声明非法：未知项、非法标识符或类型、重复、缺必填项，或重建档与来源不匹配。"""


class IndexNotFoundError(StorageError):
    """索引库文件不存在。**读路径不建库**：不在就报错，只有显式建立才创建文件。"""


class IndexSchemaError(StorageError):
    """库内结构与声明不一致，且该差异不允许自动处置（默认拒绝，须显式授权重建）。"""


class ObjectNotFoundError(StorageError):
    """对象不在存储里：索引没有这一行，或行指向的字节已经读不出来。"""


__all__ = [
    "CairnError",
    "HubNotFoundError",
    "HubShapeError",
    "IndexNotFoundError",
    "IndexSchemaError",
    "InvalidIdError",
    "ObjectNotFoundError",
    "RecordFormatError",
    "SlotError",
    "StorageError",
    "TableDeclarationError",
]

# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""基础异常体系（跨层共享）。"""

from __future__ import annotations


class CairnError(Exception):
    """所有 cairn 异常的基类。"""


class InvalidIdError(CairnError, ValueError):
    """标识符格式非法。"""


class ObjectNotFoundError(CairnError):
    """对象不存在。"""


class KindMismatchError(CairnError):
    """对象类型与期望的类型不匹配。"""


class CorruptObjectError(CairnError):
    """对象数据损坏或校验失败。"""


# ---- 存储侧 ----


class StorageError(CairnError):
    """存储侧异常的基类。"""


class BucketExistsError(StorageError):
    """桶已存在（重复创建）。"""


class BucketNotFoundError(StorageError):
    """桶不存在。"""


class SlotError(StorageError):
    """槽区间非法：越界、溢出载体，或与槽长不匹配。"""


class IndexSchemaError(StorageError):
    """表声明与实际结构不一致，且该差异不允许自动处置（拒绝启动）。"""


class RecordFormatError(StorageError):
    """载体记录头非法：长度、校验和或字段缺失。"""


__all__ = [
    "BucketExistsError",
    "BucketNotFoundError",
    "CairnError",
    "CorruptObjectError",
    "IndexSchemaError",
    "InvalidIdError",
    "KindMismatchError",
    "ObjectNotFoundError",
    "RecordFormatError",
    "SlotError",
    "StorageError",
]

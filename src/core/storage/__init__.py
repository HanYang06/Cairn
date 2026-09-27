# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""存储层：桶 + 块（新载体层已在位）。

    Bucket      载体——受管的文件系统，**类**，不是数据结构（旧层，待退役）
    Block       存储单元——``{id, checksum, type, body, attrs}``
    CarrierFile 载体文件——定长槽 + 自框定记录；顺扫即可重建
    Record      载体中的一条记录——头四项（总长 / 校验和 / ID / 槽数）+ 载荷
    Vault       多桶——一个库一个索引库；桶名是库里的一列

其余一切（笔记 / 项目 / 多媒体 / 索引 / 变更）都是块的一种 ``type`` / ``body``。

> 字段标注（``Attr`` / ``Data``）**不在这里**：它们是**声明**，见 `core.types.attr`。
> 存储只负责"放得进、取得出、找得到"，标注不属于它。
>
> 新旧两层**暂时并存**（接线与退役见 `docs/architecture/storage-design.md` §11）：
> 新层的桶类与旧 ``Bucket`` 同名，过渡期只在 `core.storage.vault` 内可见
> （``from core.storage.vault import Bucket``）；旧层退役后它就是 `core.storage.Bucket`。
"""

from __future__ import annotations

from .block import (
    BLOCK_VERSION,
    INDEX_TYPE,
    PART_TYPE,
    Block,
    Body,
    BodyField,
    canonical,
    decode_canonical,
)
from .bucket import CATALOG_NAME, Bucket, BucketConfig
from .carrier import CARRIER_HEADER_BYTES, CARRIER_MAGIC, CarrierLayout
from .catalog import BlockLocation, Catalog
from .engine import Storage
from .index import INDEX_NAME, Difference, Index, RebuildPlan
from .io import CarrierFile
from .record import Record, RecordHeader
from .table import Table
from .tables import Column, ColumnType, Owned, RebuildTier, declared_tables
from .vault import (
    BucketRole,
    BucketState,
    Finding,
    FindingKind,
    PatrolReport,
    Placement,
    Vault,
)

__all__ = [
    "BLOCK_VERSION",
    "CARRIER_HEADER_BYTES",
    "CARRIER_MAGIC",
    "CATALOG_NAME",
    "INDEX_NAME",
    "INDEX_TYPE",
    "PART_TYPE",
    "Block",
    "BlockLocation",
    "Body",
    "BodyField",
    "Bucket",
    "BucketConfig",
    "BucketRole",
    "BucketState",
    "CarrierFile",
    "CarrierLayout",
    "Catalog",
    "Column",
    "ColumnType",
    "Difference",
    "Finding",
    "FindingKind",
    "Index",
    "Owned",
    "PatrolReport",
    "Placement",
    "RebuildPlan",
    "RebuildTier",
    "Record",
    "RecordHeader",
    "Storage",
    "Table",
    "Vault",
    "canonical",
    "declared_tables",
    "decode_canonical",
]

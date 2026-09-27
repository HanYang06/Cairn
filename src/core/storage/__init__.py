# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""存储层：桶 + 块（新载体层已在位）。

    Bucket      载体——受管的文件系统，**类**，不是数据结构
    Block       存储单元——``{id, checksum, type, body, attrs}``
    CarrierFile 载体文件——定长槽 + 自框定记录；顺扫即可重建
    Record      载体中的一条记录——头四项（总长 / 校验和 / ID / 槽数）+ 载荷

其余一切（笔记 / 项目 / 多媒体 / 索引 / 变更）都是块的一种 ``type`` / ``body``。

> 字段标注（``Attr`` / ``Data``）**不在这里**：它们是**声明**，见 `core.types.attr`。
> 存储只负责"放得进、取得出、找得到"，标注不属于它。
>
> 新载体层（`carrier` / `record` / `io`）与旧目录（`catalog`）**暂时并存**：
> 接线与旧层退役见 `docs/architecture/storage-design.md` §11 的分期。
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
from .tables import Column, ColumnType, RebuildTier, canonical_tables
from .tables import tables as declared_tables

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
    "CarrierFile",
    "CarrierLayout",
    "Catalog",
    "Column",
    "ColumnType",
    "Difference",
    "Index",
    "RebuildPlan",
    "RebuildTier",
    "Record",
    "RecordHeader",
    "Storage",
    "Table",
    "canonical",
    "canonical_tables",
    "declared_tables",
    "decode_canonical",
]

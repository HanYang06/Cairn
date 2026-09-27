# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""存储层：块 + 桶（四层一条线，见 `docs/architecture/storage-design.md`）。

    Storage     引擎角色——对象进 / 出 / 删（坐在块面与库之上）
    BlockStore  块面——块 ⇄ 记录（内容记录 ＋ 块记录）
    Vault       多桶——一个库一个索引库；桶名是库里的一列
    Bucket      一个桶——`vault/<桶名>/packs/` 下的一串载体
    Record      载体中的一条记录——自框定（总长在最前）、自校验、自描述
    CarrierFile 载体文件——定长槽 + 记录；顺扫即可重建
    Index       索引库——对比 → 分类 → 处置；表声明编译成语句

其余一切（笔记 / 项目 / 多媒体 / 索引 / 变更）都是块的一种 ``type`` / ``body``。

> 字段标注（``Attr`` / ``Data``）**不在这里**：它们是**声明**，见 `core.types.attr`。
> 存储只负责"放得进、取得出、找得到"，标注不属于它。
>
> 旧层（旧 `Bucket` / `Catalog` / `Oid` / `Cid`）**已退役**：载体、目录与身份都换成上面这一套，
> 旧格式的库不予读取（`Vault.open` 会显式拒绝）。
"""

from __future__ import annotations

from core.types import BucketExistsError, BucketNotFoundError

from .block import (
    INDEX_TYPE,
    PART_TYPE,
    Block,
    Body,
    BodyField,
    canonical,
    decode_canonical,
)
from .blocks import BlockStore
from .carrier import CARRIER_HEADER_BYTES, CARRIER_MAGIC, CarrierLayout
from .engine import Storage
from .index import INDEX_NAME, Difference, Index, RebuildPlan
from .io import CarrierFile
from .record import Record, RecordHeader
from .table import Table, create_table
from .tables import Column, ColumnType, Owned, RebuildTier, declared_tables
from .vault import (
    DEFAULT_BUCKET,
    PACKS_DIR,
    Bucket,
    BucketRole,
    BucketState,
    Finding,
    FindingKind,
    PatrolReport,
    Placement,
    Vault,
)

__all__ = [
    "CARRIER_HEADER_BYTES",
    "CARRIER_MAGIC",
    "DEFAULT_BUCKET",
    "INDEX_NAME",
    "INDEX_TYPE",
    "PACKS_DIR",
    "PART_TYPE",
    "Block",
    "BlockStore",
    "Body",
    "BodyField",
    "Bucket",
    "BucketExistsError",
    "BucketNotFoundError",
    "BucketRole",
    "BucketState",
    "CarrierFile",
    "CarrierLayout",
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
    "create_table",
    "declared_tables",
    "decode_canonical",
]

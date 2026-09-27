# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""类型层：**内核的地基**（基础数据结构 + 声明 + 机制件）。

作者口述（2026-09-22）：原 `tool/` 与 `types/` 两个目录功能重复，**合并到 `types/`**——
因为这里**大部分是类型声明**，少部分是工具型函数，都放这也合理；反过来全叫"工具"才不合理。

成员：

| 模块 | 内容 | 性质 |
|---|---|---|
| `errors` | 异常体系（含存储侧） | 基础 |
| `id` | `Id`（身份证）与两套凭证 `ValueUuid` / `ValueHash`、`SlotRange` | 基础 |
| `kind` | 类型词表与最小类型表（`TypeInfo` / `type_name` / `register`） | 声明 |
| `objects` | 中立视图（`ObjectInfo` / `VerifyReport`） | 结构 |
| `common` | 通用小函数（`now_ms`） | 工具 |
| `attr` | `Attr` / `Data`：**字段的高级标注** | 声明 |
| `cfg` | `Cfg`：**配置项的高级标注**（与 `Attr` 同族，另有取值面） | 声明 |
| `event` | `Event` / `Action` / `Slot` / `Intent`：**事件数据结构** | 结构 |

> 本包**不做 eager 导入**：`attr` 要在存储层导入期被使用（`Block` 子类在类体里声明字段），
> 任何 eager 链都会把上层拖进来形成环。请从具体模块导入，例如 ``from core.types.attr import Attr``。
"""

from __future__ import annotations

from .common import now_ms
from .errors import (
    BucketExistsError,
    BucketNotFoundError,
    CairnError,
    CorruptObjectError,
    IndexSchemaError,
    InvalidIdError,
    KindMismatchError,
    ObjectNotFoundError,
    RecordFormatError,
    SlotError,
    StorageError,
)
from .id import Id, SlotRange, ValueHash, ValueUuid
from .kind import (
    ROLE_DATA,
    ROLE_DOMAIN,
    TypeInfo,
    collect_fields,
    domain_of,
    register,
    type_info,
    type_name,
    types,
    unit_infos,
    unit_names,
)
from .objects import ObjectInfo, VerifyReport

__all__ = [
    "ROLE_DATA",
    "ROLE_DOMAIN",
    "BucketExistsError",
    "BucketNotFoundError",
    "CairnError",
    "CorruptObjectError",
    "Id",
    "IndexSchemaError",
    "InvalidIdError",
    "KindMismatchError",
    "ObjectInfo",
    "ObjectNotFoundError",
    "RecordFormatError",
    "SlotError",
    "SlotRange",
    "StorageError",
    "TypeInfo",
    "ValueHash",
    "ValueUuid",
    "VerifyReport",
    "collect_fields",
    "domain_of",
    "now_ms",
    "register",
    "type_info",
    "type_name",
    "types",
    "unit_infos",
    "unit_names",
]

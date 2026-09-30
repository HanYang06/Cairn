# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""配置词表：声明投影成的 JSON Schema（给 IDE 与分发看的第二份产物）。

词表是**产物**，不是事实源：它由声明现算，落在 `config/schema/settings.json`，
`$id` / `$schema` 两个头由本模块统一给。值文件顶部那句话（`$schema`）指向的就是它。

两条形状约定：

- **键逐字保留点分形式**（`"storage.pack.slot_bytes"` 是一个属性名，不展开成嵌套对象）：
  `conf("…")` 里那个字符串是全仓唯一的检索词，代码与文件里逐字一致，`grep` 才扫得干净；
- **`additionalProperties` 不设 `false`**：值文件是可以手改的产物，用户自己加的键要被允许
  （引擎只补缺失的键、不删不改别人的东西）。故词表用于悬停提示与总览，不当"键名权威"用。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.conf.types import CONFIG_TYPES, MISSING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from core.conf.registry import Declared

#: 词表的固定两头（与 JSON Schema 2020-12 对齐）
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID = "https://github.com/HanYang06/cairn/config/schema/settings.json"

#: 总词表的说明（进 `description`，改口径改这里）
SCHEMA_DOC = (
    "由声明自动生成，勿手改：改配置请改声明的那个 conf(...) 调用点，改值请改 config/settings.json。"
)


def build(items: Iterable[Declared]) -> dict[str, Any]:
    """由声明算出整份词表：键 → 类型 / 说明 / 默认值 / 出处。

    参数：

    - `items`：声明登记项（键、规范化类型、默认值、说明、出处），来自引擎的登记表。

    **类型不给的键只写 `description`**：那种键的值本身就是数据（如一份表声明文件），
    给它编一个类型反而误导。多处声明的同键由引擎先行拦下，故这里的后写覆盖只作兜底。
    """
    properties: dict[str, Any] = {}
    for declared in items:
        spec = declared.item.spec
        entry: dict[str, Any] = {}
        type_name = CONFIG_TYPES.get(spec.scalar)
        if type_name is not None:
            entry["type"] = type_name
        entry["description"] = declared.item.doc
        if declared.item.default is not MISSING:
            entry["default"] = declared.item.default
        entry["x-cairn-owner"] = (
            f"{declared.module}.{declared.qualname}" if declared.qualname else declared.module
        )
        entry["x-cairn-site"] = f"{declared.site.file}:{declared.site.line}"
        properties[declared.path] = entry
    return {
        "$schema": SCHEMA_DIALECT,
        "$id": SCHEMA_ID,
        "title": "Cairn 配置（总词表）",
        "description": SCHEMA_DOC,
        "type": "object",
        "properties": properties,
    }

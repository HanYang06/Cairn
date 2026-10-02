# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""反表：按值查回块。

- `attrindex.py`：属性（`Attr` 声明的字段）到块的倒排；
- `bodyindex.py`：正文摘要到块的倒排，写入去重的命中也依它。

**两者本身也是块**——它们有 ID、落进自己的身份表，与任何块同路，没有第二套机制。
它们同时是**增强件**：缺位即退化为全库扫，数据不丢，只是慢。
"""

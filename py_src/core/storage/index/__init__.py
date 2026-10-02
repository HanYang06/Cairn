# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""反表：按值查回块。

- `attrindex.py`：块属性（`Attr` 声明的字段）的倒排；
- `bodyindex.py`：内容凭证（摘要）到块的倒排。

**这两者本身也是块**——它们有 ID、落进自己的身份表，与任何块同路，没有第二套机制。
它们同时是**范例代码**：一个能跑的块该长什么样，看它们即可。
"""

# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""数据库引擎：索引库与身份。

- `engine.py`：库本身——一个类型一张**身份表**（列全部由 `ID_FIELDS` 现算）、`hub` 登记、`meta`；
- `id.py`：`ID` 的字段与落盘口径（库里的行是它的镜像）；
- `payload.py`：块记录与内容记录的载荷编解码（保留键住在这里）。

它是**存储引擎的子引擎**：存储引擎面向载体，本包面向索引库，两者只经"身份"接头。
"""

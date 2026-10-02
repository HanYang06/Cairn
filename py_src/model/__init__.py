# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""领域层：只依赖 `core` 的公共面，内部分**域**与**共享件**。

方向只有一条：`model` → `core`，`core` 永不反向认识它（`pyproject.toml` 的
import-linter 契约拦着）。故内核按身份读写字节，不知道那些字节是哪个领域概念——
"这是哪种块"由调用方递进来的类说了算。

**现状**：只有 `note` 一个域，且只落到数据结构这一层（见 `note/__init__.py` 的三层说明）。
`shared/`（跨域共享件）**待落**——判据照旧：第二个调用方出现才抽，不预先占位。
"""

# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""hub：一个目录，装若干载体（旧称"桶"，2026-09-29 起统一叫 hub）。

- 判据是**形状**而不是"是个目录"：`vault/` 下带 `packs/` 的直接子目录才算 hub；
  库里还会有别的东西，见目录就当 hub 会把它们卷进来；
- hub 名就是它的地址（目录名），进 ID 的 `in_hub`；索引库里它是一列；
- hub 不持有 ID：ID 是载荷的身份证，hub 是容器，它的标识就是它的名字；
- hub 目录本身即 hub 的存在证明，索引库里的登记是**登记**而非真源。

尚未落地。
"""

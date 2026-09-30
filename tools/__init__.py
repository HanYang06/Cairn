# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""开发工具（门禁 / 生成器 / 检查器），**不参与产品运行期**。

做成正规包（而非命名空间包）有两个理由：

1. `mypy src tools tests` 与 pytest 都要能从仓根 import `tools.<模块>`，正规包最稳；
2. 测试用 `sys.executable` 起子进程跑这些工具时，导入路径同样要成立。
"""

from __future__ import annotations

# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0

"""工具:**可被 Python 内部 import 调用**的模块,与"脚本"分开.

判据只有一条——**能不能被 import**:

- `tools/`(本目录):正规包,可 `from tools.<模块> import …`.装的是产品与开发流程
  **用得着的可调用件**(mypy 插件,原子写与输出助手等);
- `scripts/`:门禁,生成器,打包等"跑完就算"的入口.那里**不放 `__init__.py`**,
  用来声明"这不是一个包";但**只靠这一点拦不住**——Python 3 的命名空间包(PEP 420)
  照样能 `import scripts.xxx`.真正的拦截是 import-linter 契约
  (`pyproject.toml` 的 `[tool.importlinter]`):**`core` 与 `tools` 不许依赖 `scripts`**.

做成正规包(而非命名空间包)另有两个理由:

1. `mypy py_src tools scripts tests` 与 pytest 都要能从仓根 import `tools.<模块>`,正规包最稳;
2. 测试用 `sys.executable` 起子进程跑脚本时,脚本里的 `from tools._iosafe import …`
   同样要成立(脚本会先把仓根塞进 `sys.path`).
"""

from __future__ import annotations

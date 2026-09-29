<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 质量标准（企业级-ε）

本仓库的质量口径：严格度在「草台班子」与「金融级」之间，约等于**企业级再降半档**。
`pyproject.toml` 是配置的**唯一事实来源**；本文件只写口径、豁免理由与升级路径。

## 四个维度

### 1. 注释：有要求

- 公共**模块 / 类 / 函数**必须有 docstring（pydocstyle，google 约定）。
- 不强制每个方法 / 魔法方法 / `__init__`（豁免 `D102` / `D105` / `D107`）。
- 中文 docstring 以「。」结尾，`D415` 不认全角句号 → 豁免 `D415`。
- 测试、工具脚本、实验包（`tests/` `tools/` `src/net/` `src/server/`）整体豁免 `D` 系。

### 2. 代码风格：有规范

- `ruff check`：`select = ["ALL"]`，再用一份**逐条写明理由**的 `ignore` 收口。
- `ruff format` 强制：提交前与 CI 都检查（`ruff format --check`）。
- 复杂度 / 裸 `except` / magic value / 导入分层等默认开启。
- vendored 第三方技能（`.agents/`）排除，保持上游原样。

### 3. 类型：按静态语言口径

- `mypy strict = true`，覆盖 `src`、`tools` 与 `tests`（门禁命令 `uv run mypy src tools tests`）。
- `mypy_path = "src"` 指明源码根：不指路时 mypy 把 `core` 当成缺 `py.typed` 的已装包，
  测试侧的 `core.*` 全成 `Any`，报错数仍在、判据已失效。
- 未注解、隐式 `Any`、`Any` 返回值、缺泛型参数一律报错。
- **测试只豁免签名**（`tests.*` 关 `disallow_untyped_defs` / `disallow_incomplete_defs`）：
  函数体仍在 `check_untyped_defs` 下受检，对 `core.*` 的调用判据一条不少；
  口径与 ruff 对 `tests/**` 豁免 `ANN` 一致。
- `Attr[T] = 值` 这类字段由 `tools/mypy_plugin.py` 还原可见类型，**不靠 ignore**。
- 例外：`id` / `type` / `hash` 是本项目的**领域词汇**，豁免 `A002` / `A003`。

### 4. 其他：按企业级

- **测试**：`pytest --strict-markers --strict-config`；`filterwarnings = ["error"]`（warning 零容忍）。
- **覆盖率**：行 + 分支 ≥ 80%（CI 门禁 `--cov-fail-under=80`）。
- **提交前**（pre-commit）：`ruff check --fix` → `ruff format` → `mypy`。
- **CI**（`.github/workflows/ci.yml`）：ruff → format → mypy → pytest + 覆盖率门禁。

## 全局豁免清单（每条都有理由）

见 `pyproject.toml` 的 `[tool.ruff.lint] ignore` 内注释，摘要：

| 规则 | 理由 |
|---|---|
| `D203` `D213` `COM812` `ISC001` | 与 `ruff format` 冲突，交给格式化器 |
| `RUF001` `RUF002` `RUF003` | 中文全角标点误报 |
| `D415` | 中文 docstring 以「。」结尾，规则不认 |
| `D102` `D105` `D107` | 不强制方法 / dunder docstring |
| `ANN401` | 边界处允许显式 `Any`（未注解由 mypy 把关） |
| `TID252` | 项目内部允许相对导入 |
| `EM101` `EM102` `TRY003` | 异常消息允许字面量 / f-string |
| `PLR2004` | 可读性阈值判断不算魔法数 |
| `A002` `A003` | 领域词汇 `id` / `type` / `hash` |

按文件豁免（`per-file-ignores`）：Qt 边界 `backend.py`、测试 / 工具 / 实验包、`table.py` 的 `S608`。

## 升级到「全企业级」

- 打开 `D103`（公共函数）与 `D102`（方法）的 docstring 要求。
- 覆盖率阈值提到 90%+。
- 引入 `bandit` / `pip-audit` 作为强制门禁（现未启用）。

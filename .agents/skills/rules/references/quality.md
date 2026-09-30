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
- 测试、工具脚本整体豁免 `D` 系（`tests/` `tools/`）。

### 2. 代码风格：有规范

- `ruff check`：`select = ["ALL"]`，再用一份**逐条写明理由**的 `ignore` 收口。
- `ruff format` 强制：提交前与 CI 都检查（`ruff format --check`）。
- 复杂度 / 裸 `except` / magic value / 导入分层等默认开启。
- vendored 第三方技能（`.agents/`）排除，保持上游原样。

### 3. 类型：按静态语言口径

- `mypy strict = true`，覆盖 `py_src`、`tools`、`scripts` 与 `tests`
  （门禁命令 `uv run mypy py_src tools scripts tests`）。
- `mypy_path = "py_src"` 指明源码根：不指路时 mypy 把 `core` 当成缺 `py.typed` 的已装包，
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
- **提交前**（`.pre-commit-config.yaml`，共 10 个钩子；**须先 `uv run pre-commit install
  --hook-type pre-commit --hook-type commit-msg`**，否则一个都不跑）：
  SPDX → 书面语 → 标点（报告模式）→ `ruff check --fix` → `ruff format` → `deptry` →
  `lint-imports` → `mypy` → `uv lock --check` → `pytest` → 前端 `pnpm check`；
  提交信息另由 commit-msg 钩子校验 Conventional Commits。
- **CI**（`.github/workflows/ci.yml`，Python 侧十道 + 前端一组 `pnpm check`）：
  SPDX → 书面语 → 标点 → 文档防漂移 → docstring 覆盖（报告）→ ruff → deptry →
  import-linter → `uv lock --check` → mypy → pytest + 覆盖率门禁。
- **架构校验**（`uv run lint-imports`）：契约写在 `pyproject.toml` 的 `[tool.importlinter]`——
  `core` 不许依赖上层（`model` / `feature` / `app` / `net` / `server`）且必须 Qt-free。
  配置放 pyproject 而非 `.importlinter`：后者按系统默认编码读，Windows 下遇中文即失败。
- **依赖盘点**（`uv run deptry .`）：拦"声明了却一处没用"与"用了却没声明"；
  已知的未接线依赖冻结在 `[tool.deptry.per_rule_ignores]`，故新增的才会红。
- **标点**（`uv run python scripts/punct.py`）：**注释与 docstring** 用半角标点（中英混排），
  字符串字面量不动（那是行为不是排版）。当前是**报告模式**：全仓命中约 5300 处，
  看过一轮再改成阻断式。

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

按文件豁免（`per-file-ignores`）：`rows.py` / `index.py` 的 `S608`（SQL 由声明拼、值全参数化），
`conf/registry.py` 的 `PLR0913`（声明与取值共用一个签名），`storage/tables.py` 的 `PLC0415`
（"配置在哪"延后问），以及测试 / 工具脚本的整组豁免。

## 升级到「全企业级」

- 打开 `D103`（公共函数）与 `D102`（方法）的 docstring 要求。
- 覆盖率阈值提到 90%+。
- `pip-audit`（CVE 扫描）作为 CI 门禁：它需要网络，**不放本机钩子**。
  `bandit` 不再单独引入：ruff 的 `S` 规则族已覆盖同一批检查。

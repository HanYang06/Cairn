<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 参与开发

## 环境

```powershell
uv sync                                  # 安装/同步依赖（Python 3.13，走 uv.lock + 阿里云镜像）
```

内核不设库旋钮：库根由调用方显式给出（`Kernel.create(root)` / `Kernel.open(root)`）；
开发库通常放 `<repo>/vault/`（已 gitignore）。配置根有一个旋钮 `CAIRN_CONFIG`，
仅用于测试与部署的路径重定向，不是配置项。桌面壳侧另有 `CAIRN_VAULT` / `CAIRN_PYTHON` /
`CAIRN_PYTHONPATH`（见「[快速开始](quickstart.md)」第 4 节）。

## 常用命令

```powershell
uv run pytest                              # 全部测试（含覆盖率；CI 用 --cov-fail-under=80）
uv run pytest tests/core/test_conf.py -x   # 单个测试
uv run ruff check .                        # lint（--fix 自动修）
uv run ruff format .                       # 格式化（提交前用 --check）
uv run mypy py_src tools scripts tests     # 类型检查（strict）
uv run python scripts/spdx.py --check      # SPDX 头门禁（缺头用 --fix 自动补）
uv run python scripts/prose.py             # 书面语门禁（文档/注释不得口语，词典即标准）
uv run python scripts/punct.py --report    # 标点检查（注释/docstring 的中文标点）
uv run deptry .                            # 依赖盘点（声明了没用 / 用了没声明）
uv run lint-imports                        # 架构校验（契约在 pyproject 的 [tool.importlinter]）
uv lock --check                            # 锁文件是否与声明同步
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
                                           # 先装钩子；不装时配置文件在、门禁不跑
uv run pre-commit run --all-files          # 提交前全量门禁（11 个钩子，清单见 quality.md §4）
pnpm --dir app check                       # 前端门禁（类型/lint/样式/架构/令牌/重复代码/单测）
```

!!! tip "提交前顺序"

    一条命令跑完：`uv run pre-commit run --all-files`；只看 Python 侧时可用
    `ruff → mypy → pytest`。质量口径定义在 `.agents/skills/rules/references/quality.md`，
    配置的**唯一事实来源**是 `pyproject.toml`。

## 文档站

```powershell
uv run mkdocs serve            # 本地预览（热重载）→ http://127.0.0.1:8000
uv run mkdocs build --strict   # 跟 CI 同口径构建（坏链接 / 缺页面 / 未知配置即报错）
```

生成物落在 `site/`，**不入库**。动手改文档前请先读「[怎么改文档](../contributing.md#怎么改文档)」。

## 目录结构

```text
py_src/
  core/        L0 底座：事件 / 存储 / 配置 / 异常（Qt-free、传输无关）
  model/       领域落点（note，重建中）
  app/         Python 侧入口：内核边车（python -m app.sidecar）
app/           Tauri 壳 + Web 前端：app/src/（React/TS）、app/src-tauri/（Rust 壳）
tools/         可 import 的开发件（原子写与输出助手）
scripts/       门禁 / 生成器 / 打包（不放 __init__.py；core 与 tools 不许依赖它）
docs/          手写文档（事实源）
tests/         pytest 用例
config/        配置（值文件与词表，跑一遍即生成）+ 主题令牌
vault/         开发库（gitignore）
```

顶层包一律去 `cairn.` 前缀：`from core.storage import …`。
分层边界与红线见「[约定与红线](conventions.md)」。

## 提交

- commit message 用 **Conventional Commits**（`feat(ui): …` / `fix(core): …`），中文描述。
- pre-commit 会跑 11 个钩子（SPDX → 书面语 → 标点 → ruff → deptry → 架构 → mypy →
  锁文件 → 测试 → 前端），另由 commit-msg 钩子校验 Conventional Commits；
  缺 SPDX 头时钩子自动补，补完要重新 `git add`。**钩子需先装**（见上）。

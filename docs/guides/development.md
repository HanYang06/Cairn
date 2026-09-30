<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 参与开发

## 环境

```powershell
uv sync                                  # 安装/同步依赖（Python 3.13，走 uv.lock + 阿里云镜像）
```

开发库默认 `<repo>/vault/`（已 gitignore），可用 `CAIRN_VAULT` 覆盖；
`CAIRN_DEV_PASSPHRASE`（默认 `cairn-dev`）是 P2P / 服务端到来前的占位。

## 常用命令

```powershell
uv run pytest                              # 全部测试（含覆盖率；CI 用 --cov-fail-under=80）
uv run pytest tests/core/test_conf.py -x   # 单个测试
uv run ruff check .                        # lint（--fix 自动修）
uv run ruff format .                       # 格式化（提交前用 --check）
uv run mypy py_src tools scripts tests      # 类型检查（strict）
uv run python scripts/spdx.py --check      # SPDX 头门禁（缺头用 --fix 自动补）
uv run deptry .                            # 依赖盘点（声明了没用 / 用了没声明）
uv run lint-imports                        # 架构校验（契约在 pyproject 的 [tool.importlinter]）
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
                                           # 先装钩子；不装时配置文件在、门禁不跑
uv run pre-commit run --all-files          # 提交前全量门禁（11 个钩子，清单见 quality.md §4）
```

!!! tip "提交前顺序"

    一条命令跑完：`uv run pre-commit run --all-files`；只看 Python 侧时可用
    `ruff → mypy → pytest`。质量口径定义在 `rules/references/quality.md`，
    配置的**唯一事实来源**是 `pyproject.toml`。

## 文档站

```powershell
uv run mkdocs serve            # 本地预览（热重载）→ http://127.0.0.1:8000
uv run mkdocs build --strict   # 跟 CI 同口径构建（坏链接 / 缺页面 / 未知配置即报错）
```

生成物落在 `site/`，**不入库**。动手改文档前请先读「[怎么改文档](../contributing/docs.md)」。

## 目录结构

```text
src/
  core/        L0 底座：存储 / 事件 / 配置 / 异常（**Qt-free、传输无关**）
  feature/     领域：note / project 域 + shared/ 共享件
  ui_tools/    界面工具箱：声明树 / 编译 / 绑定 / 模型 / 主题
  app/         应用组合根，按平台（win / linux）；**只有它认识领域**
tools/         开发工具（spdx / 书面语 / docgen / mypy 插件 / 构建 / 预览）
docs/          手写文档（事实源）
tests/         pytest 用例
config/        配置（值文件与词表，**跑一遍即生成**）+ 主题与图形集
vault/         开发库（gitignore）
```

顶层包一律去 `cairn.` 前缀：`from core.storage import …`。
分层边界与红线见「[约定与红线](conventions.md)」。

## 提交

- commit message 用 **Conventional Commits**（`feat(ui): …` / `fix(core): …`），中文描述。
- **只有用户明确要求才 commit**（本项目约定）。
- pre-commit 会跑 11 个钩子（SPDX → 书面语 → 标点 → ruff → deptry → 架构 → mypy →
  锁文件 → 测试 → 前端），另由 commit-msg 钩子校验 Conventional Commits；
  缺 SPDX 头时钩子自动补，补完要重新 `git add`。**钩子需先装**（见上）。

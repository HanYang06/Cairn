<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# AGENTS.md

Cairn（巨石堆）：本地优先的内容寻址对象池 / 笔记·资产·项目工作台。Python 3.13；内核 Qt-free；UI = `src/ui_tools/`（工具箱）+ `src/app/win/`（外壳），其余界面待重建；用 `uv` 管理；Apache-2.0。

## 开工前 SOP（每个任务都先做）

1. **先看规则**：判断当前任务命中哪条规则，只读相关的那条；没有命中的规则就跳过。
2. **再看记忆**：读与本次任务相关的项目记忆（变更 / 决策 / 进度 / TODO），摸清现状。
3. **再动手**。

细则都在 `.agents/skills/`；本文件只做**索引与红线**，不要把长规则堆在这里。

## 常用命令

```powershell
uv sync                                   # 安装/同步依赖

uv run pytest                             # 全部测试（含覆盖率；CI 用 --cov-fail-under=80）
uv run pytest tests/core/test_vault.py::test_put_open_roundtrip   # 单个测试
uv run ruff check .                       # lint（--fix 自动修）
uv run ruff format .                      # 格式化（提交前用 --check）
uv run mypy src tools                     # 类型检查（strict）
uv run python tools/spdx.py --check       # SPDX 头门禁（缺头用 --fix 自动补）
uv run python tools/prose.py              # 书面语门禁（文档/注释不得口语，词典即标准）
uv run pre-commit run --all-files         # 提交前全量门禁（SPDX -> 书面语 -> ruff -> mypy）

uv run mkdocs serve                       # 文档站本地预览 -> http://127.0.0.1:8000
uv run mkdocs build --strict              # 文档站构建门禁（坏链接/缺页面/未知配置即失败）
uv run python tools/docgen.py --check     # 生成页防漂移（配置参考 vs schema 词表）
uv run python tools/docgen.py --write     # 重新生成配置参考页（改了配置声明后跑）
uv run python tools/docgen.py --coverage  # docstring 覆盖报告（没写的公共成员会从 API 页消失）
```

> 桌面入口 `uv run cairn` 与打包在 UI 重建后恢复。

提交前顺序：`ruff -> mypy -> pytest`。质量口径见 `.agents/skills/rules/references/quality.md`
（企业级-ε：mypy strict、ruff ALL、warning 零容忍、覆盖率 ≥80%）。**只有用户明确要求才 commit。**

## 硬性约定

- 每个源文件/文档顶部必须有 SPDX 头：`SPDX-FileCopyrightText: 2026 HanYang06`
  + `SPDX-License-Identifier: Apache-2.0`（`.py` 用 `#`，`.md` 用 `<!-- -->`）。
  **不得手写**：pre-commit 自动补、`tools/spdx.py` 校验；装不下头的（图片 / JSON / 锁文件 /
  vendored）走 `REUSE.toml` 集中声明。细则见 `rules/references/spdx.md`。
- Apache-2.0 项目：**禁止引入 GPL/AGPL 依赖**（传染红线）；第三方主题/画布库先核实许可。
- 文档、注释、commit message 用中文；commit 用 Conventional Commits（`feat(ui): …`、`fix(core): …`）。
- 不写 C++。Rust（PyO3 + maturin）仅在性能热点被证实后启用。
- 未实现的设计标为「预留/草案」，不要假装已存在。
- **文档分两类，别混**：手写事实源在 `docs/**/*.md`（跟代码一起评审）；
  `docs/api/` 下的 API 参考与 `site/` 站点由 `mkdocs` + `mkdocstrings` 从 docstring **自动生成**，
  **不手改**。新增页面要登记进 `mkdocs.yml` 的 `nav`。细则见 `rules/references/docs.md`。

## 架构分层（别越界）

- 顶层包在 `src/` 下、**一律去 `cairn.` 前缀**（`from core.storage import …`）：
  `core` / `feature` / `ui_tools` / `app`（`net` / `server` 已删，待重设）。
- `src/core/`（L0 存储底座）是公共底座：**必须 Qt-free、传输无关**；
  存储原语在 `core/storage/`（块 / 载体 / 桶 / 多桶 / 索引库），基础类型在 `core/types/`。
- `src/feature/`（L3）只依赖 core 公共 API，内部先分两支：**域**（`note` / `project`，`Domain` 子类，
  管理型、单例、无 ID）与 **共享件**（`shared/`：数据结构 canvas / asset / group、值 signature、
  设施 relation / provenance / base / kinds）。领域之间互不依赖；领域结构**直接继承 `Block`**，
  不得改 `Block` 顶层字段，扩展只走子类字段（`Attr` / `Data` / `Body`）、新 `type` 或新关系 `kind`。
- **类型词表 `feature.shared.Kind`**：`Kind.Feature`（域）/ `Kind.Data`（块类型），
  plain `Enum`、值即落盘字符串（如 `notedata`），不用 `cairn.<domain>.<kind>` 旧命名空间；
  第三方类型用自有前缀字符串。类型表按值归一（`core.types.type_name`）。
- `src/app/` 是界面载体（按平台 `win` / `linux`）+ `ui_tools/` 界面工具层；
  `core/conf/` 放配置与常量。
- `src/net/`、`src/server/` 曾为 P2P / 服务端**实验顶层包**，**当前已删除、待重设**
  （`tests/net/` 与 ruff 的 per-file-ignores 里还有残引用）。新内核代码放 `src/core` 或 `src/feature`。
- `docs/architecture/*.md` 是设计事实来源（`storage-design.md` 为 L0 存储的唯一事实来源，
  `data-model.md` 为数据结构总纲）。**有冲突以代码为准，改实现后回写文档。**
- 内部时间统一 unix 毫秒 int；对象身份是 `ValueUuid`（26 字符 Crockford ULID），
  内容哈希是 `ValueHash`（BLAKE3 十六进制）——两套凭证都在 `core/types/id.py` 的 `Id` 上。

## 测试

- pytest：`testpaths=["tests"]`、`pythonpath=["src"]`，无需安装即可 `import core`。
- 测试无外部服务/数据库，全部用临时本地库。

## 环境与坑

- 开发库默认 `<repo>/vault/`（已 gitignore），可用 `CAIRN_VAULT` 覆盖；
  口令 `CAIRN_DEV_PASSPHRASE`（默认 `cairn-dev`）。
- Python 3.13；`uv.lock` + 阿里云 PyPI 镜像（`pyproject.toml` 的 `[[tool.uv.index]]`）。
- 图片走 Git LFS（`.gitattributes`）；未装 LFS 时 clone 到的 png 只是指针。

## 规则 / 记忆 / Skills（`.agents/skills/`）

- 技能统一放 `.agents/skills/<name>/SKILL.md`（跨工具目录：opencode、Codex、
  GitHub Copilot、Zed 等均读；opencode 全局版才用 `~/.config/opencode/skills/`）。
- 用 CLI 管理（skills.sh）：`npx skills add <owner/repo> --skill <name> -a opencode --copy -y`
  / `npx skills find <词>` / `npx skills update`。第三方技能保持上游原样，
  来源记在 `skills-lock.json`。
- 索引分工：
  - `rules` —— **规则总入口**，按场景分发到自己的 `references/`。规则只写这里。
  - `memory` —— **项目记忆本体**（可变、活文件）：变更 / 决策 / 进度 / TODO。
  - `git-commit` —— 提交规范（Conventional Commits）；来自 `github/awesome-copilot`（MIT）。
  - `skill-creator` —— 写 / 改 skill；来自 `anthropics/skills`（Apache-2.0）。
- 现状：`rules`、`memory` 为自建骨架（备注待补）；`git-commit`、`skill-creator` 为第三方安装。
- **改完 skill 必须重启 opencode 才生效。**

### 记忆的清理机制（硬性）

- `memory` 会过期失真：每条记忆标注**日期 + 状态**（进行中 / 已定 / 已废弃）。
- 每次任务收尾一并清理：**过期、已废弃、与代码或文档不符**的记忆要删除或改写——
  只增不减会腐化失真。
- 冲突时以代码与 `docs/architecture/*.md` 为准，记忆服从事实。

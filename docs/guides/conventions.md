<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 约定与红线

> 本文是 `AGENTS.md` 红线的展开版，按场景重排。规则全文与理由见
> `.agents/skills/rules/references/`；本文只做导航与要点，冲突时以那边为准。

## 1. 许可

- 本项目为 **Apache-2.0**，**禁止引入 GPL / AGPL 依赖**（传染性条款会将本项目转为 GPL）。
- **允许引入**宽松许可：MIT / ISC / BSD / Apache-2.0——可商用、可闭源分发。
  本站所用 `mkdocs-material`（MIT）与 `mkdocstrings-python`（ISC）属这一档。
- **禁止商用类许可**（CC-BY-NC、PolyForm NC 等）与本项目的商用目标冲突，不引入。
- 第三方主题 / 画布 / 编辑器库**先核实许可再采用**；新增第三方 skill 保持上游原样，
  来源与 hash 记入 `skills-lock.json`，必要时同步 `NOTICE`。
  完整政策与工具清单见「[许可与署名](../contributing.md#依赖许可政策)」。

## 2. SPDX 头

每个源文件 / 文档顶部必须有：

```
SPDX-FileCopyrightText: 2026 HanYang06
SPDX-License-Identifier: Apache-2.0
```

`.py` 用 `#`、`.md` 用 `<!-- -->`、`.iss` 用 `;`；`SKILL.md` 的头紧随 YAML frontmatter 之后。

| 层 | 手段 |
|---|---|
| **写** | `uv run python scripts/spdx.py --fix`（pre-commit 钩子已挂，会自动补） |
| **查** | `uv run python scripts/spdx.py --check`（缺头 / 年份错 / `SKILL.md` 少 `license:` 即非零退出） |
| **兜底** | 根 `REUSE.toml` 集中声明装不下头的文件（图片 / JSON / 锁文件 / 法律文书 / vendored） |

- **不手抄**：新文件由钩子补头。钩子补完会非零退出（它把「改动了文件」也视为失败），
  重新 `git add` 再提交即可。
- **新增文件类型时**：能写注释的加进 `scripts/spdx.py` 的 `_COMMENT_STYLES`
  （无扩展名的按 `_NAMED_STYLES` 认领）；装不下头的加进 `REUSE.toml`。
  两者都不适用时 `--check` 会报「未归类」。
- **不引入 `reuse` CLI**：`fsfe/reuse-tool` 为 GPL-3.0-or-later，违反本项目许可红线；
  只采用其定义的 `REUSE.toml` **数据格式**，读写由 `scripts/spdx.py` 实现。

## 3. 分层边界

```text
Python 侧（py_src/）：
  core(L0)  ←  feature(L3)  ←  app(组合根)        —— 当前只有 core 在位

界面侧（app/）：
  Tauri 壳(Rust)  ←  Web 前端(atoms → composites → pages)
```

- `py_src/core/`（内核：事件 / 存储 / 配置 / 异常）**必须 Qt-free、传输无关**。
- `py_src/feature/`（**待重建**）只依赖 core 的公共 API；**域之间互不依赖**，跨域协作归 app。
- 界面侧**不 import 领域、不碰 `core.storage`**，只经命令面过边界；Tauri 壳**不写业务**。
  界面侧细则见 `.agents/skills/rules/references/ui-boundary.md`。
- **只有组合根认识领域**：建域服务并注入，不在界面内实例化领域对象。
- 领域结构**直接继承 `Block`**，不得改 `Block` 顶层字段；扩展只走子类字段、新 `type`、新关系 `kind`。

判据：**新开发者理解界面无需先掌握 hub / Block；不满足即视为越界。**

## 4. 数据约定

- 内部时间统一 **unix 毫秒**（`core/clock.py` 的 `now_ms`）；ID 的 `birth_time` 用纳秒。
- 对象身份是 `py_src/core/storage/db/id.py` 的 **`ID`**（身份属于数据库那一侧——它是索引的来路）：
  字段为 `name`（由持有者推出，表名取自它）、`value_uuid`、`birth_time` 与位置段；
  **`value_hash` 已按 2026-10-02 裁定移出身份**——去重只针对 `Body` 的内容，
  走正文索引块。库里的列 = `ID_FIELDS` ＋ **正文摘要那一列**（`body`），恰好七列。
- **字段落点声明在类体上**（`core/storage/types.py` 的 `Attr` / `Body`）：用了 `Attr` 就进反表、
  用了 `Body` 就进**正文槽**，**没有 `indexed=` 一类开关**；裸赋值照样落盘。
- **表名只由类名算出**（`type(self).__name__.lower()`）：没有 `__table__` 覆盖、没有表结构声明文件，
  库里的表由"这个类型用没用 ID"决定。
- **未实现的设计标为「预留 / 草案」**；文档不得把未实现的内容写成已实现。

## 5. 质量门禁（企业级-ε）

- `mypy strict`（覆盖 `py_src` + `tools` + `scripts` + `tests`）、`ruff select=ALL`
  ＋逐条有理由的 ignore、`ruff format` 强制。
- **warning 零容忍**（pytest `filterwarnings = ["error"]`）；覆盖率行 + 分支 **≥ 80%**。
- **提交前一条命令跑完**：`uv run pre-commit run --all-files`（13 个钩子，清单与判据见
  `.agents/skills/rules/references/quality.md` §4）。钩子需先安装一次：
  `uv run pre-commit install --hook-type pre-commit --hook-type commit-msg`；
  未安装时配置文件存在但门禁不执行。

## 6. 文档与提交

- 文档、注释、commit message 用**中文**；commit 用 Conventional Commits（`feat(ui): …`）。
- **权威顺序 `路线图 > 设计 > 代码`**（路线图管「要什么」、代码管「现在是什么」）；
  改了实现就回写 `docs/architecture/*.md`，不得留下与代码不符的文档。

<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 约定与红线

> 本文是 `AGENTS.md` 红线的**展开版**，按场景重排。规则全文与理由见
> `.agents/skills/rules/references/`；本文只做导航与要点，冲突时以那边为准。

## 1. 许可（最硬的一条）

- 本项目 **Apache-2.0**：**禁止引入 GPL / AGPL 依赖**（传染性）。宁可少一个功能也别踩。
- 允许并鼓励的是**宽松许可**：MIT / ISC / BSD / Apache-2.0 —— 随便用、可商用、可闭源分发。
  本站用的 `mkdocs-material`（MIT）与 `mkdocstrings-python`（ISC）就属这一档。
- 真正要躲开的是**禁止商用**类许可（CC-BY-NC、PolyForm NC 等），那才叫"商业上不好搞"。
- 第三方主题 / 画布 / 编辑器库**先核实许可再采用**；新增第三方 skill 保持上游原样，
  来源与 hash 记入 `skills-lock.json`，必要时同步 `NOTICE`。

## 2. SPDX 头：不靠手抄

每个源文件 / 文档顶部必须有：

```
SPDX-FileCopyrightText: 2026 HanYang06
SPDX-License-Identifier: Apache-2.0
```

`.py` 用 `#`、`.md` 用 `<!-- -->`、`.iss` 用 `;`；`SKILL.md` 的头紧随 YAML frontmatter 之后。

| 层 | 手段 |
|---|---|
| **写** | `uv run python tools/spdx.py --fix`（pre-commit 钩子已挂，会自动补） |
| **查** | `uv run python tools/spdx.py --check`（缺头 / 年份错 / `SKILL.md` 少 `license:` 即非零退出） |
| **兜底** | 根 `REUSE.toml` 集中声明装不下头的文件（图片 / JSON / 锁文件 / 法律文书 / vendored） |

- **不手抄**：新文件让钩子补。钩子补完会**非零退出**（它把"改动了文件"也当失败），
  重新 `git add` 再提交即可。
- **新增文件类型时**：能写注释 → 加进 `tools/spdx.py` 的 `_COMMENT_STYLES`
  （无扩展名的按 `_NAMED_STYLES` 认领）；装不下 → 加进 `REUSE.toml`。两条都不走，`--check` 会报"未归类"。
- **不引入 `reuse` CLI**：`fsfe/reuse-tool` 是 GPL-3.0-or-later，撞红线；
  我们只采用它定义的 `REUSE.toml` **数据格式**，读写由 `tools/spdx.py` 自己实现。

## 3. 分层边界（别越界）

```text
core(L0)  ←  feature(L3)  ←  app(组合根)
                     ↑
                ui_tools(工具箱) —— 谁都能用，但不认识领域
```

- `src/core/`（内核：事件 / 存储 / 异常）**必须 Qt-free、传输无关**。
- `src/feature/`（**待重建**）只依赖 core 的公共 API；**域之间互不依赖**，跨域协作归 App。
- `ui_tools`（**待重建**）**不 import `feature` / `core.storage`**。UI 里出现
  `hub` / `block` / `body` / `checksum` 即失控。
- **只有组合根认识领域**：建域服务并注入，不在 UI 内 new 领域对象。
- 领域结构**直接继承 `Block`**，不得改 `Block` 顶层字段；扩展只走子类字段、新 `type`、新关系 `kind`。

判据：**「新开发者要懂 UI 须先学 hub/Block」即失败。**

## 4. 数据约定

- 内部时间统一 **unix 毫秒**（`core/clock.py` 的 `now_ms`）；ID 的 `birth_time` 用纳秒。
- 对象身份是 `core/storage/format/id.py` 的 **`ID`**：两套凭证并存——
  `value_uuid`（`uuid4()`，比较有效）与 `value_hash`（`sha256` 十六进制，去重有效）。
- 类型名由**程序**给出（`kind`），落盘不写类型标号；不认识的 ID 一律降级读回。
- **未实现的设计标为「预留 / 草案」**，不要假装已存在；也别写"已实现"骗下一个读代码的人。

## 5. 质量门禁（企业级-ε）

- `mypy strict`（覆盖 `src` + `tools`）、`ruff select=ALL` + 逐条有理由的 ignore、`ruff format` 强制。
- **warning 零容忍**（pytest `filterwarnings = ["error"]`）；覆盖率行 + 分支 **≥ 80%**。
- 提交前：`ruff → mypy → pytest`；pre-commit：SPDX → ruff → mypy。

## 6. 文档与提交

- 文档、注释、commit message 用**中文**；commit 用 Conventional Commits（`feat(ui): …`）。
- **代码是唯一事实**；改了实现就回写 `docs/architecture/*.md`，不得留下与代码不符的文档。
- **只有用户明确要求才 commit。**

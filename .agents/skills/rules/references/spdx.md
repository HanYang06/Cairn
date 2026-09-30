<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# SPDX 头规则

## 规则本体

- 每个源文件 / 文档顶部必须有：
  - `SPDX-FileCopyrightText: 2026 HanYang06`
  - `SPDX-License-Identifier: Apache-2.0`
- 写法：`.py` 用 `#`，`.md` 用 `<!-- -->`，`.iss` 用 `;`（Inno Setup 的注释是分号）。
- `SKILL.md` 例外：YAML frontmatter 必须在最顶部，故 SPDX 注释紧随 frontmatter 之后，
  并同时在 frontmatter 写 `license: Apache-2.0`。
- 第三方 vendored 文件（`.agents/skills/skill-creator/`、`.agents/skills/git-commit/`）
  保持上游原样，不强行加 SPDX；它们的许可在 `REUSE.toml` 里声明。

## 不得手写：三层机制

| 层 | 手段 | 说明 |
|---|---|---|
| **写** | `scripts/spdx.py --fix` | 新文件**不得手写头**：pre-commit 自动插入（插完重新 `git add`） |
| **查** | `scripts/spdx.py --check` | 门禁：缺头 / 年份不对 / `SKILL.md` 缺 `license:` 都非零退出 |
| **兜底** | 根目录 `REUSE.toml` | 装不下注释的文件（图片 / JSON / 锁文件 / 法律文书 / vendored）集中声明 |

- 命令：`uv run python scripts/spdx.py --check`（或 `--fix`）。纯标准库，无第三方依赖。
- `--check` 还会报「既装不下内联头、又没在 `REUSE.toml` 声明」的文件——**不允许无主文件**。
- `.py` 另有一道 ruff 门禁：`pyproject.toml` 的 `[tool.ruff.lint.flake8-copyright] notice-rgx`
  已把 CPY001 钉在那行版权文本上（只覆盖 Python，且**只查版权行**；许可行与非 Python 文件
  靠上面的工具补位）。
- **新增文件类型时**：能写注释 → 加进 `scripts/spdx.py` 的 `_COMMENT_STYLES`（无扩展名的按
  `_NAMED_STYLES` 认领，如 `.editorconfig` / `.gitignore`）；装不下 → 加进 `REUSE.toml`。
  两条路都走不通，`--check` 会报「未归类」并中止检查。
- **不引入 `reuse` CLI**（`fsfe/reuse-tool` 是 GPL-3.0-or-later，撞许可红线）；本项目只采用
  它定义的 `REUSE.toml` **数据格式**，读写由 `scripts/spdx.py` 自己实现。
- 编辑器传绝对路径也能用（`--check "$PWD/README.md"` / `${file}` / `$FilePath$`）：工具会折成
  仓库相对路径；不在仓库内的路径直接跳过。

## 编辑器层（可选便利，不是约定）

约定永远在仓库层（上面三层）；编辑器层只在**写入时**带上，更换编辑器即失效、须重配：

- **VS Code**
  - 片段：`.vscode/spdx.code-snippets`，打 `hdr` + Tab 出头（`skill` 出 SKILL.md 骨架）；
  - 任务：`.vscode/tasks.json` 的「SPDX: 给当前文件补头 / 全库校验」，调的是同一个 `scripts/spdx.py`。
    **工作区不支持键位绑定**，快捷键写在**用户级** `keybindings.json`：
    `{ "key": "ctrl+alt+h", "command": "workbench.action.tasks.runTask", "args": "SPDX: 给当前文件补头" }`；
  - 模板扩展（可选）：`TrevorNesbitt.smart-file-templates`（**MIT**）+ 根 `.fileTemplates.json` +
    `.vscode/templates/*.template` → 新建文件时按规则套模板，这是 VS Code 里最接近 PyCharm 的做法。
    （同类 `rioj7/vscode-file-templates` 仓库**没有 LICENSE**，默认保留所有权利，不推荐。）
- **PyCharm**：`Settings → Editor | Copyright`——Copyright profile（文本 + 文件 scope，支持 Velocity
  模板），勾 `Share through VCS` 会落到 `.idea/copyright/*.xml` 随库共享，再开
  `Tools | Actions on Save → Update copyright notice` 即可保存时自动补。也可以更省事：用
  External Tools 直接调 `uv run python scripts/spdx.py --fix $FilePath$`。
- **`.editorconfig`**：工程级编辑器约定（字符集 / 行尾 / 缩进 / 尾新风）。**PyCharm 原生读；
  VS Code 需要 `EditorConfig.EditorConfig` 扩展**（已进 `extensions.json` 推荐）。
  文件里只声明「库里事实上一致」的项——JSON / TOML 缩进本来混用就不声明，免得一格式化就出噪声 diff。

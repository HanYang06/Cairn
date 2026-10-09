<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 文档规则

## 两类文档，别混

| 类 | 在哪 | 谁维护 | 能不能手改 |
|---|---|---|---|
| **手写事实源** | `docs/**/*.md`（除生成物）、`README.md`、`AGENTS.md`、`src/**` 的 docstring | 人；跟代码一起提交 / 评审 | ✅ 就该改这里 |
| **生成物** | `docs/reference/config.md`、`docs/api/**` 的渲染结果、`site/` 整站 | `scripts/docgen.py`、`mkdocs` + `mkdocstrings` | ❌ 改源头或生成器 |

**不许手写 API 文档**：签名 / 参数 / 返回类型 / 成员清单都由
[mkdocstrings](https://mkdocstrings.github.io/) 从 `src/**` 抽取（走 griffe 的 AST 解析，
不执行代码）。手写一份必然过期，最终与代码不符。

**不许手写「机器已有单一事实源」的表**：配置项来自**声明现算**（`core/conf` 的词表投影），
由 `scripts/docgen.py` 生成整页到 `docs/reference/config.md`（带 SPDX 头与「勿手改」声明）。
要加一条配置 → 在用到它的包里 `conf("键", 默认值, type=…, doc=…)` 声明 →
跑一遍程序（值文件与词表顺带落盘）、再跑 `docgen.py --write` 更新参考页。
`docgen.py --check` 已进 CI，漂移即失败；入库的投影与声明是否分叉由
`tests/core/test_conf_projection.py` 拦。

## 工具链（已落）

| 手段 | 负责 | 命令 |
|---|---|---|
| 站点与 API 参考 | `mkdocs` + `mkdocstrings`（griffe AST 抽取） | `uv run mkdocs serve` / `uv run mkdocs build --strict` |
| 配置项参考页 | `scripts/docgen.py`（读声明现算的词表投影） | `uv run python scripts/docgen.py --write` / `--check` |
| 投影防漂移（值文件 / 词表） | `tests/core/test_conf_projection.py`（跑一遍即生成） | `uv run pytest tests/core/test_conf_projection.py` |
| docstring 覆盖报告 | `scripts/docgen.py`（AST 统计） | `uv run python scripts/docgen.py --coverage` |

- 依赖在 `pyproject.toml` 的 `[dependency-groups] dev`：`mkdocs-material`（**MIT**）、
  `mkdocstrings[python]`（**ISC**）、`mkdocs-static-i18n`（**MIT**）。**构建期依赖**，不进运行期、不进 wheel。
- 取包路径由 `mkdocs.yml` 的 `plugins.mkdocstrings.handlers.python.paths: [src]` 提供，
  故指令直接写顶层包名（`::: core`），**不带 `cairn.` 前缀**。
- `site/` 是构建产物、不入库；生成页（`docs/reference/config.md`）**入库**，好让 GitHub 上也能读。
- 部署：`.github/workflows/docs.yml` —— `main` 的文档变更 → 防漂移 + strict 构建 → GitHub Pages；
  PR 只做门禁、不发布。触发面里的 `docs/**` 已覆盖下面的自定义样式，改主题即重建。

## 文档站自己的外观

文档站与桌面界面**共用一套设计语言**：主题本体在 `docs/stylesheets/cairn.css`，
由 `mkdocs.yml` 的 `extra_css` 引入。本仓库不覆盖模板，故不设 `custom_dir`——
这里只覆盖主题自带的 CSS。

- **令牌的取向以 `config/theme/tokens.json` 为准**（那是外观的唯一手写处，判据见
  `docs/architecture/ui_design/ui-theme.md` §3）。`cairn.css` 只是**投影**：
  文件顶部把令牌按同名搬到 `--cairn-*`，再映射到 Material 的 `--md-*` 变量。
- **改令牌要同步这里**：纸面 / 面板 / 暖金 / 圆角 / 字号 / 阴影任一档改值，同一改动里改
  `cairn.css`。两处不一致时页面会出现"半套暖金、半套冷蓝"。
- **两档都要写全**：Material 只按 `default` 与 `slate` 分档，漏写的那档会退回它自带的色。
- 站点不用 Google Fonts：`--md-text-font-family` / `--md-code-font-family` 指向前端的字体链。
- **站点图标必须是自己的**（`mkdocs.yml` 的 `theme.logo` / `theme.favicon`，素材在
  `docs/assets/brand/`，由 `assets/logo/` 缩出）。不得留主题自带的占位图标。
- **Material 取 `--md-primary-fg-color` 的地方要显式覆盖**：本主题把那两个变量给了纸面，
  故顶栏 / 页脚底色与 `.md-button--primary` 都得自己写；不写就会出现"浅底深字的主按钮"。
  按钮形态照前端 `.pill`：胶囊 · 实心 accent 底 · 一屏最多一个主操作。
- **图标短码（`:octicons-…:`）要在 `markdown_extensions` 里开 `pymdownx.emoji`**，
  否则原样显示成字面文本；按钮里的图标还需覆盖 `svg path` 的固定 `fill`（否则深灰落在 accent 底上）。

## 多语言文档（中文原文 + 英文机翻）

站点是双语的，**中文是事实基础（作者亲手写），英文是机器翻译的产物**。判定由
`mkdocs-static-i18n` 的 suffix 模式给出：**带 `.<locale>` 后缀的文件是译文，不带后缀的归默认语言**。
"谁是事实源"因此只看扩展名——**不带后缀的那一份就是**。

| 语言 | 文件 | 线上路径 | 谁写的 |
|---|---|---|---|
| 中文（默认，**事实基础**） | `docs/**/*.md` | `/` | 作者 |
| 英文（**机翻产物**） | `docs/**/*.en.md` | `/en/` | CI 的翻译模型（当前 6 页为手写） |

- **默认语言必须是内容齐全的那一边**：`mkdocs build --strict` 的"nav 指向不存在的页"只在
  默认语言里判定，英文当前只译 6 页，故默认只能是中文。反过来做（英文默认）就得给 14 个
  未译页各补一个英文占位页。
- **英文导航只列已译页**（插件 `languages[en].nav`）：未译页若留在英文 nav 里，插件会把中文
  正文渲染出第二份 URL，`mkdocs-autorefs` 报"同一标识多个主 URL"，`--strict` 即失败。
- **`resolve_closest: true` 必须开着**（`mkdocs.yml` 的 `autorefs` 插件）：`fallback_to_default`
  会把未译页渲染第二份，该开关让每个页面指回离自己最近的那一份，而不是逐条告警。
- **`navigation.instant` 与语言选择器不兼容**，故不启用（切语言要整页跳转）。
- **机翻只译正文**：围栏代码块整块保留，行内代码、链接、图片、裸 URL 先摘成占位符再放回。
  **增量译**：每次只处理"缺英文页"或"英文页落后"的，**已一致的页一个字符都不送**——
  这是"译过就落库、不必每次从 0 翻"的机制保障；**手写页**（无摘要行）默认不动，
  `--stamp` 可补摘要行纳入追踪。
  生成器 `scripts/translate.py`（阿里云机器翻译通用版，`TranslateGeneral`），
  `--check` 靠英文页头的 `translation-source-hash` 判漂移，`--list` 报账。
  工作流 `.github/workflows/translate.yml`（`drift` 无凭证即可跑；`translate` 需要
  只授 `alimt:TranslateGeneral` 的 RAM AK，**补译后自动提交到独立分支并开 PR**——
  译文进 `main` 才算持久化）。额度：主账号每月 100 万字符免费，本站全译一遍不到 10%。
  字符量用 `scripts/translate_chars.py` 量。
- 改中文页就要重译英文页；**两边不得停在两版**。已译清单与判定在
  `docs/reference/i18n-status.md`（那一页本身也是双语的）。

## 硬性约定

1. **能算的就不写，能查的就不写**：一份数据只留一个事实源。判断"该不该生成"的方法：
   这份内容是否已存在于代码 / 配置声明 / schema 里——是，就投影，不要抄。
1a. **书面语是硬门禁**：所有文档、注释、docstring 一律非口语化，标准与词典在
   [`prose.md`](prose.md)，由 `scripts/prose.py` 检查（已进 pre-commit 与 CI）。
2. **新页面必须登记进 `mkdocs.yml` 的 `nav`**。未登记的页面会被构建但不出现在导航里，
   `--strict` **不会**因此报错——这条靠自觉，忘了就是一页隐身文档。
3. **新 `.md` 要带 SPDX 头**（`<!-- -->` 两行）。漏了 pre-commit 会补，补完钩子非零退出，
   重新 `git add` 再提交（见 `references/spdx.md`）。
4. **相对链接用文件相对路径**（`../architecture/storage.md`），`--strict` 会抓断链；
   跨仓库文件用完整 GitHub URL（别用相对路径往上跳出 `docs/`，mkdocs 处理不了）。
5. **图文扩展**：Mermaid 用 ` ```mermaid ` 围栏（本站与 GitHub 都能渲染）；
   提示块用三叹号 admonition 语法；引入新的 Markdown 扩展时必须同步修改 `mkdocs.yml`。
6. **中文写作**、术语按 `docs/reference/glossary.md`；未实现的东西标「预留 / 草案 / 待定」。
7. **权威顺序 `路线图 > 设计 > 代码`**（路线图管「要什么」、代码管「现在是什么」）：
   改了实现就回写 `docs/architecture/*.md`（回写是任务的一部分）。
8. `README.md` 是 GitHub 门面，**不重复** `docs/` 里会长大的内容（两处必然分叉）——
   只放入口、定位、最短命令，细节链接过去。

## 坑：MkDocs 构建钩子不能放在 `docs/` 里

MkDocs 的 `hooks:` 把 `docs/` 当包目录（`docs.hooks`），与 Python 包导入撞名后
**钩子会被静默忽略**（不报错、不警告、事件一次都不触发——本仓库踩过这个坑）。
要写钩子就放**仓库根**（如 `mkdocs_hooks.py`），再在 `hooks:` 里写那个路径。
排查手法：让钩子方法直接 `raise`，构建不炸就说明它根本没被加载。

**能用生成文件解决就别上钩子**：`scripts/docgen.py --write` 生成 + `--check` 防漂移
比"构建时注入"更好验证——生成物入库还能在 GitHub 上直接读。

## 加 API 页面

```markdown
# core（底座）

::: core
    options:
      members: false
```

- `::: 模块路径` 递归渲染该模块的公开成员（`filters` 已排除 `_私有` / `__dunder`）。
- 只想收一部分：`members: [Core, Signal]`；单开一页：`::: core.core.Core`。
- 全局选项（docstring 风格 / `show_source` / `show_submodules` / `filters`）在 `mkdocs.yml`，
  别在页面里重复覆盖，除非确有例外。
- `show_if_no_docstring: false` 意味着**没写 docstring 的公共成员会从文档里消失**。
  用 `uv run python scripts/docgen.py --coverage` 看当前漏了多少（目标：`DOCSTRING_MIN`）。


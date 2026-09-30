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
  `mkdocstrings[python]`（**ISC**）。**构建期依赖**，不进运行期、不进 wheel。
- 取包路径由 `mkdocs.yml` 的 `plugins.mkdocstrings.handlers.python.paths: [src]` 提供，
  故指令直接写顶层包名（`::: core`），**不带 `cairn.` 前缀**。
- `site/` 是构建产物、不入库；生成页（`docs/reference/config.md`）**入库**，好让 GitHub 上也能读。
- 部署：`.github/workflows/docs.yml` —— `main` 的文档变更 → 防漂移 + strict 构建 → GitHub Pages；
  PR 只做门禁、不发布。

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
7. **代码是唯一事实**：改了实现就回写 `docs/architecture/*.md`（回写是任务的一部分）。
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


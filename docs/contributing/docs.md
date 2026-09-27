<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 怎么改文档

## 两类内容，两条规矩

| 类型 | 在哪 | 谁维护 |
|---|---|---|
| **手写文档**（事实源） | `docs/**/*.md`、`README.md`、`src/**` 的 docstring | 人；跟代码一起评审 |
| **自动生成** | 「[API 参考](../api/index.md)」的签名 / 类型 / docstring、整个 `site/` | 工具；**不要手改** |

**不得手写 API 文档**：签名、参数、返回类型都由 [mkdocstrings](https://mkdocstrings.github.io/)
从源码的 docstring 与类型注解抽取。改代码则页面随之更新；改 docstring 则页面描述随之完善。

## 加一篇文档

1. 在 `docs/` 下建 `.md` 文件（放对子目录：`guides/` 向导、`architecture/` 设计、`reference/` 查阅）。
2. **顶部加 SPDX 头**（`<!-- -->` 两行）——遗漏时 pre-commit 会补，
   但补完钩子会非零退出，重新 `git add` 再提交即可。
3. 在 `mkdocs.yml` 的 `nav:` 里登记它。**未登记的页面仍会被构建，但不出现在导航里**
   —— `--strict` 不对此报错，需人工保证。
4. 本地预览：

```powershell
uv run mkdocs serve            # http://127.0.0.1:8000（热重载）
uv run mkdocs build --strict   # 与 CI 同口径：坏链接 / 缺页面 / 未知配置即失败
```

## 写作口径

- **中文**，与现有文档一致；术语按「[术语表](../reference/glossary.md)」，不得自造同义词。
- **未实现的功能不得写成已实现**：未做的部分写「预留 / 草案 / 待定」，并说清现状。
  文档与代码不符的代价，是本项目最高的一项成本。
- **代码是唯一事实**：`docs/architecture/*.md` 与实现冲突时，改实现后**回写文档**
  （回写是任务的一部分，不是后续任务）。
- 相对链接用文件相对路径（`../architecture/storage-design.md`）；断链由 `--strict` 报出。
- 图用 [Mermaid](https://mermaid.js.org/) 围栏代码块（` ```mermaid `），本站与 GitHub 都能渲染。

## 加 API 页面

`docs/api/*.md` 里是 mkdocstrings 指令，例如：

````markdown
# core（底座）

::: core
    options:
      members: false
````

- `::: 模块路径` 会递归渲染该模块的公开成员（`filters` 已排除 `_私有`）。
- 顶层包**去 `cairn.` 前缀**，`paths: [src]` 已在 `mkdocs.yml` 里配好，直接写 `core` / `feature` 即可。
- 只想写某几个类：`members: [Core, Signal]`；要单独一页：`::: core.core.Core`。

## 构建产物

- `site/` 是**构建产物，不入库**（已 gitignore，且在 `REUSE.toml` 里集中声明，
  免得 SPDX 门禁把它当无主文件——虽然 `tools/spdx.py` 走 `git ls-files`，本来就躲得开）。
- 部署由 `.github/workflows/docs.yml` 负责：`main` 分支的文档变更 → 防漂移检查 → strict 构建 →
  发到 GitHub Pages（用官方 Pages Actions，**不推 `gh-pages` 分支**）。

!!! warning "一个仓库只能有一个往 Pages 发布的工作流"

    GitHub 在开启 Pages 时会自动生成一份 `jekyll-gh-pages.yml`（Jekyll 模板，从**仓库根**构建）。
    它和本站的 `docs.yml` **抢同一个 `github-pages` 环境**：两者都在 `push main` 时跑、
    都往站点根目录发布，谁后跑完谁覆盖——**站点会在两个版本之间反复跳**，而且都不报错。
    本站用的是 MkDocs，所以那份 Jekyll 模板**已删除**；若它再被生成出来，直接删掉。


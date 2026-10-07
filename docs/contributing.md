<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 贡献与许可

Cairn 尚在早期。提交前先读「[约定与红线](guides/conventions.md)」：许可、SPDX、分层三条红线由 CI 拦截。

## 怎么参与

| 目的 | 去哪 |
|---|---|
| 准备环境、运行测试 | [参与开发](guides/development.md) |
| 确认某个词的含义 | [术语表](reference/glossary.md) |
| 了解设计理由 | `docs/architecture/**`（现状 / 意图对照见[架构索引](architecture/index.md)） |
| 查某个类 / 函数的签名 | [API 参考](api/index.md) |
| 改文档、加一页 | [怎么改文档](#怎么改文档) |
| 确认许可与署名要求 | [许可与署名](#许可与署名) |

## 提交约定

- commit message 用**中文 + Conventional Commits**：`feat(core): …` / `fix(ui): …` / `docs: …`。
- 提交前执行 `uv run pre-commit run --all-files`（13 个钩子，清单见
  `.agents/skills/rules/references/quality.md` §4）。钩子需先安装一次：
  `uv run pre-commit install --hook-type pre-commit --hook-type commit-msg`。
- CI（`.github/workflows/ci.yml`）执行同一套门禁，含覆盖率 ≥ 80%。

## 报告问题

仓库：[github.com/HanYang06/cairn](https://github.com/HanYang06/cairn)。
描述问题时附**可复现的最小步骤**；涉及数据的问题请给出库根路径（`CAIRN_VAULT`）与操作序列，
**不要附带真实笔记内容**。

## 怎么改文档

### 两类内容，两条规矩

| 类型 | 在哪 | 谁维护 |
|---|---|---|
| **手写文档**（事实源） | `docs/**/*.md`、`README.md`、`py_src/**` 的 docstring | 人；跟代码一起评审 |
| **自动生成** | [API 参考](api/index.md)的签名 / 类型 / docstring、整个 `site/` | 工具；不得手改 |

**不得手写 API 文档**：签名、参数、返回类型都由 [mkdocstrings](https://mkdocstrings.github.io/)
从源码的 docstring 与类型注解抽取。代码变更使页面随之更新，docstring 变更使页面描述随之更新。

### 加一篇文档

1. 在 `docs/` 下建 `.md` 文件（`guides/` 向导、`architecture/` 设计、`reference/` 查阅）。
2. **顶部加 SPDX 头**（`<!-- -->` 两行）。遗漏时 pre-commit 会补，补完钩子非零退出，
   重新 `git add` 再提交。
3. 在 `mkdocs.yml` 的 `nav:` 里登记。**未登记的页面仍会被构建，但不出现在导航里**；
   `--strict` 不对此报错，需人工保证。
4. 本地预览与门禁：

```powershell
uv run mkdocs serve            # http://127.0.0.1:8000（热重载）
uv run mkdocs build --strict   # 与 CI 同口径：坏链接 / 缺页面 / 未知配置即失败
```

### 写作口径

- **中文**；术语按「[术语表](reference/glossary.md)」，不得自造同义词。
- **未实现的功能不得写成已实现**：未做的部分写「预留 / 草案 / 待定」，并说明现状。
- **权威顺序是 `路线图 > 设计 > 代码`**：路线图管「要什么」、代码管「现在是什么」；
  `docs/architecture/*.md` 与实现冲突时，改实现后**回写文档**（回写是任务的一部分）。
- 相对链接用文件相对路径（`../architecture/storage-design.md`），断链由 `--strict` 报出。
- 图用 [Mermaid](https://mermaid.js.org/) 围栏代码块（` ```mermaid `），本站与 GitHub 均可渲染。

### 加 API 页面

`docs/api/*.md` 中是 mkdocstrings 指令，例如：

````markdown
# core（底座）

::: core
    options:
      members: false
````

- `::: 模块路径` 递归渲染该模块的公开成员（`filters` 已排除 `_私有`）。
- 顶层包**去 `cairn.` 前缀**，`paths: [py_src]` 已在 `mkdocs.yml` 中配置，直接写 `core` 即可。
- 只渲染指定类：`members: [Kernel, Bus]`；单独一页：`::: core.init.Kernel`。

### 构建产物与部署

- `site/` 是**构建产物，不入库**（已 gitignore，并在 `REUSE.toml` 中集中声明）。
- 部署由 `.github/workflows/docs.yml` 负责：`main` 的文档变更 → 防漂移检查 → strict 构建 →
  发布到 GitHub Pages（用官方 Pages Actions，不推 `gh-pages` 分支）。
- 一个仓库只允许一个向 Pages 发布的工作流。GitHub 在开启 Pages 时可能自动生成
  `jekyll-gh-pages.yml`（从仓库根构建），它与本站的 `docs.yml` 争用同一 `github-pages` 环境，
  导致站点在两个版本间交替覆盖。若该文件再次出现，应删除。

## 许可与署名

### 本项目

Copyright 2026 HanYang06 · **Apache License 2.0**。

分发时请一并保留 [`LICENSE`](https://github.com/HanYang06/cairn/blob/main/LICENSE)
与 [`NOTICE`](https://github.com/HanYang06/cairn/blob/main/NOTICE)。

### 依赖许可政策

| 类别 | 结论 |
|---|---|
| MIT / ISC / BSD / Apache-2.0 | **允许引入**：宽松许可，可商用、可闭源分发 |
| **GPL / AGPL** | **禁止引入**：传染性条款会将本项目转为 GPL |
| 禁止商用类（CC-BY-NC、PolyForm NC） | 与“可商用”目标冲突，不引入 |

- 开发期工具适用同一标准：`fsfe/reuse-tool` 为 GPL-3.0-or-later，因此**不引入 `reuse` CLI**，
  只采用其定义的 `REUSE.toml` **数据格式**，读写由自研的 `scripts/spdx.py` 实现。
- 新增依赖后**复核** `NOTICE` / `pyproject.toml` 的许可声明；第三方主题 / 画布 / 编辑器库
  先核实许可再采用。

#### 本站用到的工具（构建期依赖，不进产品）

| 工具 | 许可 |
|---|---|
| [MkDocs](https://www.mkdocs.org/) | BSD-2-Clause |
| [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) | MIT |
| [mkdocstrings](https://mkdocstrings.github.io/) / `mkdocstrings-python` / Griffe | ISC |

### 源码与署名

- 每个源文件 / 文档顶部的 **SPDX 头**是许可声明的机器可读形式，由 `scripts/spdx.py`
  自动补 / 校验，不要手写（见「[约定与红线](guides/conventions.md)」§2）。
- 装不下注释的文件（图片 / JSON / 锁文件 / 法律文书 / vendored）在根 `REUSE.toml` 集中声明。
- 第三方 vendored 的技能保持上游原样，来源与 hash 记入 `skills-lock.json`。

### 全文

#### LICENSE

```text
--8<-- "LICENSE"
```

#### NOTICE

```text
--8<-- "NOTICE"
```

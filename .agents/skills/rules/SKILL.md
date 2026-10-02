---
name: rules
description: "Cairn 项目规则总入口。改动代码、文档、依赖、提交或引入第三方库之前，先在此按场景读取对应规则；只读与当前任务相关的那条，没有命中的规则就跳过。"
license: Apache-2.0
---

<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Cairn 项目规则

本技能是**规则总入口**：根目录 `AGENTS.md` 只做索引与红线，细则写在这里，按场景分发到 `references/`。

## 怎么用

1. 判断当前任务命中哪个场景（见下表）。
2. **只读**对应那条 `references/*.md`；没有命中的规则直接跳过，不要全读。
3. 规则与代码或 `docs/architecture/*.md` 冲突时，以代码与文档为准，并一并修正规则。

## 场景路由

| 场景 | 规则 |
|---|---|
| 提交 / commit message | [`references/commit.md`](references/commit.md)（并加载 `git-commit` 技能） |
| 新增依赖、引入第三方主题 / 画布 / 库 | [`references/licensing.md`](references/licensing.md) |
| 新建或修改任何源文件 / 文档 | [`references/spdx.md`](references/spdx.md) |
| **写任何文档 / 注释 / commit message（书面语）** | [`references/prose.md`](references/prose.md) |
| 写 / 改文档、加文档页面、动 API 参考或文档站 | [`references/docs.md`](references/docs.md) |
| **写任何 Python 代码（风格 / 魔法用量 / 类型）· 质量门禁** | [`references/quality.md`](references/quality.md) |
| 新增 / 修改界面（前端组件 / 样式 / 令牌） | [`references/frontend.md`](references/frontend.md)（**写第一行前端代码前先读**） |
| 界面边界（分层 / 依赖方向 / 壳与内核的分工） | [`references/ui-boundary.md`](references/ui-boundary.md) |

> 新规则出现时：在这里加一行路由 + 一个 `references/` 文件。**不要把长文写回 `AGENTS.md`。**

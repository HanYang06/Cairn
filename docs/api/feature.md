<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# feature（领域）· 待重建

> **这一层在 2026-09-29 的内核重建里被整条删除**（见
> `.agents/skills/memory/progress.md`「界面层重建余项」）：`src/feature/` 已不存在，
> 故本页暂时没有可抽取的代码。

原定位（重建后照这个方向回来）：

- **域**（note / project）+ **共享件**（`shared/`）；
- 只依赖 `core` 的公共 API；**域之间互不依赖**，跨域协作归 App；
- 领域结构直接继承 `Block`，扩展只走子类字段、新 `type` 或新关系 `kind`；
- 正文模型（行序列 + 行内区间样式）见 [`note-model.md`](../architecture/note-model.md)。

代码回来之后，把这一页改回 mkdocstrings 抽取（`::: feature` / `::: feature.note` …）。

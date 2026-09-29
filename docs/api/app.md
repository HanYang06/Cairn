<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# app（应用组合根）· 待重建

> **这一层在 2026-09-29 的内核重建里被整条删除**（见
> `.agents/skills/memory/references/progress.md`「内核重建」）：`src/app/` 已不存在，
> 故本页暂时没有可抽取的代码。

原定位（重建后照这个方向回来）：

- **组合根 / 编排层**：组合内核 + 领域 + `ui_tools`，按平台发布；
- **只有它认识领域** —— 建域服务并注入 UI，UI 自己不 new 领域对象；
- 平台分派（`python -m app`）：非 Windows 平台**没有 UI**，打印提示并返回退出码 2。

代码回来之后，把这一页改回 mkdocstrings 抽取（`::: app` / `::: app.win` …）。
在此之前，`pyproject.toml` 的 hatch 打包与 mypy 范围都不含这一层。

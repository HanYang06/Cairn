<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# ui_tools（界面工具层）· 待重建

> **这一层在 2026-09-29 的内核重建里被整条删除**（见
> `.agents/skills/memory/progress.md`「内核重建」）：`src/ui_tools/` 已不存在，
> 故本页暂时没有可抽取的代码。

原定位（重建后照这个方向回来）：

- 界面**工具箱**：声明树 / 编译 / 绑定 / 模型 / 主题 / 组件 / 布局；
- **不认识领域** —— 不 import `feature`、不碰 `core.storage`（有架构测试断言）；
- **这一层不依赖 Qt**；Qt 只在接入点那一处出现（边界）。

代码回来之后，把这一页改回 mkdocstrings 抽取（`::: ui_tools` / `::: ui_tools.core` …）。

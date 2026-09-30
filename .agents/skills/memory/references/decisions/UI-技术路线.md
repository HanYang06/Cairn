<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

## UI 技术路线（2026-09-18，现行）

- 已定 · **Widgets 宿主 + QML 岛**：工作台外壳、列表/树、检查器、编辑器、菜单/对话框全部走
  QtWidgets（Python 对象组合）；QML 只保留给**画布 / 大规模关系图 / 特殊视觉**这类自包含「岛」。
- 已定 · **编辑器用 `QTextEdit` + `QTextDocument` + `QUndoStack`**：一条硬行 ≈ 一个 block，
  与笔记行模型同构；跨行选区、撤销/重做、IME、代码高亮由框架提供（QML 逐行 `TextEdit` 做不了）。
- 已定 · **判据三条**：① Qt 只支持 Widgets 里嵌 Quick，不支持 Quick 里嵌 Widgets；
  ② App 需要的动效类别（硬切/软切/渐变/滑移）Widgets 全覆盖，QML 的连续高频场景图收益与产品不符；
  ③ **实现语言须在负责人射程内**——组件库用 Python，负责人可参与设计与维护（QML 做不到）。
- 已定 · **命名分层**：`App`（QObject 组合根：Session/facade/命令表）+ `MainWindow`（QMainWindow）
  + `Component` / `Panel` / `Page`（部件基类）。依赖显式注入，不用全局单例。
- 已定 · **QML 岛是哑视图**：输入类型化 VM、输出回调；不持应用状态、不碰 Vault、不反向耦合。
- 已定 · 组件建造四规则：**联动在控制器**（compound components，不控件互连）、
  **布局靠 `VBox/HBox/Grid/Split` 嵌套组合**（不新增原语）、**增长只在原子与页面**、
  **主题 = 点分配置 → QSS 编译 + 有限 Qt 侧增强**。细则见 `rules/references/ui-boundary.md` §6。

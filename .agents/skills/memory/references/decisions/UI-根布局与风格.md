<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

## UI 根布局与风格（2026-09-21，Windows 壳起步）

- 已定 · **根布局三带**：顶带（工具栏，相对固定）+ 舞台（自由度最高的主区）+ 任务栏（长期任务）。
  边缘（导航 / 检查器 / 关系 / 版本）按需出现、默认收起；专注时全隐。
- 已定 · **捕捉与整理 = 同一空间换态**（不另开捕捉窗）：浏览（卡片流）/ 专注（一卡占满）/ 组织（看板 / 画板）。
- 已定 · **笔记与项目同构**：舞台只有「卡片」一种单元；项目 / 组 / 标签是**镜头（过滤器）**，不是顶级分区。
  「进项目」= 换镜头，不是换世界。以此兑现最早的「融合」诉求。
- 已定 · **卡片四粒度**：卡 → 展开（卡内编辑）→ 专注（占满）→ 落板（拿空间坐标）。
  卡自带位置属性，规则视图是派生、画板是手动覆盖。
- 已定 · **两种密度**（照 Windows 资源管理器，只留两种）：卡片（大 / 中图标）/ 详细（列表）。
  笔记与项目混排，靠 `kind` 颜色区分（note 蓝 / project 赭）。
- 已定 · **软质感**：低饱和冷灰底 + 少量暖赭点缀，圆角、柔和阴影、留白、半透明「毛玻璃」近似；
  真 Acrylic（Windows DWM）另立，不假装已实现。
- 已定 · **顶带 = 工具栏**：搜索 / 命令常驻；其余功能走**伸缩抽屉**。
- 已定 · **工具底座 = 大方框 + 格子 + 槽（无任何业务词汇）**：`App.root` 是空的大方框，作者用
  `set` / `add` / 嵌套自由搭出任意结构（三栏 / 异形都行）；`Slot`（命名槽位）用 `expects=` 声明
  等谁的哪个部件。**工具里不留 `topbar` / `navigator` / `content` 这类预置区域**
  （上一版 `SuperLayout` / `TopBar` / `TaskBar` 已删）。
- 已定 · **谁定义标签，标签归谁**：App 的槽名 App 起，Facet 的部件名领域起，**不代定义**。
- 已定 · **`App` = 根 / 定义，`Facet` = 子件**：`App.add(facet)` 遍历结构里的槽，按 `expects` 取
  `facet.parts()` 同名部件填入。Facet 说领域话（`parts()`：`page` / `nav`…），App 说 App 话
  （槽名 + 填充规则）。**组件 / 布局只被 Page 或 Facet 消费；App 不直接吃组件 / 布局。**
- 已定 · **槽只管自己的行为**（弹性 `stretch` / 滚动 `scroll` / 顶对齐 `align` / 隐藏 `hidden` /
  锁死 `locked` / 容量 `capacity`），**不管内容怎么显示**——内容显示是组件自己的事，别本末倒置。
- 已定 · **`Surface` = 带外观的通用容器**（背景 / 圆角 / 可选投影），App 搭格子用的普通组件。
- 已定 · **实现归位**：机制进 `ui_tools`，组装与数据进 `app/win`（`windows/CairnApp` + `NoteFacet`
  + 主题加载，`backend/` 投影），外观进 `config/theme/*.json`。**壳不得绕开 `ui_tools` 用裸 Qt 搭**。
- 已定 · **增长只在 `ui_tools` 目录**：加组件 / 布局 / 页面就进 `component/` / `layout/` / `page/`；
  **内核非必要不修改**（仅当内核确实不支持时才动）。
- 已定 · **UI→UI 绑定用动作句柄**：`Node.action(方法名)` 返回 `NodeAction`，编译期解析到控件方法
  （密度按钮 `.clicked` → `stage.action("toggle_density")`），不把 Qt 控件泄进声明层。
- 已定 · **外观唯一真源 = `config/theme/*.json`**：由 `ui_tools.core.load_theme` 加载，`App.theme` 持有，
  卡片委托按令牌取色；壳不再自带硬编码色。默认 GitHub 色盘（`github-dark` / `github-light`），改盘待定。
- 已定 · **领域 Facet 自带视图控件**：卡片 / 详细密度切换归笔记 Facet（内容自带），不进 App 顶带（免跨层）。
- 方向 · **对象驱动生成（待落）**：把领域对象交给 `Facet` 应自动产出卡片 / 字段 / 配置等机械件，
  作者只写领域页面本身；当前卡片提取器仍是手写，属下一片。
- 已定 · **`App` 拥有生命周期与启动**：`CairnApp.open()`（开库 + 组装）/ `.run()`（套主题 → 建窗 →
  事件循环）；`main` 只剩一行 `CairnApp.open().run()`。Qt 启动实现放 `ui_tools.core.qt.run`（Qt 边界），
  `core` 仍 Qt-free。**不把 Qt 启动样板与两步 `build` 暴露给使用者**（上一版作废）。
- 进行中 · 第一片（App 级根壳 + 笔记 Facet + 真实数据 + `ui_tools` 管线 + config 主题）已落；
  自动生成 / 抽屉 / 任务栏真实任务 / 边板 / Acrylic / 笔记编辑页待续。

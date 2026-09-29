<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# UI 边界规则（Widgets 宿主 + QML 岛）

决定：`references/decisions/` 的「UI 技术路线（2026-09-18）」。本文件是**可执行约定**，新增 / 改 UI 前先读。

## 一、技术归属

- **Widgets（QtWidgets，Python）**：工作台外壳、菜单 / 工具栏 / 状态栏 / 停靠、列表 / 树、
  表单 / 检查器、**编辑器**、对话框 / 弹层、命令面板。
- **QML（Qt Quick）**：只做**岛**——画布 / 墨迹、大规模关系图、特殊视觉 / 过渡。
  判据命中才开：① 高频重绘 / GPU 场景图 / 着色器；② 大规模图可视化；
  ③ 独立的声明式动画画面；④ 高度自定义、非标准控件的视觉面。
- 原因①：Qt 只支持 **Widgets 里嵌 Quick**（`QQuickWidget` / `createWindowContainer`），
  不支持 Quick 里嵌 Widgets。**宿主只能是 Widgets。**

## 二、命名分层

| 名 | 职责 |
|---|---|
| `App` | QObject **组合根**：拥有 Session / facade / 命令表，被 UI 注入 |
| `MainWindow` | `QMainWindow`：OS 窗口 + 菜单 / 工具栏 / 状态栏 / 停靠 / 中央区 |
| `Component` | 所有部件的薄基类（令牌访问、`objectName` 约定） |
| `Panel` / `Page` | 可停靠侧栏 / 中央内容页 |

## 三、硬约定

1. **显式依赖注入**：`def __init__(self, app: App, parent=None)`；不用全局单例 / context property。
2. **部件只发意图信号**（`noteActivated(str)`、`renameRequested(str)`），业务由装配层转给 facade。
3. **UI 不 import `feature` / 不碰 `Vault`**，只经 facade / Session。
4. **样式只来自令牌**：`ui/theme` 是唯一真源，由 `tokens → QSS` 全局应用；
   组件内禁止硬编码颜色 / 间距 / 圆角。
5. **`objectName` 必填**，QSS 按它选；一文件一主类，文件名 `snake_case`、类名 `PascalCase`。
6. 布局用 Qt 现成的 `QVBoxLayout` / `QHBoxLayout` / `QGridLayout` / `QSplitter`。
7. **不要造绑定框架**：不把 QML 的声明式魔法搬进 Python，保持朴素对象组合。

## 四、QML 岛接入范式

- 每个岛有一个 `QWidget` 外壳（如 `CanvasView(QWidget)` 内含 `QQuickWidget`），
  对外只暴露 QWidget 的信号 / 槽 + 类型化 VM；宿主只认这个壳。
- 岛内**禁止**：持应用状态、读 / 写 Vault、直接耦合 Widgets、承担业务。
- 弹层 / z-order 一律走 Widgets（原生子窗口叠放有限制）。

## 五、禁止项（防回退）

- 在 QML 里用 `ListModel.append/clear` 手工重建受管列表 → 必须走 `QAbstractItemModel`。
- 在 QML 里持有 App 状态（选中集 / 折叠集 / 拖拽载荷 / 编辑中 id）。
- 用 QML JS 现算富文本 / 序号 / 展示字符串 → 放 Python 视图模型。
- 新增 `Property(list[dict])` 这类无类型跨边界结构 → 用 `rows.py` 的类型化 DTO。

## 六、组件 / 布局 / 主题建造规则（2026-09-18）

- **联动在控制器，不在控件之间**：组合式组件（compound components）用共享控制器 / 状态对象协调
  零件；零件只发意图，**禁止控件间直接互连**（否则成蜘蛛网、无法复用）。
- **布局靠原语嵌套组合**：底层只 `VBox / HBox / Grid / Split / Stack`（配伸缩 / 对齐 / 跨行列）；
  复杂 / 异形 / 非对称结构由嵌套 + 权重拼出，**不新增原语**。
- **组合可递归**：组合类型可以再组合，深度不设限；再组合出来的**类型仍归为组合类型本身**，
  不引入新的层级概念。组合只增复杂度，不增概念。
- **增长只在原子与页面**：加控件只改原子目录；加功能只改页面组合；内核与外壳保持稳定。
- **主题 = 点分配置 → QSS 编译**：配置只覆盖 QSS 能表达的（token / widget / 伪状态 / 页面作用域）；
  阴影 / 动效等落到代码侧（`QGraphicsDropShadowEffect` / `QPropertyAnimation`），
  增强**逐条加、可测、有边界**，不模拟整个 CSS。

### 主题包约定（2026-09-18）

- 主题文件放 `config/theme/*.json`，**文件名即主题名**；`CAIRN_THEME_DIR` 可覆盖目录。
- 主题文件**两段式**：全局 `token` 块 + `style` 块（**CSS 式选择器 → 声明块**，选择器点名目标，
  声明块写属性）：
  ```json
  { "token": { "accent": "#2F81F7" },
    "style": {
      "widget.Button":       { "background": "token.elevated" },
      "widget.Button:hover": { "border_color": "token.accent" } } }
  ```
  选择器为 `widget.<类型>[:<状态>]`；声明键取该部件的可样式属性。
- 加载时展开为点分路径（`token.<字段>` / `widget.<类型>[.<状态>].<属性>`）并由 schema 自动校验；
  未知段 / 选择器 / 属性**报错**（不静默失效）。
- 供 IDE 校验的 JSON Schema 落 `config/schema/theme.json`（**随 UI 重建**：生成器
  `tools/gen_theme_schema.py` 与漂移用例随界面工具箱一并删除，回来时同款两段式重建）。
- 只有 `cairn.ui.components` 下的部件进主题词汇表；外壳 / 页面 / 测试类不入，保证 schema 确定。

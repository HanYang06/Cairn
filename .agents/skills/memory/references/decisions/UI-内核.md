<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

## UI 内核（2026-09-19，重定；设计总纲 `docs/architecture/ui-kernel.md`）

- 已定 · **两套内核**：数据内核（`core`/`feature`）升级调整；UI 内核（`ui/`）重新设计。
  **UI 内核 ≠ Qt**——它负责「对象 → 界面」的生成 / 编译 / 绑定 / 配置，Qt 只是实现材质。
- 已定 · **技术路线：QtWidgets 宿主 + QML 岛**（沿用 2026-09-18 三条判据）；画布 / 大关系图走 QML 岛。
- 已定 · **数据直通 = 内核预埋信号代理 + 投影 + 命令**：信号代理（现为 `core/events.py` 的
  `EventBus`）是 UI 与 feature 的统一变更源；UI 经 `投影(Session) → Bridge → Model` 消费，
  **不 import `feature`、不碰 `Vault`/`Bucket` 内部**；写回一律走命令。**单向数据流**。
- 已定 · **快捷创建 = 对象驱动生成**：由领域对象（Note/Project…）内省出 **UI 模板树**（可用初稿）+ 套通用架构默认行为；开发者只改细节。**特化优于通用**，不求外部框架式极致通用；自动生成只出模板，细节不猜、不假装已实现。
- 已定 · **事件绑定 = 声明 + 编译**：组件只发意图 → 命令；内核信号 → Session → Qt。**不做响应式框架 / reconciler / 双向绑定**。
- 已定 · **统一 Config = Theme（封闭词表，外观唯一真源）+ UiConf（开放词表，随组件生长）**；选择器 `widget.<类型>[:<状态>]`，**比 CSS 轻**（不做层叠 / 继承 / 优先级）。
- 已定 · **数据内核须配合补**：字段内省 API（现缺，类型信息只在 `Block.__init_subclass__` 内部消费）、
  字段 traits（纯数据展示语义）、`batch` 合并事件、`Vault` 死 API 收口。
- 已定 · **各司其职 = 领域契约**：领域对象除结构 / 事件外，另声明 UI 可消费的契约
  **`fields` / `actions` / `signals`**；UI 按契约绑定与生成。**契约是领域的事，渲染是 UI 的事**。
  契约**不得长在 `Block` 上**；字段描述符（`Attr`/`Data`）属存储机制，在内核边界内投影为中立
  `FieldSpec{名字,种类,traits}`，UI 只读 `FieldSpec`，不外泄 `Attr`/`Data`/`Block`。
- 已定 · **Bucket / Block 与 UI 正交**：`core.storage`（Bucket/Block）是存储实现，**UI 不 import、
  不复用、不感知**（UI 里出现 `bucket`/`block`/`body`/`attrs`/`checksum` 即失控）；判据=
  「新开发者要懂 UI 须先学 Bucket/Block」即失败。**已有架构测试**断言 `ui_tools` 不 import
  `feature` / `core.storage` / `core.vault`（`tests/test_architecture.py`）。
- 已定 · **实现归位**：`core/signal/`（Qt-free 通信主干，**已实现**）、`ui_tools/core/`（UI 内核，**已实现**）；
  `EventBus` 已并入 `core/signal`（不再单飞）。
- 已定 · **验收指标**：加领域字段 = 领域一处（+traits），UI **0~1 处**；加标准动作 = 契约一处。
  加字段仍要改 5 个 UI 文件 = 设计失败。
- 已定 · **代理是必然的（内核在变，UI 不变）**：内核随业务 / 数据变，UI 可不变，靠**代理**挡住。
  **两端各一代理**：数据侧 `core.signal.Signal`（包内核、稳定面 + 取实体操作入口）；UI 侧同构代理
  （对接 Qt 信号槽）。**`Bind` 把两个稳定面接起来**——绑定对象因此必然存在。`Signal` **不生成页面**
  （生成页面是 `Facet` 的事）。
- 已定 · **交付单元 = `Facet`**（原 `Page` 生成器含义弃用，`Page` 退为内层页面层）：一个域的整套
  UI 定义（布局 + 部件 + 绑定），由领域对象生成；`Facet(Note)` / `class NoteFacet(Facet)` 同树。
  交付：**直接交给 App（组合根）**，由 App 编译 / 挂载 / 接信号（定义被动，外部发起）。
  `Facet.__init__` **只声明两件事：属性配置 + 绑定**。
- 已定 · **绑定模型**：`bind = Bind(self)`（作用域 = Facet，随生命周期释放）；
  `bind.add(源, 目标)`：源为 UI 信号（**明确到信号**，如 `self.save_btn.clicked`），目标为
  领域 `Signal`（`self.note.favorite`）或本类方法（`self.on_clear`）——UI→内核 与 UI→UI 同写法；
  参数沿 source→target 传；**编译期校验**信号名 / 签名。Qt 物理事件与控件事件由 UI 侧代理
  **统一包成 `Signal`**，作者不碰 `QEvent`。
- 已定 · **总目标（唯一尺度）**：**更便捷、更快、更轻量、更少工作量**。
- 已定 · **`core/signal` = 现有 `EventBus` 升级，不重造**：分两层——**存储事件**（已有
  `ObjectPut`/`ObjectDeleted`）+ **语义信号**（各域声明"会喊哪些话 / 关心哪些话"，
  `emit(名字,数据)` / `subscribe(名字,处理)`）。域间**不 import、只认信号**；听了**重新读**当前状态
  （不缓存假设，解"邻居突变"）；通知非命令；处理器不可重入。`Signal(Note)` = 域的信号 / 动作句柄。
- 已定 · **`Facet` 自包含规则**：主题等内置属性**自带**；布局 / 部件**不自包含**——自己 import、选、
  配好（专属配置在对象自身）再放进去。**`set` = 设形态**（`layout.set(Grid)`）、
  **`add` = 加持有**（`layout.add((1,2),Editor)`），**语义不可混**。产物 = **对象本身直接交 App**
  （`Facet` / 包装对象；**不序列化、不加中间格式，是啥传啥**）。
- 已定 · **Config = JSON**：顶层 `token {…}`（全局外观）+ 具体配置（`note.<…> = 值` / `note.<…> {}`）；
  App 认识所有 `Facet` → **自动生成 JSON schema**（键自动列出、可校验）；**布局参数也在其中**
  （拖布局 = 改文件，不动代码）。
- 已定 · **QML 岛 = 组件化增强**（非完整 UI、非外壳）：画布 / 大关系图等**特定领域增强组件**，
  按普通原子处理——包一层 `QQuickWidget`，对外"配置进 / 信号出"，**接法同普通部件**。
- 已定 · **字段显示属性固定四词**：`label` / `group` / `display` / `editable`；**能按类型推的不写**，
  领域一并挂、UI 照做。
- 已定 · **多页面 = `Facet` 里的 `Page`**：`Page` = 单页（布局 + 部件 + 绑定），是导航目标；
  `Facet` 持多 `Page` 并声明怎么切（`tabs`/`stack`/主从，默认 `tabs`）；**单页域不显式写页**
  （`Facet` 即默认页）；宿主由 App 给、页面懒加载、切换触发 `on_enter`/`on_leave`。
- 已定 · **字段从领域对象分析而来、不写死**；`label`/`group`/`display`/`editable` 只是**可选显示提示槽位**，
  值随领域；**信号**告知"它现在有哪些字段"。
- 进行中 · 分阶段 M0 地基 → M1 外壳 → M2 生成 → M3 扩展；每阶段以 note 打穿闭环。
- 已定 · 本设计**预期与现有 UI 规则冲突**（`ui-boundary.md` / `ui-theme.md` / AGENTS 红线），
  届时以本方向为准定向改规则。

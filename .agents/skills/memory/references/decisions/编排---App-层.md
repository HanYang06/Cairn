<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

## 编排 / App 层（2026-09-19，方向定 + 目录已落地）

- 已定 · **内核 / 领域 / UI 各自独立定义**，之间是**垂直依赖**；由此自然产生的新层是 **App**——**不是再造一个
  "kernel" 层**（此前 `src/kernel.py` 的编排尝试已撤除）。**App = 组合根 / 编排层**：组合内核 + 领域 + UI，并按平台发布。
- 已定 · **发布布局在 `src/app/<平台>/`**：`win` / `linux`（macOS 等顺加）；`src/app/__main__.py`、
  `src/app/win/{main,backend,windows}`。
- 已定 · **`ui_tools` 原地不动（工具箱）；实际 UI 载体在 `src/app/<平台>`**（`win/`）：从内核取数据、用
  `ui_tools` 组装窗口。**平台策略**：Windows 真上；Linux 不要 UI；macOS 暂缓；Android 未来另择 UI 框架
  （Qt 上安卓不划算）。
- 已定 · App 组合落地：`app.Feature`（静态域容器）+ `app.build(vault)`（Session/App/Facet）；领域 UI
  `NoteFacet` 在 **App 侧**（`src/app/facets.py`），**不进 `ui_tools`**。
- 已定 · **目录重定**：`src/core`（底座；含新 `core/conf` 配置 / 常量）/ `src/feature`（领域）/
  `src/ui_tools`（界面工具层，原 `src/ui`）/ `src/app`（应用）。**删除** `src/conf`（并入 `core/conf`）、
  `src/net`、`src/server`。
- 已定 · **撤销 `feature/_shared`**：跨域协作不靠"共享层"，改由 **App 承担编排**；`relation` / `provenance` /
  `signature` 回 `feature/` 顶层（`_shared` 已删）。跨域协作的确切形态待 App 落地时定。
- 已定 · **`core/conf` = 统一配置 / 常量内核化**：把散落的配置 / 常量集中（便于查询 / 管理 / 不发生混乱崩溃）；
  用途仍在明确（`core.py` 已有 `FORMAT_VERSION` / `TOML_NAME` / `VAULT_META_CONTEXT` / `VERSION_WINDOW_MS`）。
- 已定 · UI **不是**统一领域的东西（它只是消费方）；App 才是。`ui_tools` 是**工具箱**，不放入口 / 领域 Facet
  （已删 `ui_tools/app.py`、`ui_tools/note.py`）。
- 待定 · 剩余横向依赖：`note → canvas`（`canvas` 已升格为块域，却被 note 当共享类型用）——
  需定 `canvas` 算共享内容类型还是独立域；跨域编排整体归 App，待落地。

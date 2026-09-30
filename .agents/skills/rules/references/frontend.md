<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 前端工程宪法（`app/`）

决定与理由见 `memory/references/decisions/界面.md`；边界红线见 `ui-boundary.md`。
本文件是**可执行约定**，写第一行前端代码之前先读。

## 零、总原则：能机器判定的才写成规矩

- **判不了的规矩不许写进来**。"组件设计得好不好""命名是否有品味"这类无法判定者，
  写进规则只会变成空话与垃圾桶（作者口径）。
- **每条规矩必须对应一道门禁**。没有门禁的规矩视为不存在；加了规矩就要加门禁。
- **能机器检查的就不要人工检查**：人工检查查不出，而其中绝大多数是可以判定的。

## 一、样式：靠结构消灭，不靠自觉

作者口径：**尽可能少写 CSS**——"写多了只会导致一个结果，就是样式绑定不统一"。
做法是把样式绑进组件，上层只做编排。

1. **样式只从令牌取，禁止字面量**：组件里不许出现颜色 / 圆角 / 间距的字面值，
   一律 `var(--…)`。门禁：`stylelint` 的 `declaration-property-value-disallowed-list`。
2. **令牌是唯一真源**：`config/theme/tokens.json` 是唯一手写处；
   CSS 自定义属性由它生成（`app/scripts/gen-tokens.mjs`），生成物**不许手改**。
   门禁：`pnpm check:tokens` 防漂移。
3. **组件拥有自己的样式**：一个组件的观感写在组件自己那里（样式与组件同处一个目录），
   页面**不写组件内部的样式**。
4. **布局用原语表达意图，不写像素**：页面里的间距只许用布局原语
   （`Stack` / `Cluster` / `Grid` / `Split` 一类，间距取令牌档位），不写 `padding: 12px`。
5. **页面层禁止原生标签与样式属性**（硬规矩，待作者拍板）：
   页面只允许用原子与组合组件，不出现裸 `div` / `span` 与内联样式。
   门禁：自写检查（`app/scripts/check-layout.mjs`）——见 §五。

## 二、类型与契约

1. **契约只有一份事实源**：领域契约（fields / actions / signals）在 **Python 侧声明**，
   生成 TypeScript 与 JSON Schema。**生成器尚未实现**（要有真领域类才有对象可生成）。
2. **前端不许手写契约类型**：生成的 `.ts` 入库，防漂移走 `--check`。
   **手写一份 `interface` 当第二份事实 = 违规**——那正是"两份事实"的起点。
3. **不许 `any`**：`tsc` strict + Biome 双拦。跨边界数据必须有类型。
4. **壳里不写业务**：Rust 只做传输与转发（`kernel_call(method, payload)` 那一形），
   **不解构领域字段**；payload 对壳是不透明对象。

> **在契约生成器落地之前，不许在 `app/` 里手写领域类型**——宁可先不写那一块界面。

## 三、分层与依赖方向

- `app/src/` 内部只有三层：**原子（atom）/ 组合（composite）/ 页面（page）**。
  **增长只在原子与页面**，组合只做编排，不新增层级概念。
- **依赖只能向下**：页面 → 组合 → 原子。原子不许反向依赖页面。
  （**规则先不立**：没有代码的规矩一开就是红的；等三层真的分出来再逐条打开。）
- **单一咽喉**：`@tauri-apps/api` **只许在 `app/src/ipc/` 里 import**——
  前端与内核之间只有一个转发口，别处直接用即绕过契约。
- **不许出现存储词汇**：`block` / `body` / `hub` / `pack` / `carrier` / `catalog` /
  `checksum` / `notedata` 等字眼**不得出现在 `app/src/` 的任何文件里**（含类型名与文件名）。
- 门禁：`dependency-cruiser`（配置在 `app/.dependency-cruiser.mjs`）。
  **已实测会拦**：在页面里 `import { invoke } from "@tauri-apps/api/core"` 会被
  `ipc-single-chokepoint` 拦下并非零退出。

## 四、门禁（全部经一个入口）

**唯一入口：`pnpm check`。** 单条命令跑完下面全部，任一红即非零退出。

| 面 | 脚本 | 判据 |
|---|---|---|
| 类型 | `pnpm check:types` | `tsc --noEmit`，strict |
| lint + 格式 | `pnpm check:lint` | `biome check .`（一个工具、一份配置） |
| 样式令牌 | `pnpm check:css` | `stylelint`，禁字面量样式值 |
| 架构边界 | `pnpm check:arch` | `depcruise`：无环 + Tauri API 单一咽喉 |
| 令牌防漂移 | `pnpm check:tokens` | `gen-tokens.mjs --check` |
| 单测 | `pnpm check:test` | `vitest run` |
| 依赖 | `pnpm install --frozen-lockfile` | 锁文件即事实源 |

**接线位置**（两边都要）：`pre-commit` 的 `frontend` 钩子（`apps: app`，只在前端文件被改动时跑）、
`.github/workflows/ci.yml` 的 `web` job（`pnpm install --frozen-lockfile` → `pnpm check`）。

**门禁与人的关系**：规矩不靠自觉，靠上面这张表；表里没有的规矩不要写在别处。

## 五、待作者拍板 / 待实现

- [ ] **"页面层禁止原生标签与样式属性"**：这条最狠也最有效（它让"边距圆角阴影一个都不写"
  从自觉变成没有位置可写）。**认不认？** 认了我就写 `check-layout.mjs` 并接进门禁。
- [ ] **`jscpd`（重复代码）与 `knip`（未用导出与依赖）**：行业成熟做法，接不接？
- [ ] **契约生成器**：等第一个领域类落地后实现（Python 声明 → TS + JSON Schema + 防漂移）。
- [ ] **组件库与"难件"选型**（编辑器、表格 + 虚拟滚动、画布）：随界面生长再定，
  判据是**优先成品库、不自己造**；采用前核实许可证。

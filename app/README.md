<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Cairn 桌面外壳（`app/`）

**这是界面载体的施工区，功能尚未落地。** 一份 Tauri 工程里装着三样东西：

| 位置 | 是什么 | 技术 |
|---|---|---|
| `src/` | 界面本体 | React + TypeScript（Vite） |
| `src-tauri/` | 壳：窗口、系统能力、IPC 转发口、Python 边车的生命周期 | Rust（Tauri 2） |
| `public/` | Vite 静态目录（不经打包、原样拷进产物） | — |

## 命令

```powershell
pnpm install                    # 装依赖
pnpm tauri dev                  # 开发（首次会编译 Rust，较慢）
pnpm tauri build                # 出安装包
pnpm tauri icon <方形 PNG>       # 重新生成图标集（源图在 ../assets/logo/）
```

## 边界（动手前必读）

- 架构与红线：`.agents/skills/rules/references/ui-boundary.md`（界面侧不许出现存储词汇、
  不许绕过契约、壳里不写业务）。
- 前端工程宪法与门禁：`.agents/skills/rules/references/frontend.md`。
- 决策与理由：`.agents/skills/memory/references/decisions/界面.md`。
- **未定的三项**（契约类型同步、令牌机制、前端宪法）落定之前**不写业务界面**。

## 已知缺口

- 图标已换成 Cairn 的（由 `assets/logo/cairn-icon.png` 生成）。
- Python 内核的**边车**尚未接上：`src-tauri/` 目前只有转发口的位置，没有实现。

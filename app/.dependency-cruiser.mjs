/**
 * SPDX-FileCopyrightText: 2026 HanYang06
 * SPDX-License-Identifier: Apache-2.0
 *
 * 架构门禁：**依赖方向与边界**（见 `rules/references/frontend.md` §三、`ui-boundary.md`）。
 *
 * 两条立意：
 * 1. **单向**：模块图不许有环。
 * 2. **单一咽喉**：`@tauri-apps/api` 只许在 `src/ipc/` 里 import——前端与内核之间
 *    只有一个转发口，别处直接用 Tauri API 等于绕过契约。（`ui-boundary.md`：
 *    壳只做传输与转发，写回只经命令。）
 *
 * 分层规则（原子不得反向依赖页面）等 `src/` 真的分出三层之后再逐条打开——
 * **没有对应代码的规矩先不立**，否则门禁一跑就是红的，规矩会被人绕过去。
 */
export default {
  forbidden: [
    {
      name: "no-circular",
      severity: "error",
      comment: "循环依赖：模块图必须是单向的",
      from: {},
      to: { circular: true },
    },
    {
      name: "ipc-single-chokepoint",
      severity: "error",
      comment:
        "Tauri API 只许在 src/ipc/ 里 import：前端与内核之间只有一个转发口，别处直接用即绕过契约",
      from: { path: "^src", pathNot: "^src/ipc/" },
      // 按**解析后的路径**匹配：pnpm 把依赖放在 `.pnpm/@tauri-apps+api@<版本>/…`，
      // 故既不能写 `node_modules/@tauri-apps/`（那层不存在），也不能只写模块名。
      to: { path: "(^|/)@tauri-apps\\+?[a-z-]*|(^|/)node_modules/@tauri-apps/" },
    },
    {
      name: "not-to-dev-dep",
      severity: "error",
      comment: "运行时不许依赖开发期工具",
      from: { path: "^src" },
      to: { dependencyTypes: ["npm-dev"] },
    },
  ],
  options: {
    // `exclude` 把"谁 import 了它"的边一并藏掉，故**不能排除 `node_modules`**——
    // 实测：排除它之后，探针里的违规 import 根本不出现在图里，规则再对也看不见。
    // 故只排除构建产物，规则一律按**模块名**匹配（pnpm 的真实路径在 `.pnpm/` 下，写路径易碎）。
    exclude: { path: "(^|/)dist/" },
    tsConfig: { fileName: "tsconfig.json" },
  },
};

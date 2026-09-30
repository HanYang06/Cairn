// SPDX-FileCopyrightText: 2026 HanYang06
// SPDX-License-Identifier: Apache-2.0

/**
 * 应用入口：目前只有一页——工作台（卡片板）。
 *
 * 界面只认识"契约 + 投影"，不认识领域内部；跨边界一律经 `ipc/` 唯一咽喉。
 * 口径见 `docs/architecture/by-design.md`（页面结构）与 `ui-theme.md`（观感）。
 */

import { Workbench } from "./pages/workbench/workbench";

function App() {
  return <Workbench />;
}

export default App;

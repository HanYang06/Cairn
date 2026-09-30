// SPDX-FileCopyrightText: 2026 HanYang06
// SPDX-License-Identifier: Apache-2.0

import "./App.css";

/**
 * 外壳占位：脚手架自带的 Tauri + Vite + React 演示已清掉。
 *
 * 这里**故意不写业务**——界面骨架与「从内核取一条真实数据」那条闭环按
 * `.agents/skills/memory/progress.md` 的落地顺序来；组件的规矩（样式绑进组件、
 * 页面层禁原生标签）先在 `rules/references/frontend.md` 定下来再动手。
 */
function App() {
  return (
    <main className="shell">
      <h1>Cairn</h1>
      <p>本地优先的内容寻址对象池 / 笔记·资产·项目工作台</p>
    </main>
  );
}

export default App;

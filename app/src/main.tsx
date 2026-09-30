// SPDX-FileCopyrightText: 2026 HanYang06
// SPDX-License-Identifier: Apache-2.0

import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
// 令牌：生成的 CSS 自定义属性（唯一手写处是 config/theme/tokens.json）。
// 组件只引用 var(--…)，不许写字面值——由 stylelint 拦。
import "./styles/tokens.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

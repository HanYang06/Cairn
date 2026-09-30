// SPDX-FileCopyrightText: 2026 HanYang06
// SPDX-License-Identifier: Apache-2.0

//! 壳的入口：建窗口、装插件、注册转发口。
//!
//! **这一层不写业务**。判断句：换掉界面之后仍然该存在的逻辑，不属于壳。
//! 前端与 Python 内核之间只有一个转发口（`kernel_call(method, payload)` 那一形），
//! 壳负责传输与鉴权，**不解构领域字段**；契约的形状在 Python 侧声明、生成给 TS。
//!
//! 现状：**边车与转发口尚未实现**（脚手架演示命令已清掉）。接法见
//! `.agents/skills/memory/references/decisions/界面.md` §二。

/// 启动桌面外壳。
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .run(tauri::generate_context!())
        .expect("启动 Tauri 应用失败");
}

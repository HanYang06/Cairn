// SPDX-FileCopyrightText: 2026 HanYang06
// SPDX-License-Identifier: Apache-2.0

/**
 * 前端与内核之间的**唯一转发口**。
 *
 * 规矩：`@tauri-apps/api` 只许在这个目录里 import（由 `.dependency-cruiser.mjs` 的
 * `ipc-single-chokepoint` 拦）。别处一律经这里暴露的窄面调用——这样"写回只经命令"
 * 与"壳只做传输"两条边界才落得下来。
 *
 * **尚未实现**：Python 内核的边车与 stdio 分帧协议接上之后，这里才长出真正的面。
 * 在那之前**不要**凭空定义方法——没有调用方的转发口就是脚手架。
 */
export {};

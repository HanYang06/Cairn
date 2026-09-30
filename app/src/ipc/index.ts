// SPDX-FileCopyrightText: 2026 HanYang06
// SPDX-License-Identifier: Apache-2.0

/**
 * 前端与内核 / 壳之间的**唯一转发口**。
 *
 * 规矩：`@tauri-apps/api` 只许在这个目录里 import（由 `.dependency-cruiser.mjs` 的
 * `ipc-single-chokepoint` 拦）。别处一律经这里暴露的窄面调用——这样"写回只经命令"
 * 与"壳只做传输"两条边界才落得下来。
 *
 * **尚未实现**：Python 内核的边车与 stdio 分帧协议接上之后，这里才长出真正的面。
 * 在那之前只放**已经有调用方**的几件：系统字体枚举、卡片板布局的读写。
 */

/** 是否跑在 Tauri 壳里（浏览器与测试环境为 false）。 */
export function inShell(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

async function invoke<Result>(name: string, args?: Record<string, unknown>): Promise<Result> {
  const { invoke: call } = await import("@tauri-apps/api/core");
  return call<Result>(name, args);
}

/**
 * 列出**用户系统里已安装的字体**。
 *
 * 只报告"装了什么"——**不提供、不复制、不缓存字体文件**
 * （`docs/architecture/ui-theme.md` §3.8 的红线）。没有壳时返回空表，界面自行降级。
 *
 * 壳返回的是一张**面孔表**（同族多面孔会重复出现，字段见
 * `app/src-tauri/src/system_fonts.rs`）；前端只要族名，故在这里收口——
 * 跨边界的形状以后有变化，只改这一处。
 */
export async function listSystemFonts(): Promise<string[]> {
  if (!inShell()) return [];
  try {
    const faces = await invoke<{ name?: unknown }[]>("list_system_fonts");
    const names = faces
      .map((face) => (typeof face?.name === "string" ? face.name : null))
      .filter((name): name is string => name !== null);
    return [...new Set(names)].sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
  } catch {
    // 壳里还没接这个命令：当作"系统没有额外字体"，不阻塞界面
    return [];
  }
}

/**
 * 卡片板布局的读写。
 *
 * 口径（`by-design.md` §8.5）：布局是**用户数据**，有自己的文件——
 * **不进库、也不走 `conf()`**。命令名与形状先定下来；壳尚未提供时落到本地存储，
 * 届时只换实现，调用方不动。
 */
const BOARD_KEY = "cairn.board.layout";

export async function readBoardLayout(): Promise<string | null> {
  if (inShell()) {
    try {
      return await invoke<string | null>("read_board_layout");
    } catch {
      return null;
    }
  }
  try {
    return globalThis.localStorage?.getItem(BOARD_KEY) ?? null;
  } catch {
    return null;
  }
}

export async function writeBoardLayout(payload: string): Promise<void> {
  if (inShell()) {
    try {
      await invoke<void>("write_board_layout", { payload });
    } catch {
      // 写不出去不影响本次运行：布局是视图偏好，不是数据源
    }
    return;
  }
  try {
    globalThis.localStorage?.setItem(BOARD_KEY, payload);
  } catch {
    // 同上
  }
}

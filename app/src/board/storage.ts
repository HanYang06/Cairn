// SPDX-FileCopyrightText: 2026 HanYang06
// SPDX-License-Identifier: Apache-2.0

/**
 * 卡片板的读写与一次调整的认领。
 *
 * 落盘的口径（`by-design.md` §8.5）：布局是**用户数据**，只有整数与字符串；
 * **不进库、也不走 `conf()`**，走自己的文件（当前阶段落到 IPC 咽喉的读写命令上）。
 *
 * 坏掉的布局**不报错**：它是视图偏好，不是数据源——读不动就回到默认板。
 */

import type { BoardCard } from "./cards";
import { DEFAULT_BOARD } from "./cards";
import { GRID_COLS, GRID_ROWS, settle } from "./layout";

interface StoredBoard {
  readonly version: number;
  readonly grid: { readonly cols: number; readonly rows: number };
  readonly cards: readonly BoardCard[];
}

export const BOARD_FORMAT_VERSION = 1;

/** 序列化：只有整数与字符串（便于人看、便于将来换实现）。 */
export function serializeBoard(cards: readonly BoardCard[]): string {
  const payload: StoredBoard = {
    version: BOARD_FORMAT_VERSION,
    grid: { cols: GRID_COLS, rows: GRID_ROWS },
    cards: cards.map((c) => ({ id: c.id, x: c.x, y: c.y, w: c.w, h: c.h, kind: c.kind })),
  };
  return JSON.stringify(payload, null, 2);
}

const isInt = (value: unknown): value is number =>
  typeof value === "number" && Number.isInteger(value);

/** 解析：任何一处不合法就整份丢掉，回到默认板。 */
export function parseBoard(raw: string | null): BoardCard[] {
  if (!raw) return [...DEFAULT_BOARD];
  try {
    const data = JSON.parse(raw) as Partial<StoredBoard>;
    if (data.version !== BOARD_FORMAT_VERSION || !Array.isArray(data.cards)) {
      return [...DEFAULT_BOARD];
    }
    const cards: BoardCard[] = [];
    for (const item of data.cards) {
      const c = item as Partial<BoardCard>;
      if (
        typeof c.id !== "string" ||
        typeof c.kind !== "string" ||
        !isInt(c.x) ||
        !isInt(c.y) ||
        !isInt(c.w) ||
        !isInt(c.h)
      ) {
        return [...DEFAULT_BOARD];
      }
      cards.push({ id: c.id, kind: c.kind, x: c.x, y: c.y, w: c.w, h: c.h });
    }
    return cards.length > 0 ? cards : [...DEFAULT_BOARD];
  } catch {
    return [...DEFAULT_BOARD];
  }
}

/**
 * 认领一次调整：**被拖的那张卡先入场**，其余按原顺序跟在后面。
 *
 * 先后次序在这里是有意义的——`settle` 按顺序保留先到的、把后到的顺延，
 * 故"谁先入场"决定谁的原位置不被挤走。用户正在拖的那张卡优先。
 */
export function settleBoard(cards: readonly BoardCard[], movedId: string): BoardCard[] {
  const moved = cards.find((c) => c.id === movedId);
  if (!moved) return [...cards];
  const rest = cards.filter((c) => c.id !== movedId);
  return settle([moved, ...rest]) as BoardCard[];
}

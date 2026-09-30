// SPDX-FileCopyrightText: 2026 HanYang06
// SPDX-License-Identifier: Apache-2.0

/**
 * 卡片板的布局引擎（纯函数，无 DOM）。
 *
 * 口径见 `docs/architecture/by-design.md` §8：**位置与大小都是整数格**，
 * 指针只负责给"原始比例"，落盘一律取整。四条防碎化硬约束住在这一层：
 * 吸附（整数格）· 最小尺寸 1×1 · 自动补位 · 禁止重叠。
 *
 * 无领域词汇：这里的 `CardSpot` 只是"一块占位"，不认识笔记 / 项目 / 标签。
 */

/** 网格的列数与行数（布局机制自身的旋钮；将来走 `conf()`，见 by-design.md §8.5）。 */
export const GRID_COLS = 6;
export const GRID_ROWS = 5;

/** 最小尺寸：一格。比一格更小的卡会让网格失去意义。 */
export const MIN_W = 1;
export const MIN_H = 1;

/** 一块占位：`x`/`y` 从 1 起算，`w`/`h` 是跨几格。 */
export interface CardSpot {
  readonly id: string;
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
}

const clamp = (v: number, lo: number, hi: number): number =>
  Math.max(lo, Math.min(hi, Math.trunc(v)));

/** 把任意尺寸夹进"至少一格、且不越出网格"。 */
export function clampSize(
  spot: Pick<CardSpot, "x" | "y" | "w" | "h">,
  cols = GRID_COLS,
  rows = GRID_ROWS,
): { w: number; h: number } {
  return {
    w: clamp(spot.w, MIN_W, cols - spot.x + 1),
    h: clamp(spot.h, MIN_H, rows - spot.y + 1),
  };
}

/** 两块占位是否重叠（半开区间：贴着不算重叠，重叠一格就算）。 */
export function overlaps(a: CardSpot, b: CardSpot): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

/** 给定一批占位，返回"已被占用的格"的键集合。 */
export function occupiedKeys(spots: readonly CardSpot[]): Set<string> {
  const taken = new Set<string>();
  for (const s of spots) {
    for (let dx = 0; dx < s.w; dx++) {
      for (let dy = 0; dy < s.h; dy++) {
        taken.add(`${s.x + dx},${s.y + dy}`);
      }
    }
  }
  return taken;
}

/**
 * 找第一个能放下 `w × h` 的位置（按行扫描）。
 *
 * 用于新建卡片：**禁止重叠**这条约束由此在"摆放"入口就成立，
 * 不需要等到渲染时才去救。
 */
export function firstFreeSpot(
  spots: readonly CardSpot[],
  w: number,
  h: number,
  cols = GRID_COLS,
  rows = GRID_ROWS,
): { x: number; y: number } | null {
  const taken = occupiedKeys(spots);
  const fits = (x: number, y: number): boolean => {
    if (x + w - 1 > cols || y + h - 1 > rows) return false;
    for (let dx = 0; dx < w; dx++) {
      for (let dy = 0; dy < h; dy++) {
        if (taken.has(`${x + dx},${y + dy}`)) return false;
      }
    }
    return true;
  };
  for (let y = 1; y + h - 1 <= rows; y++) {
    for (let x = 1; x + w - 1 <= cols; x++) {
      if (fits(x, y)) return { x, y };
    }
  }
  return null;
}

/** 把一批占位里的重叠消掉：按 id 顺序保留先到的，后到的顺延到下一个空位。 */
export function resolveCollisions(
  spots: readonly CardSpot[],
  cols = GRID_COLS,
  rows = GRID_ROWS,
): CardSpot[] {
  const out: CardSpot[] = [];
  for (const spot of spots) {
    const size = clampSize(spot, cols, rows);
    // 位置与尺寸都要落回板内：越界的卡不能被"放到板外就算数"
    const wanted: CardSpot = {
      ...spot,
      ...size,
      x: clamp(spot.x, 1, cols - size.w + 1),
      y: clamp(spot.y, 1, rows - size.h + 1),
    };
    if (!out.some((other) => overlaps(other, wanted))) {
      out.push(wanted);
      continue;
    }
    const free = firstFreeSpot(out, wanted.w, wanted.h, cols, rows);
    // 放不下就留在原处（宁可暂时压着，也不把卡丢出板外）
    out.push(free ? { ...wanted, ...free } : wanted);
  }
  return out;
}

/**
 * 自动补位：把卡尽量往上提。
 *
 * 这是"卡片缩小或移走后，后方的卡补位"（安卓主屏的行为）——没有它，
 * 用户每次调整都会亲手制造空洞（by-design.md §8.3 第 3 条）。
 *
 * 两条纪律（都是被用例逼出来的）：
 * ① **顺序**：先摆"原本更靠上"的卡，再摆下面的——否则提上来的卡会被后面的卡压住；
 * ② **不压别人**：抬升时不只躲已经摆好的，也要躲**还没摆的**（排在后面的卡占的位置），
 *    实在提不上去就留在原位。**不许为了补位而制造重叠**。
 */
export function compactUp(
  spots: readonly CardSpot[],
  cols = GRID_COLS,
  rows = GRID_ROWS,
): CardSpot[] {
  const sized: CardSpot[] = spots.map((spot) => ({ ...spot, ...clampSize(spot, cols, rows) }));
  // 先摆"原本更靠上"的卡；同高按原顺序（稳定）
  const order = sized
    .map((spot, index) => ({ spot, index }))
    .sort((a, b) => a.spot.y - b.spot.y || a.index - b.index);

  const placed: CardSpot[] = [];
  const pending = [...sized];

  for (const { spot } of order) {
    const at = pending.indexOf(spot);
    if (at >= 0) pending.splice(at, 1);

    let y = spot.y;
    while (y > 1) {
      const lifted: CardSpot = { ...spot, y: y - 1 };
      const blocked =
        placed.some((other) => overlaps(other, lifted)) ||
        pending.some((other) => overlaps(other, lifted));
      if (blocked) break;
      y -= 1;
    }
    placed.push({ ...spot, y });
  }
  return placed;
}

/** 端到端的一次调整：夹尺寸 → 消重叠 → 补位。 */
export function settle(spots: readonly CardSpot[], cols = GRID_COLS, rows = GRID_ROWS): CardSpot[] {
  return compactUp(resolveCollisions(spots, cols, rows), cols, rows);
}

/** 把占位翻译成 CSS Grid 的定位（行 / 列从 1 起算，与网格线号一致）。 */
export function toGridPlacement(spot: CardSpot): {
  gridColumn: string;
  gridRow: string;
} {
  return {
    gridColumn: `${spot.x} / span ${spot.w}`,
    gridRow: `${spot.y} / span ${spot.h}`,
  };
}

/**
 * 指针位移 → 整格尺寸（**吸附**）。
 *
 * 指针给的是连续比例（`rawW`/`rawH`），这里只做两件事：**就近取整**与**夹进合法范围**。
 */
export function snapSize(
  base: Pick<CardSpot, "x" | "y">,
  rawW: number,
  rawH: number,
  cols = GRID_COLS,
  rows = GRID_ROWS,
): { w: number; h: number } {
  return clampSize({ ...base, w: Math.round(rawW), h: Math.round(rawH) }, cols, rows);
}

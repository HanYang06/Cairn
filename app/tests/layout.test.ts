// SPDX-FileCopyrightText: 2026 HanYang06
// SPDX-License-Identifier: Apache-2.0

/**
 * 布局引擎的契约测试。
 *
 * 这一组是**四条防碎化硬约束**的机器挡板（`by-design.md` §8.3）：
 * 吸附（整数格）· 最小尺寸 1×1 · 自动补位 · 禁止重叠。
 * 它们坏了不会报错，只会让板子慢慢碎掉——所以必须由用例守住。
 */

import { describe, expect, it } from "vitest";

import {
  type CardSpot,
  clampSize,
  compactUp,
  firstFreeSpot,
  GRID_COLS,
  GRID_ROWS,
  occupiedKeys,
  overlaps,
  resolveCollisions,
  settle,
  snapSize,
  toGridPlacement,
} from "../src/board/layout";

const spot = (id: string, x: number, y: number, w: number, h: number): CardSpot => ({
  id,
  x,
  y,
  w,
  h,
});

/** 任意两块都不许重叠——这是板子的不变量。 */
const expectNoOverlap = (spots: readonly CardSpot[]): void => {
  for (let i = 0; i < spots.length; i++) {
    for (let j = i + 1; j < spots.length; j++) {
      const a = spots[i];
      const b = spots[j];
      if (a && b) expect(overlaps(a, b)).toBe(false);
    }
  }
};

describe("尺寸夹取（最小 1×1、不越出网格）", () => {
  it("小于一格会被抬到一格", () => {
    expect(clampSize({ x: 2, y: 2, w: 0, h: -3 })).toEqual({ w: 1, h: 1 });
  });

  it("越出右边界与下边界会被压回", () => {
    expect(clampSize({ x: 5, y: 4, w: 99, h: 99 }, 6, 5)).toEqual({ w: 2, h: 2 });
  });

  it("非整数会被截断（吸附：板上只有整数格）", () => {
    expect(clampSize({ x: 1, y: 1, w: 2.9, h: 3.7 })).toEqual({ w: 2, h: 3 });
  });
});

describe("重叠判定", () => {
  it("贴边不算重叠", () => {
    expect(overlaps(spot("a", 1, 1, 2, 2), spot("b", 3, 1, 2, 2))).toBe(false);
    expect(overlaps(spot("a", 1, 1, 2, 2), spot("b", 1, 3, 2, 2))).toBe(false);
  });

  it("压住一格就算重叠", () => {
    expect(overlaps(spot("a", 1, 1, 3, 3), spot("b", 3, 3, 2, 2))).toBe(true);
  });
});

describe("占格表", () => {
  it("按面积展开成格键", () => {
    expect(occupiedKeys([spot("a", 1, 1, 2, 2)]).size).toBe(4);
  });
});

describe("新建时找空位（禁止重叠在入口就成立）", () => {
  it("空板落在左上角", () => {
    expect(firstFreeSpot([], 2, 2)).toEqual({ x: 1, y: 1 });
  });

  it("避开已占的格", () => {
    expect(firstFreeSpot([spot("a", 1, 1, 2, 2)], 2, 2)).toEqual({ x: 3, y: 1 });
  });

  it("整行占满则落到下一行", () => {
    const row = [spot("a", 1, 1, GRID_COLS, 1)];
    expect(firstFreeSpot(row, 1, 1)).toEqual({ x: 1, y: 2 });
  });

  it("放不下时返回空（宁可报告，不要静默压上去）", () => {
    const full = [spot("a", 1, 1, GRID_COLS, GRID_ROWS)];
    expect(firstFreeSpot(full, 1, 1)).toBeNull();
  });
});

describe("消重叠", () => {
  it("后到的顺延，全部不重叠", () => {
    const out = resolveCollisions([spot("a", 1, 1, 3, 3), spot("b", 1, 1, 2, 2)]);
    expectNoOverlap(out);
    expect(out.find((s) => s.id === "a")).toMatchObject({ x: 1, y: 1, w: 3, h: 3 });
  });

  it("尺寸越界也一并夹住", () => {
    const out = resolveCollisions([spot("a", 6, 5, 9, 9)]);
    expect(out[0]).toMatchObject({ x: 6, y: 5, w: 1, h: 1 });
  });
});

describe("自动补位", () => {
  it("下方的卡会补上被让出的空间", () => {
    const out = compactUp([spot("a", 1, 3, 2, 1)]);
    expect(out[0]).toMatchObject({ y: 1 });
  });

  it("被别的卡挡住时停住，不穿模", () => {
    const out = compactUp([spot("a", 1, 1, 2, 1), spot("b", 1, 3, 2, 1)]);
    expect(out.find((s) => s.id === "b")).toMatchObject({ y: 2 });
    expectNoOverlap(out);
  });
});

describe("一次调整的端到端", () => {
  it("settle 之后：不重叠、贴着顶、尺寸合法", () => {
    const out = settle([spot("a", 1, 3, 2, 2), spot("b", 1, 1, 2, 2), spot("c", 99, 99, 99, 99)]);
    expectNoOverlap(out);
    for (const s of out) {
      expect(s.w).toBeGreaterThanOrEqual(1);
      expect(s.h).toBeGreaterThanOrEqual(1);
      expect(s.x + s.w - 1).toBeLessThanOrEqual(GRID_COLS);
      expect(s.y + s.h - 1).toBeLessThanOrEqual(GRID_ROWS);
    }
  });

  it("反复 settle 应当收敛（幂等）", () => {
    const once = settle([spot("a", 1, 2, 3, 2), spot("b", 2, 3, 2, 2)]);
    const twice = settle(once);
    expect(twice).toEqual(once);
  });
});

describe("吸附：指针比例 → 整格", () => {
  it("就近取整", () => {
    expect(snapSize({ x: 1, y: 1 }, 2.4, 1.5)).toEqual({ w: 2, h: 2 });
    expect(snapSize({ x: 1, y: 1 }, 2.6, 3.2)).toEqual({ w: 3, h: 3 });
  });

  it("拖过头也不会越出网格", () => {
    expect(snapSize({ x: 4, y: 4 }, 99, 99)).toEqual({ w: 3, h: 2 });
  });
});

describe("翻译成 CSS Grid 定位", () => {
  it("行列都从 1 起算，与网格线号一致", () => {
    expect(toGridPlacement(spot("a", 2, 3, 4, 2))).toEqual({
      gridColumn: "2 / span 4",
      gridRow: "3 / span 2",
    });
  });
});

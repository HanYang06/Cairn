// SPDX-FileCopyrightText: 2026 HanYang06
// SPDX-License-Identifier: Apache-2.0

/**
 * 布局落盘的契约测试（`by-design.md` §8.5）。
 *
 * 两条要点：
 * ① **坏掉的布局不报错**——它是视图偏好，不是数据源，读不动就回到默认板；
 * ② **只有整数与字符串**落盘，且"被拖的那张卡优先入场"。
 */

import { describe, expect, it } from "vitest";

import { type BoardCard, DEFAULT_BOARD, isDefaultBoard } from "../src/board/cards";
import { overlaps } from "../src/board/layout";
import {
  BOARD_FORMAT_VERSION,
  parseBoard,
  serializeBoard,
  settleBoard,
} from "../src/board/storage";

const card = (
  id: string,
  x: number,
  y: number,
  w: number,
  h: number,
  kind = "笔记",
): BoardCard => ({
  id,
  x,
  y,
  w,
  h,
  kind,
});

describe("序列化", () => {
  it("带上版本号与网格尺寸", () => {
    const data = JSON.parse(serializeBoard(DEFAULT_BOARD)) as Record<string, unknown>;
    expect(data.version).toBe(BOARD_FORMAT_VERSION);
    expect(data.grid).toEqual({ cols: 6, rows: 5 });
  });

  it("落盘的全是整数与字符串（没有像素、没有小数）", () => {
    const data = JSON.parse(serializeBoard([card("a", 1, 1, 2, 3)])) as {
      cards: Record<string, unknown>[];
    };
    for (const value of Object.values(data.cards[0] ?? {})) {
      expect(["string", "number"]).toContain(typeof value);
    }
    for (const key of ["x", "y", "w", "h"]) {
      expect(Number.isInteger(data.cards[0]?.[key])).toBe(true);
    }
  });
});

describe("解析：坏数据一律回到默认板", () => {
  it("空值", () => {
    expect(parseBoard(null)).toEqual([...DEFAULT_BOARD]);
  });

  it("不是 JSON", () => {
    expect(parseBoard("{ 这不是 json")).toEqual([...DEFAULT_BOARD]);
  });

  it("版本号不认识", () => {
    expect(parseBoard(JSON.stringify({ version: 99, cards: [] }))).toEqual([...DEFAULT_BOARD]);
  });

  it("字段类型不对（小数 / 字符串坐标）", () => {
    const bad = JSON.stringify({
      version: BOARD_FORMAT_VERSION,
      grid: { cols: 6, rows: 5 },
      cards: [{ id: "a", kind: "笔记", x: 1.5, y: 1, w: 2, h: 2 }],
    });
    expect(parseBoard(bad)).toEqual([...DEFAULT_BOARD]);
  });

  it("好数据原样读回", () => {
    const cards = [card("a", 2, 2, 3, 2, "待办")];
    expect(parseBoard(serializeBoard(cards))).toEqual(cards);
  });
});

describe("认领一次调整", () => {
  it("被拖的那张卡优先入场，其余顺延，且不重叠", () => {
    const cards = [card("a", 1, 1, 3, 3), card("b", 1, 1, 2, 2)];
    const out = settleBoard(cards, "b");
    expect(out.find((c) => c.id === "b")).toMatchObject({ x: 1, y: 1 });
    for (let i = 0; i < out.length; i++) {
      for (let j = i + 1; j < out.length; j++) {
        const left = out[i];
        const right = out[j];
        if (left && right) expect(overlaps(left, right)).toBe(false);
      }
    }
  });

  it("传入不存在的 id 时原样返回", () => {
    const cards = [card("a", 1, 1, 1, 1)];
    expect(settleBoard(cards, "zzz")).toEqual(cards);
  });
});

describe("与默认板比对", () => {
  it("默认板自己算默认", () => {
    expect(isDefaultBoard([...DEFAULT_BOARD])).toBe(true);
  });

  it("挪动一格就不算默认", () => {
    const moved = DEFAULT_BOARD.map((c, i) => (i === 0 ? { ...c, x: c.x + 1 } : c));
    expect(isDefaultBoard(moved)).toBe(false);
  });
});

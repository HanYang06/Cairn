// SPDX-FileCopyrightText: 2026 HanYang06
// SPDX-License-Identifier: Apache-2.0

/**
 * 字体替换机制的契约测试（`ui-theme.md` §3.8）。
 *
 * 重点是两件容易悄悄坏掉的事：
 * ① `DEFAULT_STACK` 与令牌源不许分叉（**防漂移**：令牌改了这里没改，兜底就成了假的）；
 * ② 没有 DOM 时不许炸（测试与 Node 侧都要能安全调用）。
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
  applyFontOverrides,
  DEFAULT_STACK,
  FONT_ROLES,
  fontAvailable,
  isMonospace,
  normalizeFontName,
} from "../src/board/fonts";

const APP = dirname(dirname(fileURLToPath(import.meta.url)));
const REPO = dirname(APP);

describe("默认字体链与令牌源一致", () => {
  const tokens = JSON.parse(readFileSync(join(REPO, "config", "theme", "tokens.json"), "utf8")) as {
    fontFamily: Record<string, string>;
  };

  it("三层角色都在令牌里有值", () => {
    for (const role of FONT_ROLES) {
      expect(tokens.fontFamily[role], `令牌缺 fontFamily.${role}`).toBeTruthy();
    }
  });

  it("样式里的三层字体都带 `-user` 兜底（否则用户覆盖会顶掉默认链）", () => {
    const css = readFileSync(join(APP, "src", "styles", "global.css"), "utf8");
    expect(css).toContain("var(--font-sans-user, var(--font-sans))");
  });
});

describe("字体名归一化", () => {
  it("去空格与引号", () => {
    expect(normalizeFontName('  "Noto Sans CJK SC" ')).toBe("Noto Sans CJK SC");
    expect(normalizeFontName("'Sarasa Mono SC'")).toBe("Sarasa Mono SC");
  });

  it("空串视为未设置", () => {
    expect(normalizeFontName("   ")).toBeNull();
    expect(normalizeFontName('""')).toBeNull();
  });
});

describe("没有 DOM 时的安全降级", () => {
  it("可用性判定返回 false，而不是抛错", () => {
    expect(fontAvailable("Noto Sans CJK SC")).toBe(false);
    expect(isMonospace("Sarasa Mono SC")).toBe(false);
  });

  it("传 null 根节点时不抛错", () => {
    expect(() => applyFontOverrides({ sans: "Any" }, null)).not.toThrow();
  });
});

describe("覆盖不产生自引用（兜底必须是内建链）", () => {
  it("没有根节点时是空操作；有根节点时写成 用户字体 + 内建链", () => {
    const written: Record<string, string> = {};
    const removed: string[] = [];
    const fakeRoot = {
      style: {
        setProperty: (k: string, v: string) => {
          written[k] = v;
        },
        removeProperty: (k: string) => {
          removed.push(k);
        },
      },
    } as unknown as HTMLElement;

    applyFontOverrides({ mono: "Maple Mono" }, fakeRoot);
    // 只写独立的一层，不动令牌本身——兜底交给 CSS 的 `var(--font-mono-user, var(--font-mono))`
    expect(written["--font-mono-user"]).toBe('"Maple Mono"');
    expect(written["--font-mono"]).toBeUndefined();
    // 未设置的两层交还默认
    expect(removed).toContain("--font-sans-user");
    expect(removed).toContain("--font-read-user");
  });
});

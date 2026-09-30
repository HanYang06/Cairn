// SPDX-FileCopyrightText: 2026 HanYang06
// SPDX-License-Identifier: Apache-2.0

/**
 * 令牌契约：声明与生成物必须对得上。
 *
 * 这一组用例是"防漂移"的另一半——`gen-tokens.mjs --check` 保证**文件内容**一致，
 * 这里保证**内容本身有该有的东西**（词表没被删空、两套配色都在）。
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const APP = dirname(dirname(fileURLToPath(import.meta.url)));
const REPO = dirname(APP);

const tokens = JSON.parse(
  readFileSync(join(REPO, "config", "theme", "tokens.json"), "utf8"),
) as Record<string, Record<string, unknown>>;
const css = readFileSync(join(APP, "src", "styles", "tokens.css"), "utf8");

describe("令牌声明", () => {
  it("五族齐全：色 / 间距 / 圆角 / 字 / 动效", () => {
    for (const family of ["color", "spacing", "radius", "fontSize", "duration"]) {
      expect(Object.keys(tokens[family] ?? {}).length).toBeGreaterThan(0);
    }
  });

  it("深浅两套配色的键完全一致（缺一个就会切出半套主题）", () => {
    const light = Object.keys(tokens.color.light as object).sort();
    const dark = Object.keys(tokens.color.dark as object).sort();
    expect(dark).toEqual(light);
  });
});

describe("生成的 CSS", () => {
  it("深浅两套都在：一套进 :root，另一套进 prefers-color-scheme", () => {
    expect(css).toContain("@media (prefers-color-scheme: dark)");
    // 浅色是默认值：暖纸底（不是纯白，见 ui-theme.md §3.1 的亮度理由）
    expect(css).toContain(`--color-bg: ${tokens.color.light.bg}`);
    expect(css).toContain(`--color-bg: ${tokens.color.dark.bg}`);
    expect(css).toContain(`--color-accent: ${tokens.color.light.accent}`);
    expect(css).toContain(`--color-accent: ${tokens.color.dark.accent}`);
  });

  it("浅色底不是纯白：暖纸底比纯白暗，但不至于显黄", () => {
    const bg = String(tokens.color.light.bg).toUpperCase();
    expect(bg).not.toBe("#FFFFFF");
    const lum = (hex: string) => {
      const c = [1, 3, 5].map((i) => Number.parseInt(hex.slice(i, i + 2), 16) / 255);
      const f = (s: number) => (s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4);
      return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
    };
    expect(lum(bg)).toBeLessThan(1);
    expect(lum(bg)).toBeGreaterThan(0.85);
  });

  it("默认档不带后缀，其余档带名字", () => {
    expect(css).toContain("--radius:");
    expect(css).toContain("--radius-sm:");
    expect(css).toContain("--space-md:");
  });

  it("正文与背景的对比度过 AA（4.5）", () => {
    const lum = (hex: string) => {
      const c = [1, 3, 5].map((i) => Number.parseInt(hex.slice(i, i + 2), 16) / 255);
      const f = (s: number) => (s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4);
      return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
    };
    const ratio = (a: string, b: string) => {
      const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
      return (hi + 0.05) / (lo + 0.05);
    };
    for (const mode of ["light", "dark"] as const) {
      const c = tokens.color[mode] as Record<string, string>;
      expect(ratio(c.text, c.bg)).toBeGreaterThanOrEqual(4.5);
      expect(ratio(c.accent, c.bg)).toBeGreaterThanOrEqual(4.5);
    }
  });
});

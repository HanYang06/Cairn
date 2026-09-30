// SPDX-FileCopyrightText: 2026 HanYang06
// SPDX-License-Identifier: Apache-2.0

/**
 * 令牌引用的契约测试。
 *
 * 这一条补的是一个**以前只能靠人眼发现**的漏洞：组件里写了 `var(--x)`，
 * 而 `--x` 根本不存在——样式静默失效，界面只是"看着不对"。
 * 门禁（stylelint）只保证"值必须是 var(--…)"，不保证"这个 var 存在"。
 *
 * 顺带守住另一头：**令牌不许只在生成物里有、声明里没有**（生成物是单向投影）。
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const APP = dirname(dirname(fileURLToPath(import.meta.url)));
const REPO = dirname(APP);
const SRC = join(APP, "src");

/** 递归收集源文件。 */
function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

const cssFiles = walk(SRC).filter((f) => f.endsWith(".css") && !f.endsWith("tokens.css"));
const tsFiles = walk(SRC).filter((f) => f.endsWith(".ts") || f.endsWith(".tsx"));
const tokenCss = readFileSync(join(SRC, "styles", "tokens.css"), "utf8");

/** 生成物里声明的令牌名（去掉 `--` 前缀）。 */
const declared = new Set([...tokenCss.matchAll(/--([a-zA-Z0-9-]+)\s*:/g)].map((m) => m[1] ?? ""));

/**
 * 运行时注入的变量：**不是令牌，但名字必须受控**。
 *
 * - `--font-<角色>-user`：用户覆盖层（`ui-theme.md` §3.8），由 `applyFontOverrides` 写入；
 * - `--board-cols` / `--board-rows`：卡片板的网格尺寸（`by-design.md` §8.1），
 *   由 `composites/board` 的 style 属性注入——**受控**在这里的意思是：
 *   只许这几个名字，别的一律要么进令牌、要么报错。
 */
const RUNTIME_VARS = new Set(["board-cols", "board-rows"]);

const isRuntimeVar = (name: string): boolean => name.endsWith("-user") || RUNTIME_VARS.has(name);

/** 某份文件里用到的 `var(--x)`。 */
function usedIn(files: readonly string[]): Map<string, string[]> {
  const used = new Map<string, string[]>();
  for (const file of files) {
    const text = readFileSync(file, "utf8");
    for (const match of text.matchAll(/var\(--([a-z][a-z0-9-]*)(?=[,)] ?)/g)) {
      const name = match[1] ?? "";
      if (isRuntimeVar(name)) continue;
      const where = used.get(name) ?? [];
      where.push(relative(REPO, file));
      used.set(name, where);
    }
  }
  return used;
}

describe("令牌引用", () => {
  it("组件样式里用到的每个令牌都已声明", () => {
    const missing: string[] = [];
    for (const [name, where] of usedIn(cssFiles)) {
      if (!declared.has(name)) missing.push(`--${name}（${[...new Set(where)].join(", ")}）`);
    }
    expect(missing).toEqual([]);
  });

  it("组件代码里用到的每个令牌都已声明", () => {
    const missing: string[] = [];
    for (const [name, where] of usedIn(tsFiles)) {
      if (!declared.has(name)) missing.push(`--${name}（${[...new Set(where)].join(", ")}）`);
    }
    expect(missing).toEqual([]);
  });

  it("令牌生成物不为空（防止生成器被改崩后静默通过）", () => {
    expect(declared.size).toBeGreaterThan(30);
  });
});

// SPDX-FileCopyrightText: 2026 HanYang06
// SPDX-License-Identifier: Apache-2.0

/*
 * 令牌生成器：把 `config/theme/tokens.json`（唯一手写处）投影成 CSS 自定义属性。
 *
 * 与 `scripts/docgen.py` 同款：**能算的就不写**，生成物入库 + `--check` 防漂移。
 * 分工是死的——组件只引用 `var(--…)`，不许写字面值（由 stylelint 拦）。
 *
 * 用法：
 *   node scripts/gen-tokens.mjs            # 生成
 *   node scripts/gen-tokens.mjs --check    # 防漂移门禁（不一致即非零退出）
 */

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const APP = dirname(dirname(fileURLToPath(import.meta.url)));
const REPO = dirname(APP);
const SOURCE = join(REPO, "config", "theme", "tokens.json");
const TARGET = join(APP, "src", "styles", "tokens.css");

const HEAD = `/* SPDX-FileCopyrightText: 2026 HanYang06 */
/* SPDX-License-Identifier: Apache-2.0 */

/*
 * 本文件由 \`app/scripts/gen-tokens.mjs\` 生成，**不要手改**。
 * 唯一手写处是 \`config/theme/tokens.json\`；改那里之后重新生成：
 *   pnpm -C app gen:tokens
 */
`;

/** 取一份标量表并渲染成若干 `--前缀-名: 值;` 行。 */
function scale(prefix, table) {
  return Object.entries(table).map(([name, value]) => {
    const suffix = name === "DEFAULT" ? "" : `-${name}`;
    return `  --${prefix}${suffix}: ${value};`;
  });
}

/** 由令牌声明渲染整份 CSS。 */
function render(tokens) {
  const light = scale("color", tokens.color.light);
  const dark = scale("color", tokens.color.dark);
  const blocks = [
    ":root {",
    ...light,
    "",
    ...scale("space", tokens.spacing),
    "",
    ...scale("radius", tokens.radius),
    "",
    ...scale("font", { ...tokens.fontFamily, ...tokens.fontSize }),
    "",
    ...scale("leading", tokens.lineHeight),
    "",
    ...scale("dur", tokens.duration),
    "",
    ...scale("shadow", tokens.shadow),
    "}",
    "",
    "@media (prefers-color-scheme: dark) {",
    "  :root {",
    ...dark.map((line) => `  ${line}`),
    "  }",
    "}",
    "",
  ];
  return `${HEAD}\n${blocks.join("\n")}\n`;
}

const tokens = JSON.parse(readFileSync(SOURCE, "utf8"));
const rendered = render(tokens);
const shown = relative(REPO, TARGET).replaceAll("\\", "/");

if (process.argv.includes("--check")) {
  let current = "";
  try {
    current = readFileSync(TARGET, "utf8");
  } catch {
    console.error(`[tokens] 生成物不在: ${shown}`);
    process.exit(1);
  }
  if (current !== rendered) {
    console.error(`[tokens] ${shown} 与 ${relative(REPO, SOURCE)} 不一致。`);
    console.error("         跑 `pnpm -C app gen:tokens` 重新生成。");
    process.exit(1);
  }
  console.log(`[tokens] ${shown} 与声明一致。`);
} else {
  // 目标目录由生成器自己保证存在：少一步"先建目录"的手工前置，生成物就不会因缺目录而断。
  mkdirSync(dirname(TARGET), { recursive: true });
  writeFileSync(TARGET, rendered);
  console.log(`[tokens] 已生成 ${shown}`);
}

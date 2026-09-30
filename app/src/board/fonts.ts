// SPDX-FileCopyrightText: 2026 HanYang06
// SPDX-License-Identifier: Apache-2.0

/**
 * 字体替换机制的取值层（口径见 `docs/architecture/ui-theme.md` §3.8）。
 *
 * 三件事在这里定：
 * ① **三层角色**（界面 / 编辑 / 阅读）各一个值；
 * ② 用户覆盖**就是在 `:root` 上覆盖 CSS 变量**——不新增构建链；
 * ③ **必须能判断字体是否真的存在**：写一个不存在的名字，系统会**静默回退**，
 *    用户看着"没变"却不知原因。
 */

/** 三个字体角色。名字即 CSS 变量后缀：`--font-<role>`。 */
export const FONT_ROLES = ["sans", "mono", "read"] as const;
export type FontRole = (typeof FONT_ROLES)[number];

/** 每个角色在设置里的中文名（界面用）。 */
export const FONT_ROLE_LABEL: Record<FontRole, string> = {
  sans: "界面",
  mono: "编辑",
  read: "阅读",
};

export const FONT_ROLE_HINT: Record<FontRole, string> = {
  sans: "外壳、标签、列表、按钮、元信息",
  mono: "编辑区、代码、时间戳、表格",
  read: "阅读 / 展示态（只读长文）",
};

/** 用户选择：只存"用户改过"的那几层；没改过的层不出现在这里。 */
export type FontOverrides = Partial<Record<FontRole, string>>;

/**
 * 用户覆盖写在**独立的一层**上：`--font-<角色>-user`。
 *
 * 样式读的是 `var(--font-<角色>-user, var(--font-<角色>))`，
 * 故**用户没设、或设的字体不存在**时自动落回令牌里的默认链——
 * 字体名只有令牌一处真源，这里不必抄一份默认链（那会变成两份事实）。
 */
const USER_VAR = (role: FontRole): string => `--font-${role}-user`;

/**
 * 字体在本机是否可用。
 *
 * 做法是**实测宽度**：同一个字串用"候选字体 + 兜底字体"两串分别量，
 * 宽度不同即说明候选字体真的被用上了（静默回退时两串宽度相同）。
 * 比"查字体表"可靠——浏览器没有可靠的字体枚举接口。
 */
export function fontAvailable(name: string): boolean {
  if (typeof document === "undefined" || !name.trim()) return false;
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  if (!ctx) return false;

  const probe = "WWWWmmmmiiii8888否命器";
  const size = "48px";
  const measure = (family: string): number => {
    ctx.font = `${size} ${family}`;
    return ctx.measureText(probe).width;
  };

  const fallback = ["monospace", "serif", "sans-serif"].map((generic) => measure(generic));
  const candidate = measure(`"${name}", monospace`);
  const candidateSerif = measure(`"${name}", serif`);
  // 与至少一个通用族不同，才算"这个名字真的起作用了"
  return !nearly(candidate, fallback[0] ?? 0) || !nearly(candidateSerif, fallback[1] ?? 0);
}

/**
 * 该字体能否当等宽用——**靠支撑计算，不靠字形**。
 *
 * 名字里带 `Mono` 不等于中文字符等宽（有的中文字体只让拉丁等宽）。
 * 故拿中日韩字符实测：两个汉字的宽度应约等于两个拉丁字符的宽度（2:1 的等宽）。
 */
export function isMonospace(name: string): boolean {
  if (typeof document === "undefined" || !name.trim()) return false;
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  if (!ctx) return false;
  ctx.font = `32px "${name}"`;
  const latin = ctx.measureText("MMMMMMMMMM").width / 10;
  const cjk = ctx.measureText("啊啊啊啊啊").width / 5;
  if (latin <= 0) return false;
  const ratio = cjk / latin;
  // 等宽的中文字体约 2.0（1 个汉字 = 2 个拉丁字符宽）；留 15% 余量
  return ratio > 1.7 && ratio < 2.3;
}

const nearly = (a: number, b: number): boolean => Math.abs(a - b) < 0.5;

/** 把用户选择写到 `:root` 上；传空串即"还原默认"（等于交还给默认字体链）。 */
export function applyFontOverrides(
  overrides: FontOverrides,
  root: HTMLElement | null = typeof document === "undefined" ? null : document.documentElement,
): void {
  if (!root) return;
  for (const role of FONT_ROLES) {
    const value = normalizeFontName(overrides[role] ?? "");
    if (value) {
      root.style.setProperty(USER_VAR(role), `"${value}"`);
    } else {
      root.style.removeProperty(USER_VAR(role));
    }
  }
}

/** 归一化用户输入：去空格、去引号、空串视为未设置。 */
export function normalizeFontName(input: string): string | null {
  const cleaned = input
    .trim()
    .replace(/^["']|["']$/g, "")
    .trim();
  return cleaned.length > 0 ? cleaned : null;
}

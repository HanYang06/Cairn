/**
 * SPDX-FileCopyrightText: 2026 HanYang06
 * SPDX-License-Identifier: Apache-2.0
 *
 * 样式门禁：**禁字面量样式值**。
 *
 * 规矩（见 `rules/references/frontend.md` §一）：样式只从令牌取——组件里出现颜色 / 圆角 /
 * 间距 / 时长的字面值即违规，一律写 `var(--…)`。令牌的生成物 `src/styles/tokens.css`
 * 是唯一允许写死这些值的地方。
 */
export default {
  extends: ["stylelint-config-standard"],
  rules: {
    "declaration-property-value-disallowed-list": [
      {
        "/^color$/": ["/^(?!var\\().+/"],
        "/^(background|background-color)$/": ["/^(?!var\\().+/"],
        "/^border(-(top|right|bottom|left))?(-color)?$/": ["/^(?!var\\(|none|0).+/"],
        "/^border-radius$/": ["/^(?!var\\(|0$).+/"],
        "/^(padding|margin)(-(top|right|bottom|left))?$/": ["/^(?!var\\(|0$|auto$).+/"],
        "/^gap$/": ["/^(?!var\\(|0$).+/"],
        "/^(box-shadow|font-family|font-size|line-height|transition-duration)$/": [
          "/^(?!var\\().+/",
        ],
      },
      {
        severity: "error",
        message:
          "样式值必须取自令牌：写 var(--…)，不要写字面值（见 rules/references/frontend.md §一）",
      },
    ],
  },
  ignoreFiles: ["src/styles/tokens.css", "dist/**", "node_modules/**"],
};

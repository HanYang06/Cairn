// SPDX-FileCopyrightText: 2026 HanYang06
// SPDX-License-Identifier: Apache-2.0

/**
 * 动作按钮（原子）。
 *
 * 口径（`ui-theme.md` §3.4）：**动作可以是胶囊，容器不做胶囊。**
 * 三个层级各一个变体；`primary` 一屏最多一个（§3.5 的单动作原则）。
 */

import type { ReactNode } from "react";

import "./pill.css";

export type PillTone = "primary" | "ghost" | "danger";

export interface PillProps {
  readonly children: ReactNode;
  readonly tone?: PillTone;
  readonly onClick?: () => void;
  readonly title?: string;
  readonly disabled?: boolean;
}

export function Pill({ children, tone = "ghost", onClick, title, disabled = false }: PillProps) {
  return (
    <button
      className={`pill pill-${tone}`}
      type="button"
      onClick={onClick}
      title={title}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

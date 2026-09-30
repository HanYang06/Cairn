// SPDX-FileCopyrightText: 2026 HanYang06
// SPDX-License-Identifier: Apache-2.0

/**
 * 卡片（原子）。
 *
 * 口径：**卡片是板上唯一的单元**（`by-design.md` §8.4）。一张卡有类型名、标题、
 * 内容与元信息；**容器不做胶囊**（`ui-theme.md` §3.4），故卡是矩形、圆角走 `--radius-xl`。
 *
 * 本文件只负责"长什么样"与"报出意图"；拖拽与缩放由 `composites/board` 编排。
 */

import { forwardRef, type ReactNode } from "react";

import "./card.css";

export interface CardProps {
  /** 卡片类型名（界面短词，如「笔记」「待办」）。 */
  readonly kind: string;
  readonly title: string;
  readonly description?: string;
  readonly meta?: ReactNode;
  /** 被点选。 */
  readonly selected?: boolean;
  readonly onSelect?: () => void;
  /** 右下角的缩放把手由 `Board` 注入，卡片自己不管拖拽语义。 */
  readonly resizeHandle?: ReactNode;
}

export const Card = forwardRef<HTMLElement, CardProps>(function Card(
  { kind, title, description, meta, selected = false, onSelect, resizeHandle },
  ref,
) {
  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: 键盘操作在 slot 上（方向键移动 / Shift 改尺寸）
    <article
      ref={ref}
      className={selected ? "card card-selected" : "card"}
      onClick={onSelect}
      aria-current={selected ? "true" : undefined}
    >
      <header className="card-head">
        <span className="card-kind">{kind}</span>
      </header>
      <h3 className="card-title">{title}</h3>
      {description ? <div className="card-body">{description}</div> : null}
      {meta ? <div className="card-meta">{meta}</div> : null}
      {resizeHandle}
    </article>
  );
});

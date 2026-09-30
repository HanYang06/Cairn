// SPDX-FileCopyrightText: 2026 HanYang06
// SPDX-License-Identifier: Apache-2.0

/**
 * 卡片板（组合）：把 `Card` 原子按整数格摆开，接住指针与键盘。
 *
 * 本层**只做编排**：几何计算全在 `board/layout.ts`（纯函数、有测试），
 * 卡片的观感在 `atoms/card`。这里只做三件事——
 * ① 把占位翻译成 Grid 定位；② 指针拖右下角 → 原始比例 → 吸附成整格；
 * ③ 键盘方向键移动、`Shift` + 方向键改尺寸。
 *
 * 组件不自己发请求：变更经 `onCommit` 向上抛，由页面交给 IPC 客户端（`ipc/` 唯一咽喉）。
 */

import { type CSSProperties, type KeyboardEvent, type PointerEvent, useRef, useState } from "react";

import { Card } from "../../atoms/card/card";
import type { BoardCard } from "../../board/cards";
import { GRID_COLS, GRID_ROWS, snapSize, toGridPlacement } from "../../board/layout";
import "./board.css";

export interface BoardProps {
  readonly cards: readonly BoardCard[];
  readonly selectedId: string | null;
  readonly onSelect: (id: string) => void;
  /** 一次调整结束（指针抬起 / 键盘操作）时抛给页面——页面据此落盘。 */
  readonly onCommit: (cards: readonly BoardCard[]) => void;
  /** 拖动过程中的预览（不落盘）。 */
  readonly onPreview: (cards: readonly BoardCard[]) => void;
  /** 认领一次调整：以该卡为基准消重叠并补位。 */
  readonly onSettle: (cards: readonly BoardCard[], movedId: string) => readonly BoardCard[];
}

interface DragState {
  readonly id: string;
  readonly baseW: number;
  readonly baseH: number;
  readonly cellW: number;
  readonly cellH: number;
  readonly startX: number;
  readonly startY: number;
}

export function Board({ cards, selectedId, onSelect, onCommit, onPreview, onSettle }: BoardProps) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const drag = useRef<DragState | null>(null);
  const [living, setLiving] = useState<{ id: string; rawW: number; rawH: number } | null>(null);

  /** 认领一次拖拽：量出单元格尺寸，后面全靠它把像素换成格。 */
  const beginResize = (event: PointerEvent<HTMLDivElement>, card: BoardCard): void => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    event.preventDefault();
    event.stopPropagation();
    (event.target as HTMLElement).setPointerCapture(event.pointerId);

    const rect = canvas.getBoundingClientRect();
    const style = getComputedStyle(canvas);
    const gapX = Number.parseFloat(style.columnGap) || 0;
    const gapY = Number.parseFloat(style.rowGap) || 0;
    const padX = Number.parseFloat(style.paddingLeft) || 0;
    const padY = Number.parseFloat(style.paddingTop) || 0;

    drag.current = {
      id: card.id,
      baseW: card.w,
      baseH: card.h,
      cellW: (rect.width - padX * 2 - gapX * (GRID_COLS - 1)) / GRID_COLS,
      cellH: (rect.height - padY * 2 - gapY * (GRID_ROWS - 1)) / GRID_ROWS,
      startX: event.clientX,
      startY: event.clientY,
    };
    setLiving({ id: card.id, rawW: card.w, rawH: card.h });
  };

  const moveResize = (event: PointerEvent<HTMLDivElement>): void => {
    const state = drag.current;
    if (!state) return;
    const rawW = state.baseW + (event.clientX - state.startX) / (state.cellW + 2);
    const rawH = state.baseH + (event.clientY - state.startY) / (state.cellH + 2);
    const card = cards.find((c) => c.id === state.id);
    if (!card) return;
    const { w, h } = snapSize(card, rawW, rawH);
    setLiving({ id: state.id, rawW, rawH });
    onPreview(cards.map((c) => (c.id === state.id ? { ...c, w, h } : c)));
  };

  const endResize = (): void => {
    const state = drag.current;
    drag.current = null;
    setLiving(null);
    if (!state) return;
    onCommit(onSettle(cards, state.id));
  };

  /** 键盘：方向键移动；`Shift` + 方向键改尺寸。指针的可达性由此补齐。 */
  const onKeyDown = (event: KeyboardEvent<HTMLElement>, card: BoardCard): void => {
    const step = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[
      event.key
    ];
    if (!step) return;
    event.preventDefault();
    const [dx, dy] = step;

    const next = cards.map((c) => {
      if (c.id !== card.id) return c;
      if (event.shiftKey) {
        const w = Math.min(Math.max(1, c.w + dx), GRID_COLS - c.x + 1);
        const h = Math.min(Math.max(1, c.h + dy), GRID_ROWS - c.y + 1);
        return { ...c, w, h };
      }
      const x = Math.min(Math.max(1, c.x + dx), GRID_COLS - c.w + 1);
      const y = Math.min(Math.max(1, c.y + dy), GRID_ROWS - c.h + 1);
      return { ...c, x, y };
    });
    onCommit(onSettle(next, card.id));
  };

  const gridStyle = { "--board-cols": GRID_COLS, "--board-rows": GRID_ROWS } as CSSProperties;

  return (
    <div
      className="board"
      ref={canvasRef}
      style={gridStyle}
      onPointerMove={moveResize}
      onPointerUp={endResize}
      onPointerCancel={endResize}
    >
      {cards.map((card) => {
        const selected = card.id === selectedId;
        const live = living?.id === card.id ? living : null;
        return (
          <button
            type="button"
            className="board-slot"
            key={card.id}
            style={toGridPlacement(card)}
            aria-label={`${card.kind}卡片，位于第 ${card.x} 列第 ${card.y} 行，${card.w} × ${card.h} 格；方向键移动，Shift + 方向键改尺寸`}
            onClick={() => onSelect(card.id)}
            onKeyDown={(event) => onKeyDown(event, card)}
          >
            <Card
              kind={card.kind}
              title={card.kind === "笔记" ? "今天把界面材质换成 Tauri" : `空${card.kind}卡`}
              description={
                card.kind === "笔记"
                  ? "决定不是要不要换，是换的时机到了。"
                  : "内容面（契约生成器落地前只放中性占位）。"
              }
              selected={selected}
              meta={
                <>
                  <span>
                    {card.x},{card.y}
                  </span>
                  <span>
                    {card.w} × {card.h}
                  </span>
                  {live ? (
                    <span className="board-raw">
                      原始 {live.rawW.toFixed(2)} × {live.rawH.toFixed(2)}
                    </span>
                  ) : null}
                </>
              }
              resizeHandle={
                <div
                  className="board-grip"
                  role="presentation"
                  title="拖动改大小（或 Shift + 方向键）"
                  onPointerDown={(event) => beginResize(event, card)}
                />
              }
            />
          </button>
        );
      })}
    </div>
  );
}

// SPDX-FileCopyrightText: 2026 HanYang06
// SPDX-License-Identifier: Apache-2.0

/**
 * 卡片的类型与内容。
 *
 * **注意（`frontend.md` §二）**：这里**不是领域契约**。领域契约必须由 Python 侧声明并生成，
 * 而生成器要有真领域类才有对象可生成——**在那之前不许在前端手写领域类型**。
 * 故本文件只是**工作台的展示用材**：类型名是界面词汇（笔记 / 待办 / …），
 * 一旦契约生成器落地，这里整份换成"由契约渲染"，其余组件不动。
 */

import type { CardSpot } from "../board/layout";

/** 一张卡 = 一块整格占位 + 类型名。 */
export interface BoardCard extends CardSpot {
  /** 类型名（界面短词）。 */
  readonly kind: string;
}

/** 板上的卡片类型（界面词汇，不是领域类型）。 */
export const CARD_KINDS = [
  { id: "note", label: "笔记" },
  { id: "todo", label: "待办" },
  { id: "memo", label: "速记" },
  { id: "set", label: "集合" },
  { id: "link", label: "关系" },
] as const;

/** 新建卡片时循环使用的类型。 */
export function nextKind(existing: readonly BoardCard[]): string {
  const used = new Set(existing.map((c) => c.kind));
  const spare = CARD_KINDS.find((k) => !used.has(k.label));
  return (spare ?? CARD_KINDS[0]).label;
}

/** 首次打开的默认板：6 × 5 的网格上摆四张卡。 */
export const DEFAULT_BOARD: readonly BoardCard[] = [
  { id: "c1", x: 1, y: 1, w: 4, h: 2, kind: "笔记" },
  { id: "c2", x: 5, y: 1, w: 2, h: 2, kind: "待办" },
  { id: "c3", x: 1, y: 3, w: 2, h: 3, kind: "速记" },
  { id: "c4", x: 3, y: 4, w: 4, h: 2, kind: "集合" },
];

/** 新卡片的默认尺寸：两格宽、两格高（够放标题与一行内容）。 */
export const NEW_CARD_SIZE = { w: 2, h: 2 } as const;

/** 一串卡片是否与默认板一致（用于"还原默认"按钮的可用性）。 */
export function isDefaultBoard(cards: readonly BoardCard[]): boolean {
  if (cards.length !== DEFAULT_BOARD.length) return false;
  return cards.every((card, i) => {
    const d = DEFAULT_BOARD[i];
    return d
      ? card.id === d.id && card.x === d.x && card.y === d.y && card.w === d.w && card.h === d.h
      : false;
  });
}

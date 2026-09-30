// SPDX-FileCopyrightText: 2026 HanYang06
// SPDX-License-Identifier: Apache-2.0

/**
 * 工作台（页面）：卡片板的容器。
 *
 * 结构口径（`by-design.md` §4 路线 F）：顶带（搜索 / 命令）→ 纵向页签（跨域组织）
 * → 舞台（动作行 + 卡片板 + 字体行）。**留白由使用者亲手安排**——故这一层几乎不摆东西：
 * 一格视图切换、一个新增、一个还原默认，其余动作留给右键菜单（§3 决策四站位 + 单动作原则）。
 *
 * 本文件是**唯一**把布局与字体选择落盘的地方：经 `ipc/` 这个唯一咽喉。
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { Pill } from "../../atoms/pill/pill";
import { type BoardCard, DEFAULT_BOARD, NEW_CARD_SIZE, nextKind } from "../../board/cards";
import {
  applyFontOverrides,
  FONT_ROLE_HINT,
  FONT_ROLE_LABEL,
  FONT_ROLES,
  type FontOverrides,
  type FontRole,
  fontAvailable,
  normalizeFontName,
} from "../../board/fonts";
import { firstFreeSpot } from "../../board/layout";
import { parseBoard, serializeBoard, settleBoard } from "../../board/storage";
import { Board } from "../../composites/board/board";
import { listSystemFonts, readBoardLayout, writeBoardLayout } from "../../ipc";
import "./workbench.css";

const FONT_KEY = "cairn.font.overrides";

/** 板内视图（`by-design.md` §4 倾向：板内换态，共用一条骨架）。 */
const VIEWS = ["卡片", "流", "看板", "专注"] as const;
type ViewName = (typeof VIEWS)[number];

/** 分域页签（界面词汇；领域层重建后再由契约驱动）。 */
const RAILS = ["记", "项", "画", "库"] as const;

function readFontOverrides(): FontOverrides {
  try {
    const raw = globalThis.localStorage?.getItem(FONT_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as FontOverrides;
    const out: FontOverrides = {};
    for (const role of FONT_ROLES) {
      const value = normalizeFontName(parsed[role] ?? "");
      if (value) out[role] = value;
    }
    return out;
  } catch {
    return {};
  }
}

export function Workbench() {
  const [cards, setCards] = useState<readonly BoardCard[]>(() => [...DEFAULT_BOARD]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<ViewName>("卡片");
  const [overrides, setOverrides] = useState<FontOverrides>({});
  const [systemFonts, setSystemFonts] = useState<readonly string[]>([]);
  const [saved, setSaved] = useState(true);

  // 启动：把布局读回来（读不动就回到默认板）
  useEffect(() => {
    let alive = true;
    void readBoardLayout().then((raw) => {
      if (alive) setCards(parseBoard(raw));
    });
    return () => {
      alive = false;
    };
  }, []);

  // 启动：把用户字体选择读回来并生效
  useEffect(() => {
    const stored = readFontOverrides();
    setOverrides(stored);
    applyFontOverrides(stored);
  }, []);

  // 系统字体：经壳（前端没有枚举能力）。没有壳时留空，界面自行降级。
  useEffect(() => {
    let alive = true;
    void listSystemFonts().then((fonts) => {
      if (alive) setSystemFonts(fonts);
    });
    return () => {
      alive = false;
    };
  }, []);

  /** 一次调整结束：落盘"已被认领"的那一版（消重叠 + 补位之后）。 */
  const commit = useCallback((next: readonly BoardCard[]) => {
    setCards(next);
    setSaved(false);
    void writeBoardLayout(serializeBoard(next)).then(() => setSaved(true));
  }, []);

  /** 认领一次调整：被拖的卡优先入场。 */
  const settleOnly = useCallback(
    (next: readonly BoardCard[], movedId: string) => settleBoard(next, movedId),
    [],
  );

  const addCard = useCallback(() => {
    setCards((current) => {
      const free = firstFreeSpot(current, NEW_CARD_SIZE.w, NEW_CARD_SIZE.h);
      if (!free) return current;
      const card: BoardCard = {
        id: `c${Date.now().toString(36)}`,
        x: free.x,
        y: free.y,
        w: NEW_CARD_SIZE.w,
        h: NEW_CARD_SIZE.h,
        kind: nextKind(current),
      };
      const next = [...current, card];
      void writeBoardLayout(serializeBoard(next));
      setSelectedId(card.id);
      return next;
    });
  }, []);

  const resetBoard = useCallback(() => {
    const next = [...DEFAULT_BOARD];
    setCards(next);
    setSelectedId(null);
    void writeBoardLayout(serializeBoard(next));
  }, []);

  const changeFont = useCallback((role: FontRole, raw: string) => {
    const name = normalizeFontName(raw);
    setOverrides((current) => {
      const next: FontOverrides = { ...current };
      if (name) next[role] = name;
      else delete next[role];
      applyFontOverrides(next);
      try {
        globalThis.localStorage?.setItem(FONT_KEY, JSON.stringify(next));
      } catch {
        // 存不进去不影响本次运行：字体选择是视图偏好
      }
      return next;
    });
  }, []);

  const datalistId = "cairn-system-fonts";
  const fontCount = useMemo(() => systemFonts.length, [systemFonts.length]);

  return (
    <div className="workbench">
      <header className="workbench-top">
        <span className="workbench-brand">Cairn</span>
        <span className="workbench-find">搜索 / 命令　Ctrl+K</span>
        <span className="workbench-status">
          <span>{saved ? "布局已保存" : "保存中…"}</span>
          <span>{fontCount > 0 ? `系统字体 ${fontCount}` : "系统字体未接"}</span>
        </span>
      </header>

      <div className="workbench-main">
        <nav className="workbench-rail" aria-label="域">
          {RAILS.map((label, i) => (
            <span
              key={label}
              className={i === 0 ? "workbench-rail-item on" : "workbench-rail-item"}
            >
              {label}
            </span>
          ))}
        </nav>

        <div className="workbench-stage">
          <div className="workbench-actions">
            <span className="workbench-views">
              {VIEWS.map((name) => (
                <button
                  key={name}
                  type="button"
                  className={name === view ? "workbench-view on" : "workbench-view"}
                  onClick={() => setView(name)}
                >
                  {name}
                </button>
              ))}
            </span>
            <span className="workbench-actions-right">
              <span className="workbench-hint">
                拖右下角改大小 · 方向键移动 · Shift + 方向键改尺寸
              </span>
              <Pill onClick={addCard}>新增卡片</Pill>
              <Pill onClick={resetBoard}>还原默认</Pill>
            </span>
          </div>

          <Board
            cards={cards}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onPreview={setCards}
            onCommit={commit}
            onSettle={settleOnly}
          />

          <div className="workbench-fonts">
            {FONT_ROLES.map((role) => {
              const value = overrides[role] ?? "";
              const ok = value ? fontAvailable(value) : true;
              return (
                <label className="workbench-font" key={role}>
                  <span className="workbench-font-role">{FONT_ROLE_LABEL[role]}</span>
                  <input
                    className="workbench-font-input"
                    list={datalistId}
                    placeholder={`默认（${FONT_ROLE_HINT[role]}）`}
                    value={value}
                    onChange={(event) => changeFont(role, event.target.value)}
                  />
                  {ok ? null : <span className="workbench-font-bad">本机没有这个字体</span>}
                </label>
              );
            })}
            <datalist id={datalistId}>
              {systemFonts.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
            <span className="workbench-fonts-note">
              只引用你系统里的字体：本软件不打包、不分发任何字体文件。
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

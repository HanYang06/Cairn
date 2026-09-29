---
name: memory
description: "Cairn 项目记忆（变更 / 决策 / 进度 / TODO）。任务开始前或改动代码前，读相关记忆了解现状；任务收尾时更新记忆，并清理过期、已废弃、与代码不符的条目。"
license: Apache-2.0
---

<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Cairn 项目记忆

**这个技能本身就是项目的记忆**（可变、活文件）。内容按类别放在 `references/`：

| 类别 | 位置 | 说明 |
|---|---|---|
| 决策（已定方向及理由） | [`references/decisions/`](references/decisions/) | 按主题分节，每节一个文件；入口 [`references/decisions/index.md`](references/decisions/index.md) |
| 变更（重要改动记录） | [`references/changes/`](references/changes/) | 按日期分节，每天一个文件；入口 [`references/changes/index.md`](references/changes/index.md) |
| 进度 / TODO | [`progress.md`](progress.md) | 独立文件，不建目录 |
| 评审问题记录（原文件） | [`note/`](note/) | |
| 评审修复记录（对比） | [`fix/`](fix/) | |

## 怎么读

- 任务开始时，只读与当前任务**相关**的条目，不必全读。
- 记忆只是现状快照；与代码或 `docs/architecture/*.md` 冲突时，**服从事实**。

## 怎么写（格式）

每条标明**日期 + 状态**：

```
- 2026-09-14 · 已定 · <内容> | <理由>
```

状态取值：`进行中` / `已定` / `已废弃`。

### 变更（changes/）

- 按日期追加，每天一个文件（`changes/YYYY-MM-DD.md`）。
- 新日期新建文件；同一天追加到已有文件。
- 文件内按时间倒序（新条目在前）。

### 决策（decisions/）

- 按主题分节，每个主题一个文件（`decisions/<主题名>.md`）。
- 新主题新建文件；已有主题追加到对应文件。
- 文件内按时间倒序（新条目在前）。
- 新增主题时必须同步更新 `decisions/index.md`。

## 清理机制（硬性）

- 每次任务收尾**一并清理**：过期、已废弃、与代码或文档不符的条目 → 删除或改写。
- 只增不减会腐化失真；记忆必须比代码更短、更新更快。
- 已在代码或架构文档中固化的事实，不要再在记忆里重复。

## 评审记录职责

所有代码评审（OCR、人工审查等）的问题与修复，统一记录到两个目录：

| 目录 | 职责 | 文件命名 |
|---|---|---|
| [`note/`](note/) | **问题记录**：记录评审发现的问题，注明文件、原因、行号 | `<PR编号>-<问题编号>.md` |
| [`fix/`](fix/) | **修复记录**：与 note 对应，记录修复前后的对比 | `<PR编号>-<问题编号>.md` |

### 记录规则

- **一一对应**：每个问题在 `note/` 和 `fix/` 各有一个文件，文件名相同
- **note 文件**：记录问题本身（文件路径、行号、问题描述、严重性）
- **fix 文件**：记录修复方案（修复前代码、修复后代码、修复理由）
- **脚本辅助**：用 `tools/review_record.py` 生成记录模板，避免手写格式错误

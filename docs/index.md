<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Cairn · 巨石堆

> **本地优先的内容寻址对象池** —— 笔记、资产、项目，一台工作台。
> 一块块往上堆。

[:octicons-rocket-24: 快速开始](guides/quickstart.md){ .md-button .md-button--primary }
[:octicons-book-24: 架构总纲](architecture/data-model.md){ .md-button }

---

## 这是什么

Cairn 把使用者的内容存成一个**内容寻址对象池**：所有内容按内容哈希去重、按稳定身份寻址，
落普通文件（`vault/<桶>/packs/*.pack`）+ 一个**可重建的索引库**（`vault/catalog.db`）。应用只是消费者。

| 常见问题 | Cairn 的答案 |
|---|---|
| 数据在哪 | 若干普通文件，加一个 SQLite 索引库（**真源是载体，索引库只是投影**）；没有私有格式、没有云 |
| 会不会被锁死 | Apache-2.0；本地**不加密**、明文落盘，任何时候都能用别的工具读 |
| 为什么不用 Obsidian / Notion | 那些是"笔记应用"；Cairn 是"对象池 + 工作台"，笔记只是一种对象 |
| 现在能用吗 | **还不能**。内核已立、界面在重建中，见下 |

## 现状（诚实版）

早期开发阶段，**尚未发布**。

- ✅ **已落地**：L0 存储重写完成（块 / 载体 / 桶 / 多桶 / 索引库 / 巡检，内核已接上新底座）、
  类型地基（`Attr` / `Data` / `Cfg` 工具单元）、
  配置引擎（声明即事实，两个投影落盘）、信号引擎与内核门户（`Core` / `Signal` / `Storage` / `Conf`）、
  笔记领域（数据 + 域服务、行身份 + 区间样式）、Windows 根壳与笔记卡片舞台。
- ⚠️ **已知缺口**：**版本能力整体缺失**（`VersionStore` 与版本表已随内核重建移除，尚无一处写版本表）；
  `@action` 动作表未成立、`Intent` / `Slot` 未被引擎读取；`Event` 的 canonical 编解码（网络往返）未落。
- 🔜 **未做**：对象驱动生成、多页 Tab 宿主、笔记编辑页（专注态）、打包、P2P / 服务端。

进度与待办的**事实源**是 [`docs/architecture/*.md`](architecture/index.md) 与代码本身；
「[架构](architecture/index.md)」一节逐篇列出各文档的状态与权威范围。

## 文档来源

1. **手写文档** —— `docs/**/*.md` 与 `src/**` 的 docstring 是事实源，随代码一起提交、一起评审。
2. **自动生成** —— 「[API 参考](api/index.md)」里的签名、类型、docstring 全部由
   [mkdocstrings](https://mkdocstrings.github.io/) 从源码抽取；生成物无第二份拷贝。
   站点本身（`site/`）是构建产物，不入库。

改文档的流程见「[怎么改文档](contributing/docs.md)」。

## 许可

Copyright &copy; 2026 HanYang06 · [Apache-2.0](contributing/license.md)。
分发时请一并保留 `LICENSE` 与 `NOTICE`。

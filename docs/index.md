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
落普通文件（`<root>/<hub>/packs/*.pack`）+ 一个**可重建的索引库**（`<root>/catalog.db`）。应用只是消费者。

| 常见问题 | Cairn 的答案 |
|---|---|
| 数据在哪 | 若干普通文件，加一个 SQLite 索引库（**真源是载体，索引库只是投影**）；没有私有格式、没有云 |
| 会不会被锁死 | Apache-2.0；本地**不加密**、明文落盘，任何时候都能用别的工具读 |
| 为什么不用 Obsidian / Notion | 那些是"笔记应用"；Cairn 是"对象池 + 工作台"，笔记只是一种对象 |
| 现在能用吗 | **还不能**。内核已立、界面在重建中，见下 |

## 现状（诚实版）

早期开发阶段，**尚未发布**。

- ✅ **已落地**：**内核重建完成**——事件引擎（`Event` / `Bus` / 目录）、存储引擎
  （身份 / 载体 / hub / 索引库 / 行层 / 巡检与处置）、异常层，以及把它们装在一起的 `Kernel`；
  213 例测试、覆盖率 99%，仓库级门禁（ruff / mypy strict / pytest / 文档站 / SPDX / 书面语）全绿。
- ⚠️ **重建中被删除、待重建**：领域（`feature`）、界面工具箱（`ui_tools`）、应用外壳（`app`）、
  配置引擎（`core/conf/` 作者重做中）、打包与桌面入口。
- 🔜 **未做**：内容与块的**压实回收**（更新与摘块留下的旧字节会一直留着）、跨行事务与崩溃恢复、
  大正文分片、检索、P2P / 服务端。

进度与待办的**事实源**是 [`docs/architecture/*.md`](architecture/index.md) 与代码本身；
「[架构](architecture/index.md)」一节逐篇列出各文档的状态、**与代码的对应关系**（现状 / 意图 / 存档）。

## 文档来源

1. **手写文档** —— `docs/**/*.md` 与 `src/**` 的 docstring 是事实源，随代码一起提交、一起评审。
2. **自动生成** —— 「[API 参考](api/index.md)」里的签名、类型、docstring 全部由
   [mkdocstrings](https://mkdocstrings.github.io/) 从源码抽取；生成物无第二份拷贝。
   站点本身（`site/`）是构建产物，不入库。

改文档的流程见「[怎么改文档](contributing/docs.md)」。

## 许可

Copyright &copy; 2026 HanYang06 · [Apache-2.0](contributing/license.md)。
分发时请一并保留 `LICENSE` 与 `NOTICE`。

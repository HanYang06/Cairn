<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Cairn · 巨石堆

> **本地优先的内容寻址对象池**——笔记、资产、项目，集中在一台工作台。

[:octicons-rocket-24: 快速开始](guides/quickstart.md){ .md-button .md-button--primary }

---

## 这是什么

Cairn 把使用者的内容存成一个**内容寻址对象池**：所有内容按内容哈希去重、按稳定身份寻址，
落普通文件（`<root>/<hub>/packs/*.pack`）+ 一个**可重建的索引库**（`<root>/catalog.db`）。应用只是消费者。

| 常见问题 | Cairn 的答案 |
|---|---|
| 数据在哪 | 若干普通文件，加一个 SQLite 索引库（**真源是载体，索引库只是投影**）；没有私有格式、没有云 |
| 会不会被锁定 | Apache-2.0；本地**不加密**、明文落盘，任何时候都能用别的工具读 |
| 为什么不用 Obsidian / Notion | 那些是笔记应用；Cairn 是对象池 + 工作台，笔记只是一种对象 |
| 现在能用吗 | **还不能**。内核已立、界面在重建中，见下 |

## 现状

早期开发阶段，**尚未发布**（`0.0.1` / pre-alpha）。

- ⚠️ **L0 存储正在重写**：旧的存储模块已删、新的尚未补齐（`core.init` 依赖的模块缺失），
  故 `pytest`、`mypy` 与本站的构建此刻均不成立，`Kernel` 亦无法导入；事件引擎、配置引擎、
  异常层与 `core/clock.py` 的时间口径不受影响。
- **重建中**：领域层（`feature` 已删，新落点 `py_src/model/note/`）；
  界面（Tauri 壳与边车已接线，功能未齐）。
- **未做**：内容与块的压实回收（更新与摘块留下的旧字节仍占空间）、跨行事务与崩溃恢复、
  大正文分片、检索、P2P / 服务端、打包与桌面入口。

进度与待办的事实源是**代码本身**。`docs/architecture/**` 那批设计页在 2026-09-29 的重建里
被删、**待重写**（总纲、L0 存储设计、内核、领域、笔记模型、网络与生态等），此刻在库的只有
[配置引擎](architecture/py_core/config.md)与 [UI 主题](architecture/ui_design/ui-theme.md)两页。

## 文档来源

1. **手写文档** —— `docs/**/*.md` 与 `py_src/**` 的 docstring 是事实源，随代码一起提交、一起评审。
2. **自动生成** —— 「[API 参考](api/index.md)」里的签名、类型、docstring 全部由
   [mkdocstrings](https://mkdocstrings.github.io/) 从源码抽取；生成物无第二份拷贝。
   站点本身（`site/`）是构建产物，不入库。

改文档的流程见「[怎么改文档](contributing.md#怎么改文档)」。

## 许可

Copyright &copy; 2026 HanYang06 · [Apache-2.0](contributing.md#许可与署名)。
分发时请一并保留 `LICENSE` 与 `NOTICE`。

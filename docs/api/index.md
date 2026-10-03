<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# API 参考

!!! info "本节自动生成"

    下面所有签名、类型、docstring 由 [mkdocstrings](https://mkdocstrings.github.io/)
    直接从 `py_src/**` 抽取（走 AST，不执行副作用代码）。不存在会过期的第二份拷贝：
    代码或 docstring 变更即反映到页面。不得手写 API 说明。

## 稳定度分级

本项目的 API 面不承诺稳定（0.0.1、pre-alpha）。按可依赖程度分三档：

| 档 | 范围 | 说明 |
|---|---|---|
| **公共面**（较稳） | `core` 的 `Kernel` / `Block` / `Engine` / `Bus` / `Event` / `ID`；`core.exc` 的异常层级 | 随设计演进，变更体现于本页，并尽量保留过渡 |
| **格式面**（改即改格式） | `core.storage.pack` 的魔数与头长度、`core.storage.db.payload` 的载荷编解码、`core.storage.db.id` 的落盘口径 | 动它们等于动落盘字节：旧库不兼容，须显式处置 |
| **内部**（不依赖） | `_` 开头的名字、`core.storage.slot` 的格算术细节、`core.storage.engine` 的字段归类与位置回填 | 随时会变，不作依赖 |

## 层次

```text
core(L0)  ←  feature(L3)  ←  app(组合根)
```

`core` 是当前唯一有代码的一层：`feature` / `app` 在 2026-09-29 的重建中整条删除、待重建，
故本节只有 core 一页，其页面在代码回来后再生成。`ui_tools` 这一 Qt 时代层名已作废，
其职责由前端共享组件承担（界面侧边界见 `.agents/skills/rules/references/ui-boundary.md`）。
各层的目标形态见仓根 `AGENTS.md` 的「架构分层」；`py_src/model/note/` 是笔记领域的形状层，
其 API 页面待领域层重建后再生成。

| 页 | 覆盖 |
|---|---|
| [core（底座）](core.md) | 内核装配、配置引擎、事件引擎、存储四层、数据库引擎与索引、命令面、异常与时间 |

## 怎么读

- 先读「[架构索引](../architecture/index.md)」再看本节：本节给出签名，设计文档给出依据。
- 每页顶部的包 docstring 通常包含该层的边界与红线。
- 查词用「[术语表](../reference/glossary.md)」。

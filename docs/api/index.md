<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# API 参考

!!! info "这一节是自动生成的"

    下面所有签名、类型、docstring 都由 [mkdocstrings](https://mkdocstrings.github.io/)
    直接从 `src/**` 抽取（走 AST，不执行副作用代码）。**没有第二份会过期的拷贝** ——
    改代码 / 改 docstring，这里就跟着变。请**不要**手写 API 说明。

## 稳定度分级

本项目的 API 面**不承诺稳定**（0.0.1、pre-alpha）。按"能不能碰"分三档：

| 档 | 范围 | 说明 |
|---|---|---|
| **公共面**（较稳） | `core` 的 `Kernel` / `Storage` / `Bus` / `Event` / `ID`；`core.exc` 的异常层级 | 会随设计走，但**改了会在这里体现**，且尽量留过渡 |
| **格式面**（改就是改格式） | `core.storage.format.*`（身份 / 块载荷 / 记录）与 `core.storage.carrier` 的文件头 | 动它们等于动落盘字节：旧库不兼容，须显式处置 |
| **内部**（别依赖） | `_` 开头的名字、`core.storage` 的表结构与槽算术细节、`core.storage.patrol` 的比对内部 | 随时会动；`ui_tools` 连 `core.storage` 都不许 import |

## 层次

```text
core(L0)  ←  feature(L3)  ←  app(组合根)
                     ↑
                ui_tools(工具箱)
```

`core` 是现在唯一有代码的一层；其余三层在 2026-09-29 的重建里被整条删除，页面留位。

| 页 | 覆盖 | 状态 |
|---|---|---|
| [core（底座）](core.md) | 内核装配、事件引擎、存储引擎、字节格式、异常与时间 | 有代码 |
| [feature（领域）](feature.md) | note / project 域与共享件 | 待重建 |
| [ui_tools（界面工具层）](ui-tools.md) | 声明树、编译管线、绑定、模型、主题、组件与布局 | 待重建 |
| [app（应用组合根）](app.md) | 领域装配与平台入口（Windows 根壳） | 待重建 |

## 怎么读

- **先看「[架构](../architecture/index.md)」再看这里**：这里回答"签名是什么"，
  架构文档回答"为什么长这样"。反过来读会一头雾水。
- 每页顶部的包 docstring 通常写着该层的**边界与红线**，比正文更值得读。
- 想找某个词 → 「[术语表](../reference/glossary.md)」。

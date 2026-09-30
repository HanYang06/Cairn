<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 许可与署名

## 本项目

Copyright 2026 HanYang06 · **Apache License 2.0**。

分发时请一并保留 [`LICENSE`](https://github.com/HanYang06/cairn/blob/main/LICENSE)
与 [`NOTICE`](https://github.com/HanYang06/cairn/blob/main/NOTICE)。

## 依赖许可政策

| 类别 | 结论 |
|---|---|
| MIT / ISC / BSD / Apache-2.0 | ✅ **鼓励使用**：宽松、可商用、可闭源分发 |
| **GPL / AGPL** | ❌ **禁止引入**：传染性会把本项目拖成 GPL |
| 禁止商用类（CC-BY-NC、PolyForm NC） | ❌ 与"可商用"目标冲突，不引 |

- 唯一的工具用途例外是**开发期**工具的许可也不放松：宁可自己写。
  例：`fsfe/reuse-tool` 是 GPL-3.0-or-later，因此**不引入 `reuse` CLI**，
  只采用它定义的 `REUSE.toml` **数据格式**，读写由自研的 `scripts/spdx.py` 实现。
- 新增依赖后**复核** `NOTICE` / `pyproject.toml` 的许可声明；第三方主题 / 画布 / 编辑器库
  先核实许可再采用。

### 本站用到的工具（构建期依赖，不进产品）

| 工具 | 许可 |
|---|---|
| [MkDocs](https://www.mkdocs.org/) | BSD-2-Clause |
| [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) | MIT |
| [mkdocstrings](https://mkdocstrings.github.io/) / `mkdocstrings-python` / Griffe | ISC |

## 源码与署名

- 每个源文件 / 文档顶部的 **SPDX 头**是许可声明的机器可读形式，由 `scripts/spdx.py` 自动补 / 校验，
  不要手抄（见「[约定与红线](../guides/conventions.md)」§2）。
- 装不下注释的文件（图片 / JSON / 锁文件 / 法律文书 / vendored）在根 `REUSE.toml` 集中声明。
- 第三方 vendored 的技能保持上游原样，来源与 hash 记入 `skills-lock.json`。

## 全文

### LICENSE

```text
--8<-- "LICENSE"
```

### NOTICE

```text
--8<-- "NOTICE"
```

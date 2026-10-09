<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- translation-source-hash: 4144d16785e63c04426f661d3444132e9c635482209cd092b86011f3cf5418ce -->
# API Reference

!!! info "This section is automatically generated"

    下面所有签名、类型、docstring 由 [mkdocstrings](https://mkdocstrings.github.io/)
    直接从 `py_src/**` 抽取（走 AST，不执行副作用代码）。不存在会过期的第二份拷贝：
    代码或 docstring 变更即反映到页面。不得手写 API 说明。

## Stability Grading

The API of this project does not guarantee stability (0.0.1, pre-alpha). Divided into three tiers based on reliability:

| Level | Range | Description |
|---|---|---|
| **Public Surface** (Relatively Stable) | `core`'s `Kernel` / `Block` / `Engine` / `Bus` / `Event` / `ID`; `core.exc`'s Exception Levels | As the design evolves, changes will be reflected on this page, with transitions preserved wherever possible |
| **Format Layer** (format changes take effect immediately) | Magic numbers, header length, and the encoding/decoding of payload for `core.storage.pack`; disk storage format for `core.storage.db.id` | Modifying these fields is equivalent to modifying the on-disk byte layout: incompatible with older libraries, requiring explicit handling |
| **Internal** (not to be relied upon) | Name formatting at the beginning, arithmetic details within `core.storage.slot`, field categorization and position backfilling within `core.storage.engine` | Subject to change at any time; do not rely on it |

## Hierarchy

```text
core(L0)  ←  feature(L3)  ←  app(组合根)
```

It is currently the only layer with code:/, which was completely deleted during the rebuild on 2026-09-29 and is pending reconstruction.
Therefore, this section consists of only one core page, which will be generated after the code is returned. This Qt era layer name has been deprecated.
Its responsibilities are handled by the front-end shared components (see the interface-side boundary in `.agents/skills/rules/references/ui-boundary.md`).
The target forms of each layer are shown in Kurone’s “Layered Architecture”; (6) is the shape layer in the note-taking domain.
Its API page will be generated after the domain layer is rebuilt.

| Page | Coverage |
|---|---|
| [core（底座）](core.md) | Kernel assembly, configuration engine, event engine, storage layer, database engine and indexing, command plane, exceptions and timing |

## How to read it

-First read “[架构索引](../architecture/index.md)”, then refer to this section: This section provides the signature, while the design document provides the rationale.
-The package docstring at the top of each page typically includes the layer’s boundaries and the red line.
-Use “[术语表](../reference/glossary.md)” to look up words.

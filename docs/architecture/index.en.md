<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- translation-source-hash: 5219997afe10bde3052f94d7cb3fef05d4fc494a2e24d9ab2b4efd5a46582824 -->
# Architecture Documentation Index

It is the source of design facts. Two premises:
> **① Each item is marked with its status; ② In case of conflicts, the roadmap takes precedence.**

## Order of Authority

```text
路线图  >  docs/architecture/<具体篇>  >  docs/architecture/<总纲篇>  >  记忆 / 其它
```

-**Roadmap manages “what”:** What to build, which design to follow, and which release it will be delivered in. When it conflicts with the design or code, **the roadmap takes precedence**.
Design and code both converge on it—after the roadmap was revised, the entire design section was rewritten, and the code was updated accordingly.
-**Code represents “what is now”**: It is the single source of truth for the current state. **The only exception** is the roadmap’s restatement of the current situation.
(`具体实现文件`, whether the code has been applied) when it does not match the code—what is being modified is the row in the route map: **the route map does not reflect the current status**.
-Architectural documentation describes the current state and the desired direction. Once the implementation is modified, update the documentation; updating the documentation is part of the task.
-Entries marked “Draft” indicate that the direction has been set but some aspects remain unrealized; those marked “Reserved” signify only the intended direction.
**Any content marked as “Reserved,” “Draft,” or “To Be Determined” shall not be used as the basis for implementation.**

## Status by Entry

On 2026-09-29, the refactoring will completely remove the old implementation under `py_src/` (leaving only `core`).
Therefore, the following table includes a column titled “Correspondence with Codes”: **Current Status** indicates that the definitions in the document correspond one-to-one with the codes.
**Intention** indicates that the layer described in the document currently has no code (or is being rebuilt) and can only serve as a guideline.

| Document | Scope of Authority | Correspondence with Code | Status |
|---|---|---|---|
| [L0 存储设计](storage-design.md) | **Overview of Blocks/Carriers/Hubs/Index Repositories/Indexes**; specific criteria shall be subject to [块的组成与落点](py_core/storage/block-parts.md) | **Current Status** (as of 2026-10-02) | Current Version |
| [块范式](block-model.md) | Block **Declaration/Identity/Index**: Criteria, Costs, Paths That Have Been Eliminated | **Current Status** (The paradigm has been implemented; unconnected points are marked one by one) | Current Version |
| [块的组成与落点](py_core/storage/block-parts.md) | The storage sublayer’s **deciding chapter**: attribute slots/content slots, what is stored in the repository, and the positioning of the two index blocks | **Current Status** (2026-10-02: finalized; 2026-10-06: no longer guaranteed across generations) | Current Implementation |
| [载体的字节布局](py_core/storage/pack-format.md) | Field-by-field **byte map**: carrier file header, slot header, two types of slots | **Status** (2026-10-02 – code dropped) | Current |
| [查询链路](py_core/storage/query-path.md) | List page start, positioning jump count, and failure semantics | **Current Status** (2026-10-02: code committed; pending items in §4 remain open) | Current Implementation |
| [配置引擎](py_core/config.md) | `conf` Face (declaration = value), single-file projection, configuration root and log output; the engine is upstream OnConf | **Current Status** (engine switched on 2026-10-04; finalized with version 2.0 on 2026-10-07) | Current Implementation |
| [UI 主题](ui_design/ui-theme.md) | Token Vocabulary, Color Palette, and Layout Contract | **Intent** (Token Pipeline Implemented: `tokens.json` → `tokens.css`; Behavioral Specifications Remain Intent) | Draft |

> **Substitution relationship**: The storage ruling for 2026-10-02 has overwritten [L0 存储设计](storage-design.md).
> [载体的字节布局](py_core/storage/pack-format.md) and [查询链路](py_core/storage/query-path.md),
> In case of any conflict, this document shall prevail; the list of differences is provided in its §9.
> The ruling was **officially recorded on the same day** (`py_src/core/storage/`), so the aforementioned entries describe the current situation.
The original “Alignment and Binary Format” page has been deleted; the remaining valid sections have been incorporated into the byte layout of the container.

**The current status and specifications of the kernel assembly (`Kernel`) and the command surface (`Api`) are described in [L0 存储设计](storage-design.md) §9**,
No longer to be given a separate page: That section contains only two items—“connecting a wire” and “a method table”—and assigning it its own page would inevitably result in a disjointed presentation, with §9 discussing matters separately.

**Current stance on the event layer**: Events only trigger notifications; they do not make decisions—there is no event parser in the core.
There is also no intermediary that goes from “analyzing the package” to “deciding what to do.” The event object and the bus are in `py_src/core/event/`,
The directory contains only two entries (`object.put`/`object.deleted`); `core/event/catalog.py` shall prevail.
**Subscriptions only occur in the event log** (`core/event/logs.py`): one-time subscription, routed according to the split table.
Diagnosis/Dumps/Feedback; a dump is an additional text record that does not count toward storage (see details in…).
§9.3).

## Not yet written

The following page was deleted during the rebuild on 2026-09-29; it is **currently not in the repository**. If needed, it should be rewritten using the code from that time.
And register it in `mkdocs.yml` ’s `nav`:

| Direction | Why wait |
|---|---|
| Data Structure Overview | The storage state follows the L0 specification; the logical and in-memory states will be finalized once the UI and domain teams return. |
| Domain (two branches of `feature` and file repositioning) | Domain layer to be rebuilt |
| Note model (row identity, range styling, versioning, and deduplication) | Domain layer to be rebuilt; only shapes are included |
| Embedded resources (visibility levels and P2P trust model) | Network not implemented |
| Design archives, networking and federation, ecosystems and plugins | Interface and networking pending implementation |

See the glossary; figures on each page are enclosed in [Mermaid](https://mermaid.js.org/).

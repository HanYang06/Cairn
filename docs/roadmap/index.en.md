<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- translation-source-hash: ce62bda231fed07d739fc993d2306fddf67d0f744a0fd0bd76866f6147e3111a -->
# Roadmap Structure Explanation

This page outlines the **format and maintenance standards** for the route maps listed below. The roadmap file only contains data.
>(Route Increment Version Allocation) – how to read it, how to write it, and how to modify it are all documented in this file.
>
The roadmap ranks first in the order of authority: **`路线图 > 设计 > 代码`** (see § Order of Authority for details).

-**Scope**: Each roadmap should cover only one version line (e.g., 1.x). Start a new paragraph on the next line (`2.x.md`)--
Splitting by version sequence prevents the system from becoming excessively large; each branch ends at its respective point, and thereafter only uncommitted versions are maintained—no further incremental updates are added.
-**Only track development roadmaps, not fixes**: Defect fixes and patch-related issues are never included in the roadmap. Entries are only added **voluntarily**.
Capabilities and decision-making are not merely a chronological record of “how much has been done”; the version number will not artificially increase simply due to bug fixes.
-**Top and bottom sections**: Collect all entries (the single source of truth), and associate entry IDs by version.
-**Route increments** are incremental in nature: new decisions are added as needed, and once completed, they are marked with a check. Items are nested hierarchically by category (Category → Module → Item).
-**Route ID**: A three-digit sequence number (001, 002, ...), **globally unique, assigned sequentially, and never reused**; renaming an entry does not change its ID.
The number is sequentially numbered throughout all roadmap documents (the largest number in the sequence is incremented downward), so it will not conflict with the second copy.
-**Entry Card**: Each entry consists of six fixed lines; leave any missing fields blank without deleting them—fields are columns, not part of the main text.
-`决策状态`:`已定` / `待裁` / `未定` / `未来项` / `已废弃`; the dash is followed by the specific meaning of that state.
-`设计关联文件`: On which page is the design caliber specified? Use relative links for internal references; use backtick paths for other locations within the warehouse.
    其中 `decisions/…` 指 `.agents/skills/memory/references/decisions/`，`rules/…` 指 `.agents/skills/rules/references/`。
-?: In which specific version does it appear—Version 1/Version 2/Version 3/Version 4; if undecided, write “Undecided”; if discarded, write “Discarded.”
-`具体实现文件`: Indicate where the code is located; if it has not yet been established, specify which level is missing—do not write “none.”
-`关联 issues / PR`:GitHub issue number;`未合` Marks PRs that have not yet been merged.
-**Checkbox**: Indicates that this item is **not in the to-do list**—it has been finalized or discarded; the two situations are distinguished by parentheses.
-**Closing**: No annotation is added after the entry name.
-**Deprecated**: Items that were once planned but are no longer being worked on, and for which there is **neither code nor design**—**do not delete**; instead, check the box and add `（已废弃）` after the item name.
    留痕是为后人不再重新提一遍。
-**Version Assignment**: Below each version number is the list of item IDs associated with that version. A version has only two states:
-**Published**: Marked with `（已发布）` after the title—this is a fixed value and will not change thereafter.
-**Unconfirmed route**: Mark the title with `（未落定路线）`, or leave it blank (which is the default). Allocations can still be adjusted—
    改分配是**纯增量**（条目只增不减、版本号只增不减），不视为推翻。
Deprecated entries are listed in `### 已废弃` and do not count toward the version number.
-**Entry Template**: For new entries, simply copy the six lines below, keeping the field order unchanged.

```text
> 路线ID:
> 决策状态:
> 设计关联文件:
> 分配实现版本:
> 具体实现文件:
> 关联 issues / PR:
```

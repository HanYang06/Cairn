<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- translation-source-hash: 5010c39f397eef78ede8374d3cba89613a9795e1f73a20d50e0f6589fe6c4af6 -->
# Glossary

> Words in the project have **clear meanings**; mixing them up will lead to misreading the code. Only words that can be misinterpreted when read are accepted here.
> Definitions shall be governed by the code and `docs/architecture/*.md`; this table serves only as an index.

## Storage (L0)

This section pertains to the **current situation** (October 2, 2026: the code was finalized; on the same day, it was revised once pursuant to the amended ruling; starting October 6, 2026: **no-guarantee generation**): and
> [块的组成与落点](../architecture/py_core/storage/block-parts.md) and
> [载体的字节布局](../architecture/py_core/storage/pack-format.md) Consistent,
It also corresponds one-to-one with the code of `py_src/core/storage/`; see [L0 存储设计](../architecture/storage-design.md) for the general outline.

| Word | Meaning | Not what it is |
|---|---|---|
| **vault** | Root directory: one index database plus several hub directories (path conventions are denoted by `core/storage/engine.py` and `core/init.py`) | Not an encryption container in the "safe" sense |
| **hub** | `<root>/<hub>/packs/`: Contains multiple carriers; `packs/` The presence of this directory serves as the criterion for defining it as a "hub" | Not a domain partition; was once referred to as a "bucket" in the code |
| **Cell** | The equal-length allocation unit within the container: each cell = 16 bytes of header + content | Not “the segment occupied by a single record” (the record concept has been deprecated) |
| **Attribute Slot/Body Slot** | Two uses for slots: the attribute slot holds a block’s **entire set of attributes** and can be overwritten in place; the body slot holds **body fragments** and only appends | Not two separate files, nor two different types of storage |
| **Segment List** | In the index‑table row, record the **entire set of slots** occupied by that block: use a single number for a single slot, and an interval for a contiguous range. The writing order is semantically structured (main-content slots first, attribute slots second), and the normalized form (ascending order, non-overlapping, adjacent segments merged, minimal number of segments) is used for recovery convergence and diagnosis. It does not follow a “head slot–tail slot” pairing (as in the old model); the writing side also does not align according to slot numbers; **references to content from elsewhere are not included in this coordinate system**.
| **Slot Type** | Each slot header indicates whether it is an attribute slot or a content slot (`pack.ATTR_SLOT` / `pack.BODY_SLOT`); when reading a block, the slot headers are read and sorted as needed | Not a column in the database (`attr_in_pack_slot` Deleted: Slot numbers are only meaningful within the pack) |
| **Block** | The foundation of a storage unit: it only has a table and can be persisted to disk and read back once it has an ID; field locations are declared using `Attr` / `Body` in the class body | It is neither a "file" nor a "container that automatically persists to disk just because it has an ID" |
| **`Attr`** | The **indexable** declaration on the class body (`title: str = Attr("")`): this field goes into the attribute slot **and also into the reverse table** | It is neither a half-switch that declares but does not index, nor a type criterion |
| **`Body`** | Content declaration on the class body (`lines: list[str] = Body([])`): This field goes into the main text slot and is deduplicated based on the content summary; when it hits an existing position, this block does not write to the body slot (reference type) | It is neither a “main text pointer carried by the block” nor a binding syntax |
| **Literal assignment** | `self.title = "…"`: Still written to disk, **without index support** | It’s not that it “can’t be written to disk” |
| **Main Text Summary** | `body` That column: **the summary of the current main text** (one, not a sequence); the location of the main text is given by the row index in the main-text index | Not the “block version number,” nor the **generation chain**—storage does not preserve generations (determined on 2026-10-06); it contains no slot numbers—slot numbers are meaningful only within a pack; inter-pack associations can only be tracked using summaries |
| **Self-contained/Referenced** | A block has two runtime states: if the body slot within this block’s position segment exists, it is **self-contained** (the content is in this block); if it does not exist, it is **referenced**, and the abstract in that column is used to look up the main text index to locate the corresponding line of the main text. | Not a column in the library (during loading, `_body_hash`/`_inline_body` are derived from the library row plus the slot header). |
| **Delete** | Remove the line from the index; the old bytes on the carrier are reclaimed. **The line for the main text index and the main text slot are retained**—recycling determines liveness by checking “Is there still a line?” and pointing to it; no tombstones are appended to the carrier anymore (the tombstone mechanism has been abolished along with this ruling); nor is the main text deleted as well.
| **Slot Header** | The first 16 bytes of each slot: Slot Type 1 + CRC32 checksum 4 + Content Length 4 + Reserved 7 | Not the header of data slots in the old model (32 bytes, including three attribution fields) |
| **ID** | The origin of the row in the index database: `name` / `value_uuid` / `birth_time` and the position segment; **it holds across packs and hubs** | Not a raw string; it also **no longer carries summary credentials** (`value_hash` has been moved out of the identity); slot numbers are not addressed at this level |
| **Carrier pack** | Carrier file: 24-byte header + a sequence of fixed-length records; randomly named, and a new file is created once the fill‑up line is reached | Not a package from a "package manager" |
| **Sealed** | **Strategic Judgment**: "There’s no room left for the next piece." | Not in a placed state (no sealing marker in the file). |
| **Index** | `<root>/catalog.db`: One type, one **identity table**; `hub` Registration; `meta`; **Authoritative Perspective**—Identity, location, and text abstract shall prevail. | Not the “portion calculated back from the carrier” (forward sweep reconstruction and cold start are now obsolete). |
| **Identity Table** | The table in the database that a type with an ID occupies: table name = type name, with exactly seven columns (six identity fields + `body`) | It is not a “declared table structure” (no declaration file); it also has one more column than the fields of `ID`; and it does not have a column specifying “which cells are attribute slots.” |
| **Index Block** | `AttrIndex` / `BodyIndex`: **Enhancement** -- Retrieve blocks by attribute, or retrieve its location based on the abstract of the main text; if absent, it cannot be found by value, and write operations degrade to deduplication | This is not a database indexing function; the main-text index entries do not record which block owns them ("who is using it" is computed on the fly from the summary column in each block) |
| **Forward Table/Reverse Table** | The forward table represents either “a certain column of a block equals a specific value” (in the attribute path) or “summary → the location of a piece of main text” (in the main-text path), with each row occupying a slot in the index block; the reverse table is **computed on the fly during reads and not stored**. The reverse table is **not written to disk**—if it were stored, it would require incremental maintenance, and missing even one entry would not result in an error, only in the inability to retrieve the corresponding data.
| **GC / `sweep`** | `core/storage/gc.py`’s `sweep(engine)`: **By index library**, collect live slots (the row’s position segment + **the body text position referenced by that column within the row**), and consolidate fragmented segments by grouping; **generations are not preserved**—as soon as that column is modified, the previous version of the body text immediately becomes a dead slot. | Not an engine method (a module-level function that returns `SweepReport`); the manual side is already usable, but on the automatic side there is only the criterion function `reclaimable_bytes`, **which has not been connected to the backend**. |

## Kernel

This section is the **current situation**. The naming scheme of the old main axis (`Core` / `Signal` / `ConfEngine`/
> `Managed`/Tool unit) was completely deleted along with the entire rebuild on 2026-09-29 (see Git for history).

| Word | Meaning | Not what it is |
|---|---|---|
| **Kernel** | Kernel assembly: library core + storage engine + event bus + event log(`core/init.py`); only handles four tasks: path conventions, `bind(engine)`, event log assembly, and hooking failures to the log | Does not have `store` / `load` / `patrol` / `repair` / `reindex` / `survey` / `compact` / `locate` |
| **bind/that thread** | The capability to connect to which library: **module-level, one thread per process**, | untied | Not "each block keeps track of where to write on its own" |
| **Bus/Event Bus** | Event engine: subscribes, delivers events in registration order, isolates exceptions, and returns a failure list (`core/event/bus.py`) | Makes no decisions and has no parser |
| **Event** | Event object (frozen): `type` / `source` / `subject` / `data` / `id` / `time`; field names follow the CloudEvents convention | Does not imply implementation of the specification; nor is it stored |
| **Event Catalog** | The kernel currently emits **two** type constants (`object.put` / `object.deleted`, `core/event/catalog.py`), which are used for both publishing and subscribing | Not three (`budget.exhausted` has been removed: the quota mechanism no longer exists) |
| **Event Log** | `core/event/logs.py` of `EventLog`: **The single, unique subscription** (one-time subscription `catalog.ALL`), which, according to the routing table, is split into three paths—diagnostics, disk persistence, and feedback; the persisted data is stored as a JSON Lines text file, and the storage location must be specified before creation. | **Not a stored record** (does not enter the carrier, no table is created, and no ID is assigned); nor is it a domain activity log (that pertains to business semantics and belongs to the domain layer). |
| **Storage Engine** | Block↔Slot: allocate hub/pack/slot, encode, write to disk, read back, extract block (`core/storage/engine.py`) | Unknown database |
| **Database Engine Index** | On the index side: create an identity table, write rows, look up positions by identity, register hubs (`core/storage/db/engine.py`) | Does not recognize slots/packs/hubs |
| **Exception Layer** | Level: Bottom layer, with granular subdivisions for the storage and control planes; integration with logging occurs via failure hooks in `Bus` | Do not declare exceptions that do not have throwing points; **does not include configuration-related exceptions** (those are handled by upstream OnConf exceptions) |
| **Configuration conf** | `core/conf.py` Only for assembly: set the configuration root (`CAIRN_CONFIG`) + disable console log output; `conf` is the upstream OnConf’s own function—declaration is implementation, and the value is written to a single-value file | Not the configuration file itself; **nor is it the engine** (the engine is upstream `onconf`); when retrieving values, do not copy default values |
| **Command-side API** | Method table for `core/api.py`, **seven methods** (`tables` / `hubs` / `rows` / `locate` / `record` / `stats` / `delete`): read and diagnostics | **No `store`** (writes are initiated by the domain block itself); does not decode domain payloads |

## Domain (Intent: To be rebuilt; Note: Landing point)

> The following are mostly target patterns that currently have no code (only the shape and its container).

| Word | Meaning | Not what it is |
|---|---|---|
| **Domain** | **Management Object**: Singleton, no ID; manages mechanisms and policies (`Note` / `Project`) | Not data |
| **Carrier (five)** | `NoteData` / `NoteTag` / `NoteGroup` / `NoteAsset` / `NoteCanvas`: Subclass, **has an ID and creates a table upon entry into the repository** | Not a "structure within the payload" |
| **Structure within the payload** | `NoteLine` / `Span` / `Heading` / `Chunk`/`Figure`, etc.: ordinary value objects—**no ID, not registered, no corresponding database table**; they exist only within the payload of their respective carriers | Not a carrier |
| **note body** | Body = **sequence of lines**(`list`), one element = one line | Not a string |
| **Span Style** | Inline range `[start, end)` + a KV pair (CSS property name → value), storing only non-default values | Not a block-level property |
| **Relation** | **Expressed by the block itself** (the block specifies its relationships); the library only maintains indexes—relationship indexing has not yet been designed and is not pre-populated | Not a field; no longer a “first-class DB row” (the table was deleted on 2026-09-30) |
| **Normalized byte layer of the domain payload** | Landing point `py_src/model/note/format/`,**not landed**:`cbor2` Unable to generate a dataclass, so when `NoteData.lines` placing `NoteLine` objects, they cannot be stored | It is not the case that "row objects can already be stored" |

## Interface (Intent: Tauri shell web frontend)

> The following are mostly target patterns for which **no code currently exists**; the engineering implementation is in the Tauri‑wrapped web frontend.

| Word | Meaning |
|---|---|
| **ui_tools** | A UI **toolbox** from the Qt era (declaration tree/compilation/binding/model/theme): the layer name has been deprecated along with Qt, and its responsibilities are now handled by frontend shared components |
| **App** | Application **composition root/orchestration layer**: composes the core, domain, and UI; the Python-side entry point is `py_src/app/` (currently only as a sidecar), while the UI side is a Tauri shell |
| **Facet** | A complete UI definition for a domain (combining the analyzer, organizer, and wrapper into one), handed over to the app for compilation and mounting (the Qt implementation has been deprecated; its future remains undecided). |
| **Slot** | A **named slot** in the app’s root structure (`expects=` declares which component belongs to which slot; same as above, to be determined) |
| **token / Theme** | Appearance token **closed vocabulary** (the sole source of truth `config/theme/tokens.json`) → `gen:tokens` generates `tokens.css`, `check:tokens` to prevent drift; components only reference `token.*`, prohibiting hardcoding |


## Project

| Word | Meaning |
|---|---|
| **Enterprise-Level-ε** | Quality criteria for this project: Enterprise-level, with an additional half-step reduction in stringency (strict mode/Ruff ALL/zero tolerance for warnings/coverage ≥80%) |
| **Memory** | `.agents/skills/memory/references/`:**Decision-making** (one topic per file, only record the current status) and **Progress** (only record tasks that have not been completed), dynamic and editable files |
| **Rules** | `.agents/skills/rules/references/`: Constraints and red lines, distributed by scenario |
| **REUSE.toml** | Centrally declares the licenses of files that cannot fit an SPDX header (using REUSE’s data format; tool developed in-house) |

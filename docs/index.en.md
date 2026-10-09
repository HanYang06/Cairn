<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Cairn

> **A local-first content-addressed object pool** — notes, assets and projects in one workbench.

[:octicons-rocket-24: Quickstart](guides/quickstart.md){ .md-button .md-button--primary }

---

## What this is

Cairn stores content in a **content-addressed object pool**: bodies are deduplicated by digest and
addressed by a stable identity, on top of plain files (`<root>/<hub>/packs/*.pack`) plus an
**index database** (`<root>/catalog.db`) that is authoritative for identity, location and body
digest. Applications are only consumers.

| Common question | Cairn's answer |
|---|---|
| Where is my data | Plain files plus a SQLite index (authoritative for **identity, location and body digest**; packs only hold values). No proprietary format, no cloud |
| Can I be locked in | Apache-2.0; **not encrypted** locally, stored in the clear, readable with any other tool at any time |
| Why not Obsidian / Notion | Those are note-taking apps; Cairn is an object pool plus a workbench, and a note is only one kind of object |
| Can I use it now | **Not yet.** The kernel is in place and the UI is being rebuilt — see below |

## Status

Early development, **not released** (`0.0.1` / pre-alpha).

- ✅ **L0 storage is in place**: the kernel (`py_src/core/`) and the note domain shape layer
  (`py_src/model/note/`) are importable and testable; on-disk rules follow
  [L0 storage design](architecture/storage-design.md).
- **Under reconstruction**: the domain layer (the former `feature` package was deleted; the current
  landing spot is `py_src/model/note/`), and the UI (the Tauri shell and the Python sidecar are
  wired, but the interface is incomplete).
- **Not started**: byte-level reclamation (GC, `core/storage/gc.py` holds nothing but an SPDX
  header today), the byte-normalisation layer for domain payloads (`py_src/model/note/format/` —
  which is why line objects inside `NoteData.lines` cannot be persisted), cross-line transactions
  and crash recovery, large-body chunking, search, P2P / server, packaging and a desktop entry
  point.

What gets built next is decided by the [roadmap](roadmap/1.x.md) (**authority order: roadmap >
design > code**); the source of truth for progress is the code itself. For which design pages
describe the current state and which only describe intent, see the
[architecture index](architecture/index.md): the pages in the repository today are L0 storage
design, the block model, the configuration engine and the UI theme.

## Where the docs come from

1. **Hand-written docs** — `docs/**/*.md` and the docstrings under `py_src/**` are the source of
   truth; they are committed and reviewed together with the code.
2. **Generated** — every signature, type and docstring in the [API reference](api/index.md) is
   extracted from the source by [mkdocstrings](https://mkdocstrings.github.io/); there is no second
   copy. The built site (`site/`) is a build artefact and is not committed.

See [how to edit the docs](contributing.md#editing-the-docs) for the workflow. **Translations are
partial**: English is the default language and Chinese is the translation; a page that has no
`.zh.md` file yet falls back to the English text.

## License

Copyright &copy; 2026 HanYang06 · [Apache-2.0](contributing.md#license-and-attribution).
Keep `LICENSE` and `NOTICE` with any redistribution.

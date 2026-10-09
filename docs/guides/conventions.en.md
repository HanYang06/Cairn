<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Conventions and red lines

> This page expands the red lines in `AGENTS.md`, rearranged by scenario. The full rules and their
> reasons live in `.agents/skills/rules/references/`; this page is navigation and key points only,
> and that directory wins on any conflict.

## 1. Licensing

- This project is **Apache-2.0**, and **GPL / AGPL dependencies are forbidden** (their copyleft
  terms would turn this project into GPL).
- **Permissive licences are allowed**: MIT / ISC / BSD / Apache-2.0 — usable commercially and in
  closed distributions. `mkdocs-material` (MIT) and `mkdocstrings-python` (ISC), used by this site,
  belong to that group.
- **Non-commercial licences** (CC-BY-NC, PolyForm NC and the like) conflict with this project's
  commercial goal and are not adopted.
- Verify the licence of a third-party theme, canvas or editor library **before adopting it**. A new
  third-party skill stays exactly as upstream, with its origin and hash recorded in
  `skills-lock.json` and `NOTICE` updated when needed. The full policy and tool list are in
  [License and attribution](../contributing.md#license-and-attribution).

## 2. SPDX headers

Every source file and document starts with:

```
SPDX-FileCopyrightText: 2026 HanYang06
SPDX-License-Identifier: Apache-2.0
```

`.py` uses `#`, `.md` uses `<!-- -->`, `.iss` uses `;`; in `SKILL.md` the header follows the YAML
frontmatter.

| Layer | Means |
|---|---|
| **Write** | `uv run python scripts/spdx.py --fix` (the pre-commit hook is wired and inserts it automatically) |
| **Check** | `uv run python scripts/spdx.py --check` (missing header, wrong year or a `SKILL.md` without `license:` exits non-zero) |
| **Fallback** | The root `REUSE.toml` declares centrally every file that cannot carry a header (images, JSON, lockfiles, legal texts, vendored code) |

- **Never copy it by hand**: the hook inserts headers into new files. It exits non-zero when it
  does (a modified file counts as failure there), so `git add` again and commit.
- **When a new file type appears**: if it can carry a comment, add it to `_COMMENT_STYLES` in
  `scripts/spdx.py` (files without an extension are claimed via `_NAMED_STYLES`); if it cannot,
  add it to `REUSE.toml`. When neither applies, `--check` reports it as unclassified.
- **The `reuse` CLI is not adopted**: `fsfe/reuse-tool` is GPL-3.0-or-later, which violates this
  project's licence red line. Only the `REUSE.toml` **data format** it defines is used, read and
  written by `scripts/spdx.py`.

## 3. Layer boundaries

```text
Python side (py_src/):
  core(L0)  ←  feature(L3)  ←  app(composition root)   -- only core exists today

Interface side (app/):
  Tauri shell (Rust)  ←  Web frontend (atoms → composites → pages)
```

- `py_src/core/` (the kernel: events / storage / configuration / exceptions) **must be Qt-free and
  transport-agnostic**.
- `py_src/feature/` (**to be rebuilt**) depends only on the public `core` API. **Domains never
  depend on each other**; cross-domain work belongs to `app`.
- The interface side **never imports the domain and never touches `core.storage`**; it crosses the
  boundary through the command surface only, and the **Tauri shell holds no business logic**. See
  `.agents/skills/rules/references/ui-boundary.md` for the details.
- **Only the composition root knows the domain**: it builds domain services and injects them, and
  the interface never instantiates domain objects.
- Domain structures **inherit `Block` directly** and may not modify its top-level fields; extension
  happens through subclass fields, a new `type`, or a new relation `kind`.

The test: **a new developer can understand the interface without first mastering hub / Block; if
not, the boundary has failed.**

## 4. Data conventions

- Internal time is **unix milliseconds** everywhere (`now_ms` in `core/clock.py`); an ID's
  `birth_time` uses nanoseconds.
- Object identity is the **`ID`** in `py_src/core/storage/db/id.py` (identity belongs to the
  database side — it is where the index comes from): the fields are `name` (derived by the holder,
  and the table name comes from it), `value_uuid`, `birth_time` and the location segment.
  **`value_hash` was moved out of identity by the ruling of 2026-10-02** — deduplication covers
  only the content of a `Body`, through the body index block. A store's columns are `ID_FIELDS`
  plus **the body digest column** (`body`), seven columns exactly.
- **A field's placement is declared on the class body** (`Attr` / `Body` in
  `core/storage/types.py`): using `Attr` puts it in the reverse table, using `Body` puts it in a
  **body slot**, and **there is no `indexed=` style switch**; a bare assignment is persisted just
  the same.
- **Table names are derived from the class name alone** (`type(self).__name__.lower()`): there is no
  `__table__` override and no schema declaration file, so the tables in a store follow from whether
  a type uses `ID`.
- **Unimplemented design is marked "reserved / draft"**; documentation must never present
  unimplemented behaviour as implemented.

## 5. Quality gates (enterprise-ε)

- `mypy strict` (covering `py_src` + `tools` + `scripts` + `tests`), `ruff select=ALL` with a
  per-rule justified ignore list, and mandatory `ruff format`.
- **Zero tolerance for warnings** (pytest `filterwarnings = ["error"]`); line and branch coverage
  **>= 80%**.
- **One command before committing**: `uv run pre-commit run --all-files` (13 hooks; the list and the
  criteria are in `.agents/skills/rules/references/quality.md` §4). Install the hooks once with
  `uv run pre-commit install`; without that the configuration exists but no gate runs.

## 6. Docs and commits

- The repository's working language is **Chinese**: docs, comments and commit messages are written
  in Chinese, and commits follow Conventional Commits (`feat(ui): …`).
- **The docs site is bilingual, and Chinese is the basis of truth**: the Chinese pages
  (`docs/**/*.md`) are what the author writes, and the English pages (`docs/**/*.en.md`) are
  **machine-translated** from them (the policy and the list of translated pages are in
  [Translation status](../reference/i18n-status.md)). The file name is the whole test — **the copy
  without a suffix is the original.** Change a Chinese page and its English counterpart has to be
  re-translated; the two must never sit on two different versions.
- **Authority order `roadmap > design > code`** (the roadmap decides *what*, the code records
  *what exists*); after changing the implementation, write `docs/architecture/*.md` back, and never
  leave documentation that contradicts the code.

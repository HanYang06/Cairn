<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Contributing and licensing

Cairn is early. Read [Conventions and red lines](guides/conventions.md) before opening a change:
licensing, SPDX headers and layering are the three lines CI enforces.

## How to take part

| Goal | Where to go |
|---|---|
| Set up the environment, run tests | [Development](guides/development.md) |
| Look up what a term means | [Glossary](reference/glossary.md) |
| Understand a design decision | `docs/architecture/**` (state vs. intent: see the [architecture index](architecture/index.md)) |
| Look up a class or function signature | [API reference](api/index.md) |
| Edit or add a docs page | [Editing the docs](#editing-the-docs) |
| Check licence and attribution requirements | [License and attribution](#license-and-attribution) |

## Commit conventions

- Commit messages follow **Conventional Commits** with a Chinese description:
  `feat(core): …` / `fix(ui): …` / `docs: …`.
- Run `uv run pre-commit run --all-files` before committing (13 hooks, listed in
  `.agents/skills/rules/references/quality.md` §4). Install the hooks once with
  `uv run pre-commit install`.
- CI (`.github/workflows/ci.yml`) runs the same gates, plus a coverage floor of 80%.

## Reporting problems

Repository: [github.com/HanYang06/cairn](https://github.com/HanYang06/cairn).
Include **the smallest reproducible steps**. For anything involving data, give the vault root
(`CAIRN_VAULT`) and the sequence of operations, and **do not attach real note content**.

## Editing the docs

### Two kinds of content, two sets of rules

| Kind | Where | Maintained by |
|---|---|---|
| **Hand-written docs** (source of truth) | `docs/**/*.md`, `README.md`, docstrings under `py_src/**` | People; reviewed together with the code |
| **Generated** | signatures / types / docstrings in the [API reference](api/index.md), the whole of `site/` | Tools; never edit by hand |

**Never hand-write API documentation**: signatures, parameters and return types are extracted from
docstrings and type annotations by [mkdocstrings](https://mkdocstrings.github.io/). A code change
updates the page, a docstring change updates its description.

### Two languages

English is the **default language** (`docs/**/*.md`) and Chinese is the **translation**
(`docs/**/*.zh.md`). The rule the build follows is: **a file carrying a `.<locale>` suffix is a
translation; a file without one belongs to the default language.** English therefore lives at the
site root and Chinese under `/zh/`.

- Adding or editing a page means adding or editing **both** files; a missing counterpart makes the
  reader fall back to the other language.
- The Chinese file is the one written first for domain-heavy pages (it carries the original
  terminology), and the English file is translated from it.
- Both files must be registered in `mkdocs.yml` under `nav:` as a single entry — the suffix is not
  written there.

### Adding a page

1. Create the `.md` files under `docs/` (`guides/` for how-to, `architecture/` for design,
   `reference/` for lookups).
2. **Add the SPDX header** at the top (two `<!-- -->` lines). If it is missing, pre-commit inserts
   it and exits non-zero; `git add` again and commit.
3. Register the page in `mkdocs.yml` under `nav:`. **An unregistered page is still built but never
   appears in the navigation**, and `--strict` does not report it.
4. Preview and gate locally:

```powershell
uv run mkdocs serve            # http://127.0.0.1:8000 (hot reload)
uv run mkdocs build --strict   # same bar as CI: broken links / missing pages / unknown config fail
```

### Writing style

- Chinese prose for the Chinese files; terminology follows the [glossary](reference/glossary.md)
  and inventing synonyms is not allowed.
- **Never describe unimplemented behaviour as implemented**: mark it "reserved / draft / open" and
  state the current situation.
- **The authority order is `roadmap > design > code`**: the roadmap decides *what* to build, the
  code records *what exists*. When `docs/architecture/*.md` and the implementation disagree, change
  the implementation and then **write the docs back** — that write-back is part of the task.
- Use file-relative links (`../architecture/storage-design.md`); `--strict` reports broken ones.
- Draw diagrams with [Mermaid](https://mermaid.js.org/) fenced blocks (` ```mermaid `), which render
  both here and on GitHub.

### Adding an API page

`docs/api/*.md` holds mkdocstrings directives, for example:

````markdown
# core (foundation)

::: core
    options:
      members: false
````

- `::: module.path` recursively renders the public members of that module (`filters` already
  excludes `_private`).
- Top-level packages **drop the `cairn.` prefix**; `paths: [py_src]` is configured in `mkdocs.yml`,
  so `core` is enough.
- Render selected classes only: `members: [Kernel, Bus]`; a standalone page: `::: core.init.Kernel`.

### Build output and deployment

- `site/` is a **build artefact and is not committed** (git-ignored, and declared centrally in
  `REUSE.toml`).
- Deployment is handled by `.github/workflows/docs.yml`: document changes on `main` → drift check →
  strict build → GitHub Pages (official Pages actions, no `gh-pages` branch).
- Only one workflow may publish to Pages per repository. Enabling Pages can make GitHub generate
  `jekyll-gh-pages.yml` (which builds from the repository root); it competes with `docs.yml` for the
  same `github-pages` environment and makes the site alternate between two versions. Delete it if it
  reappears.

## License and attribution

### This project

Copyright 2026 HanYang06 · **Apache License 2.0**.

Keep [`LICENSE`](https://github.com/HanYang06/cairn/blob/main/LICENSE) and
[`NOTICE`](https://github.com/HanYang06/cairn/blob/main/NOTICE) with any redistribution.

### Dependency licence policy

| Kind | Verdict |
|---|---|
| MIT / ISC / BSD / Apache-2.0 | **Allowed**: permissive, usable commercially and in closed distributions |
| **GPL / AGPL** | **Not allowed**: copyleft terms would turn this project into GPL |
| Non-commercial licences (CC-BY-NC, PolyForm NC) | Conflicts with the "usable commercially" goal; not adopted |

- The same standard applies to development-time tools: `fsfe/reuse-tool` is GPL-3.0-or-later, so the
  **`reuse` CLI is not adopted**; only the `REUSE.toml` **data format** is used, read and written by
  the in-house `scripts/spdx.py`.
- Re-check the licence statements in `NOTICE` and `pyproject.toml` after adding a dependency; verify
  the licence of a third-party theme, canvas or editor library *before* adopting it.

#### Tools used by this site (build-time dependencies, not shipped)

| Tool | Licence |
|---|---|
| [MkDocs](https://www.mkdocs.org/) | BSD-2-Clause |
| [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) | MIT |
| [mkdocstrings](https://mkdocstrings.github.io/) / `mkdocstrings-python` / Griffe | ISC |
| [mkdocs-static-i18n](https://github.com/ultrabug/mkdocs-static-i18n) | MIT |

### Sources and attribution

- The **SPDX header** at the top of every source file and document is the machine-readable form of
  that licence statement; `scripts/spdx.py` inserts and checks it, so it must not be written by hand
  (see [Conventions and red lines](guides/conventions.md) §2).
- Files that cannot carry a comment (images, JSON, lockfiles, legal texts, vendored code) are
  declared centrally in the root `REUSE.toml`.
- Vendored third-party skills stay exactly as upstream; their origin and hash are recorded in
  `skills-lock.json`.

### Full texts

#### LICENSE

```text
--8<-- "LICENSE"
```

#### NOTICE

```text
--8<-- "NOTICE"
```

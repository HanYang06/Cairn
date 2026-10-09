<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Translation status

How this site is localised (decided 2026-10-10):

- **Chinese is the basis of truth** (`docs/**/*.md`, served at `/`) — it is what the author writes:
  the terminology, the design pages and the roadmap are authored in Chinese.
- **English is machine-translated** (`docs/**/*.en.md`, served at `/en/`) — the intent is for it to
  be produced by a translation model in CI, not written page by page.

The rule the build follows is therefore about the file name alone: **a file carrying a `.locale`
suffix is a translation; a file without one belongs to the default language.** "Which copy is the
source?" never needs a judgement call — **the one without a suffix is.**

This is a straightforward form of internationalisation: **the product is usable in English, while
the author writes in their mother tongue.** What it trades away is the root URL — an English reader
lands on the Chinese page at `/` and switches with the language selector in the header. The
selector **stays on the current page**, so switching never drops you back to the homepage.

> **Six English pages are hand-written today** (this page, the home page, the three guides and the
> contributing page); the machine-translation flow is not wired up yet. Once it is, it **will not
> overwrite an existing English page by default** — it fills in the missing ones only, unless a
> re-translation is requested explicitly.

## What is translated

| Page | Chinese (source) | English |
|---|---|---|
| `index` | ✅ | ✅ |
| `guides/quickstart` | ✅ | ✅ |
| `guides/development` | ✅ | ✅ |
| `guides/conventions` | ✅ | ✅ |
| `contributing` | ✅ | ✅ |
| `reference/i18n-status` | ✅ (this page) | ✅ |
| `reference/glossary` | ✅ | — |
| `reference/config` | ✅ (generated) | — |
| `architecture/index` | ✅ | — |
| `architecture/storage-design` | ✅ | — |
| `architecture/block-model` | ✅ | — |
| `architecture/py_core/config` | ✅ | — |
| `architecture/py_core/storage/block-parts` | ✅ | — |
| `architecture/py_core/storage/pack-format` | ✅ | — |
| `architecture/py_core/storage/query-path` | ✅ | — |
| `architecture/ui_design/ui-theme` | ✅ | — |
| `roadmap/1.x` | ✅ | — |
| `roadmap/index` | ✅ | — |
| `api/index` | ✅ | — |
| `api/core` | ✅ (generated) | — |

The **architecture, roadmap and API reference pages are deliberately last**: their wording is still
moving, and a translation of a page that is about to be rewritten has to be written twice. The
architecture and API pages are also mostly code-adjacent, where an English reader can follow the
original with the [glossary](glossary.md) at hand.

A page without an English counterpart is **rendered from the Chinese source** under `/en/` (that is
`fallback_to_default`). Nothing is missing from the English site; some of it is simply still Chinese,
and the page carries no marker saying so. Treat the table above as the marker.

## How a page gets translated

1. Write or update the **Chinese** page (`docs/path/page.md`). **It is the original**, and the
   terminology is coined there.
2. English is produced as `docs/path/page.en.md` by `scripts/translate.py` using **machine
   translation** (Alibaba Cloud Machine Translation, `TranslateGeneral`; the RPC signature is
   computed with the standard library, so **no SDK is pulled in**). Three hard constraints are
   enforced in the script:
   - **translate the prose only**: fenced code blocks are kept whole, and inline code, links, images
     and bare URLs are lifted into placeholders and put back afterwards (translating them breaks
     links and anchors); table separator rows are left alone;
   - **translate incrementally, never from scratch**: each run only touches pages whose English
     counterpart is **missing** or **stale**, and pages that already match are **not sent at all**.
     Once a translation is committed, later runs cost only the delta;
   - the API accepts at most 5000 characters per request, so documents are split by line. The result
     **lands as a pull request**, so the terminology pass has a human in the loop.

> **Committing is the point of that step**: a translation is only durable once it is on `main`.
> `translate.yml` commits the output to its own branch and opens a pull request — merging it makes
> those `.en.md` files part of the repository, and the next run skips them. **There is no "translate
> everything again every time"**, as long as the pull request is merged. When a Chinese page changes
> and its English counterpart has not followed, the generator re-translates **that page alone**
> (using the same test as `--check`). The hand-written pages (no digest line) are left untouched by
> default; run `--stamp` once to add the digest line and bring them under drift tracking (it writes
> the line only, never the prose).
3. Register the page once in `mkdocs.yml` under `nav:` (the suffix is not written there); for the
   English navigation, add the entry under the `i18n` plugin's `languages[en].nav`.
4. Run `uv run mkdocs build --strict`. The language selector and the `hreflang` links are generated
   by the `i18n` plugin, so no URL is written by hand.

```powershell
uv run python scripts/translate.py --list      # report: which pages are pending, how many characters
uv run python scripts/translate.py --check     # gate: a stale English page exits non-zero
uv run python scripts/translate.py --report    # same test as --check, but never fails
uv run python scripts/translate.py             # translate the missing or stale pages
uv run python scripts/translate.py --stamp     # add the digest line to hand-written pages only
uv run python scripts/translate.py --force     # re-translate everything, matched pages included
uv run python scripts/translate.py --probe     # endpoint self-check: two characters, credentials / signature / endpoint
```

**Quota and setup**: the general-purpose edition gives the **main account 1,000,000 free characters
per month**, then 50 CNY per million characters. This site's Chinese source is about 95,000
characters, so translating all of it uses under 10% of the free tier — **the real cost is zero**.
CI needs a RAM access key **scoped to `alimt:TranslateGeneral` only** (never the main-account key),
stored as the secrets `ALIBABA_CLOUD_ACCESS_KEY_ID` / `ALIBABA_CLOUD_ACCESS_KEY_SECRET`; when they
are absent the whole translation job is skipped and merging is unaffected.

**How drift is detected**: the head of every English file carries
`<!-- translation-source-hash: … -->`, a digest of the Chinese source. `--check` compares the two and
reports a stale page when they differ. Fourteen pages are still untranslated, so the workflow runs
`--report` instead — **the very same test as `--check`, only it does not fail the job** — and putting
`--check` back turns it into a real gate once the translations are in. Do **not** reach for
`continue-on-error`: on the step and on the job alike it leaves the job's conclusion unchanged, and was
measured twice still reporting failure.

**Endpoint self-check**: `--probe` sends two characters and answers "are the credentials right, does the
signature pass, is the endpoint reachable" in one call. It runs in two places — inside the `translate`
job, before any quota is spent, and in a dedicated `probe` job on pull requests, limited to **branches in
this repository** because a fork's pull request never receives the secrets. **Why a job of its own**: the
`translate` job is skipped on pull requests by an `if` (it creates a branch and opens a pull request, and
a pull request should not have a second writer), so if the probe lived only inside it, "did the request
assembly get fixed?" would never have an answer on a branch — the first real run would be on `main` after
the merge, which is exactly how both red runs happened.

Two build details worth knowing before touching the config:

- **`fallback_to_default` renders the untranslated pages a second time**, so every symbol in the
  generated API pages exists under two URLs. `mkdocs-autorefs` warns once per symbol unless
  `resolve_closest: true` is set (it is, in `mkdocs.yml`): with it, each page links to the copy
  nearest to itself and the warning disappears.
- **The language selector needs whole-page navigation**: `navigation.instant` is incompatible with
  it and is therefore disabled.

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

> **All 20 Chinese pages now have an English version** (2026-10-10). Six of them — this page, the home
> page, the three guides and the contributing page — are **hand-written**, from before the
> machine-translation flow was wired up: their heads carry no digest line, so the generator leaves them
> alone by default (run `--stamp` to bring one under drift tracking). The other 14 are produced by
> machine translation in CI and carry a `translation-source-hash`, so "the Chinese changed and the
> English did not follow" is caught by `--check`.

## What is translated

| Page | Chinese (source) | English |
|---|---|---|
| `index` | ✅ | ✅ (hand-written) |
| `guides/quickstart` | ✅ | ✅ (hand-written) |
| `guides/development` | ✅ | ✅ (hand-written) |
| `guides/conventions` | ✅ | ✅ (hand-written) |
| `contributing` | ✅ | ✅ (hand-written) |
| `reference/i18n-status` | ✅ (this page) | ✅ (hand-written) |
| `reference/glossary` | ✅ | ✅ (machine) |
| `reference/config` | ✅ (generated) | ✅ (machine) |
| `architecture/index` | ✅ | ✅ (machine) |
| `architecture/storage-design` | ✅ | ✅ (machine) |
| `architecture/block-model` | ✅ | ✅ (machine) |
| `architecture/py_core/config` | ✅ | ✅ (machine) |
| `architecture/py_core/storage/block-parts` | ✅ | ✅ (machine) |
| `architecture/py_core/storage/pack-format` | ✅ | ✅ (machine) |
| `architecture/py_core/storage/query-path` | ✅ | ✅ (machine) |
| `architecture/ui_design/ui-theme` | ✅ | ✅ (machine) |
| `roadmap/1.x` | ✅ | ✅ (machine) |
| `roadmap/index` | ✅ | ✅ (machine) |
| `api/index` | ✅ | ✅ (machine) |
| `api/core` | ✅ | ✅ (machine) |

The architecture, roadmap and API reference pages were deliberately last (their wording was still
moving, and translating a page that is about to be rewritten means writing it twice); they were all
translated on 2026-10-10. **This table should carry no `—` from now on**: a newly added page simply
goes through "How a page gets translated" below.

`fallback_to_default` is still on, but **no page uses it right now**: a page without an English
counterpart is rendered from the Chinese source under `/en/`, and the English site is currently
complete. While a new page exists only in Chinese, `/en/` shows the Chinese text and the page carries
no marker saying so — treat the table above as the marker then.

## How a page gets translated

1. Write or update the **Chinese** page (`docs/path/page.md`). **It is the original**, and the
   terminology is coined there.
2. English is produced as `docs/path/page.en.md` by `scripts/translate.py` using **machine
   translation** (Alibaba Cloud Machine Translation, `TranslateGeneral`; **both the signature and the
   request shape are copied from the official SDK**, which is not pulled in: `POST` with a form body,
   so the prose never enters the URL, and the signature itself is percent-encoded once). Four hard
   constraints are enforced in the script:
   - **translate the prose only**: fenced code blocks are kept whole, and inline code, links, images
     and bare URLs are lifted into placeholders and put back afterwards (translating them breaks
     links and anchors); table separator rows are left alone; and **a line that is nothing but
     placeholders and punctuation is not sent at all** — sending it makes the model emit `?`, which is
     how the licence header got mangled once;
   - **translate incrementally, never from scratch**: each run only touches pages whose English
     counterpart is **missing** or **stale**, and pages that already match are **not sent at all**.
     Once a translation is committed, later runs cost only the delta;
   - **translate concurrently** (8 in flight by default, `--jobs` to change it): one round trip takes
     about 1.1 seconds, so 20 pages take a dozen minutes serially and two or three concurrently;
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
reports a stale page when they differ. **That check is now the real gate** in the `drift` job (it went
back from `--report` to the default once all 20 pages were translated on 2026-10-10) — the six
hand-written pages carry no digest line and take no part in it. Do **not** reach for
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

**Two triggers, one job each** (so the same tree is not scanned twice): `drift` and `probe` run **on pull
requests only** — they are the checks that must be visible before a merge — while a `push` to `main` runs
the **writer** alone (translate → open a pull request), because that is the one that changes the
repository. How many pages are still pending on `main` is in the writer's own log, so there is nothing to
scan again. Touching the workflow file itself does not trigger a `main` translation either (it is absent
from the `push` `paths`; the pull-request side keeps it, so a change to it is still exercised before the
merge).

**How to exercise the whole path before merging**: `workflow_dispatch` with `dry=true` really calls the
API for the whole batch but **commits nothing and opens no pull request** — the writer only runs on a
`main` push, so this is the one place where the translation path can be run for real before the merge.

Two build details worth knowing before touching the config:

- **`fallback_to_default` renders the untranslated pages a second time**, so every symbol in the
  generated API pages exists under two URLs. `mkdocs-autorefs` warns once per symbol unless
  `resolve_closest: true` is set (it is, in `mkdocs.yml`): with it, each page links to the copy
  nearest to itself and the warning disappears.
- **The language selector needs whole-page navigation**: `navigation.instant` is incompatible with
  it and is therefore disabled.

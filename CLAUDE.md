# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A personal daily-notes / TIL site. Each day Claude curates the day's material (typically pasted AI explanations handed over by the author) into one or more **記録** (records) written in Markdown, compiled to a standalone static HTML page. Published at https://niteview2435.github.io/til/ (repo `niteview2435/til`, renamed from `daily-proof` in the TIL pivot — the old `/daily-proof/` URL is dead, GitHub Pages does not redirect it). The daily `git` commits double as the continuity record (the GitHub contribution graph). Note this repo's history still carries the old `daily-proof` name in places; that is cosmetic.

**Division of labour:** the author supplies raw material (often AI output) and says roughly what it is; **Claude** shapes it into clean Markdown, decides the record/block structure, ordering, and placement, and files each record under a field in `theme_map.json`. `build.py` compiles.

## Commands

- `make new` — scaffold today's `records/YYYY-MM-DD.md` from a template (no-op if it exists)
- `make build` — regenerate the whole site into `docs/` (`python3 build.py`)
- `make serve` — build, then preview at http://localhost:8000
- `make clean` — remove `docs/`

There are no tests and no linter. The dev shell (via `flake.nix` + direnv, or `nix develop`) only provides `python3` and `make`; `build.py` is pure standard library, so plain `python3 build.py` works without the shell.

## Deploy model (important)

Pages source is **GitHub Actions**, not a branch folder. On push to `main`, `.github/workflows/pages.yml` runs `python3 build.py` and deploys `docs/`.

- **A commit alone changes nothing live — you must `push`.** Push triggers build + deploy automatically.
- `docs/` is **git-ignored and not committed**; CI regenerates it. Do not re-add it to tracking.
- Local `make build` is only for previewing; never commit the output.

## Architecture

Single-file generator `build.py` (stdlib only). Math is rendered **client-side by MathJax** — the build never shells out to a TeX engine.

Source → one file per day: `records/YYYY-MM-DD.md`. The date comes from the filename (no frontmatter). A file may contain:
- an optional leading `tags:` line (comma / 、 / space separated) before the first heading, and
- one or more **records** (記録), each opened by a single-`#` line. The `#` line's text is an optional **title**; a day with more than one record auto-numbers them `記録 1 / 記録 2 / …` (the title rides beside the number, in parentheses), while a lone record shows just its title (or nothing). Within a record, `##` lines slice the prose into **blocks** (the `##` text is the block heading, shown gothic). `###`–`######` are ordinary sub-headings *inside* a block. Content before the first `#` forms an implicit leading record; content before the first `##` in a record is a heading-less block. Empty blocks (and records with no non-empty block) are dropped.

`build.py` pipeline:
- `parse_records()` → list of `(title, blocks)` records, where `blocks` is `[(heading, content), …]` in document order; `parse_tags()` → tag list.
- `md_to_html()` is a small-but-real Markdown subset, enough to render pasted AI explanations faithfully: `###`–`######` headings, paragraphs, unordered (`-`/`*`) **and** ordered (`1.`) lists with lazy continuation, blockquotes (`>`), GFM pipe tables, fenced code blocks (```` ``` ````), and `**bold**`/`*italic*`/`` `code` ``. `render_blocks()` is the shared block tokenizer (blockquotes recurse through it). A rule line (`---`/`***`/`___`) is a block separator only — no `<hr>` is emitted. `render_inline()` is the inline-only variant used for titles/headings.
- Math safety: `protect_math()`/`restore_math()` swap `$...$` and `$$...$$` spans for placeholders **around** the Markdown pass so Markdown can't mangle them, then restore the raw TeX for MathJax.
- `render_records(records, eyebrow_html, with_divider)` emits stacked `<section>`s: an optional `<h2 class="record-label">` per record (`記録 N` + title), then one `<section class="block reveal">` per block (`<h3 class="label">` heading + `<div class="body">`). `eyebrow_html` (the date, on day pages) rides above the first section; the divider `<hr>` rides inside the **last** section when `with_divider` is set. There is no proof-specific machinery any more (no `SECTION_KINDS`, no auto-∎). Tags are deliberately **not** rendered — they go only into `index.json`.
- Theme articles (分野記事): the reorganisation unit is now the **record**. `assign_days_into_themes()` files each of a day's records under its theme and `render_theme()` stacks a theme's records oldest-first — titled by their record heading, with **no** source-day eyebrow and **no** dividers. This is a read-later **reorganisation layer over the daily log** — the daily pages remain the primary artifact.
- `DAY_TEMPLATE` / `THEME_TEMPLATE` / `INDEX_TEMPLATE` are `str.format` templates. Literal braces in a template must be doubled (`{{ }}`) — see the MathJax config block. Substituted values may safely contain `{ }` (e.g. `\frac{}{}`).

`theme_map.json` (repo root, **hand-maintained by Claude — the author never touches it**): `{themes: [{name, slug}], assign: {YYYY-MM-DD: name | [name, …]}}`. Themes are kept **broad** (a few standing fields like 高校数学 / 確率論 / 位相空間論); new records accrete into existing themes rather than spawning a narrow new one, unless a genuinely new field appears. **Workflow when a new `records/` day is added:** read it, then add an `assign` entry — a single theme name if the whole day is one field, or a per-record list if records span fields (count must equal the day's record count, or be a single name to broadcast). Use an existing theme when it fits; add to `themes[]` only for a real new field. An unassigned day just prints a build warning and is omitted from articles (the daily page is unaffected); an unknown theme name or a list-length mismatch is a hard build error.

Output in `docs/`:
- `YYYY-MM-DD.html` per day.
- `theme-<slug>.html` per theme that has ≥1 record.
- `index.json` — manifest `[{date, tags}]`, newest first.
- `themes.json` — manifest `[{name, slug, file, count, dates}]` in `theme_map.json` order (for a future portfolio entry point to fetch, mirroring `index.json`).
- `index.html` — there is **no dedicated home**; it fetches `index.json`, picks a random date, and `location.replace()`s to that day page.
- `assets/` — copied verbatim from the top-level `assets/`.

`assets/` (edit these directly; the build copies them):
- `reveal.js` — IntersectionObserver that adds `.in-view` to `.reveal` elements (fade + blur + translateY, the "Web5" reveal). MathJax auto-typeset is disabled in the page config and triggered here after the DOM is ready.
- `calendar.js` — builds the month grid from `index.json`: proof days get strong text and link to their page, the open day is a filled circle, arrows change month. Defaults to the page's own month.
- `style.css` — monochrome design driven by `--ink` CSS vars; Latin Modern (Roman body, Sans headings) with Shippori Mincho / Noto Sans JP fallbacks for Japanese.

All asset/data references use relative `./` paths so the site works under the `/til/` Pages subpath.

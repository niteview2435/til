#!/usr/bin/env python3
"""Generate the TIL static site into docs/.

Sources live in proofs/YYYY-MM-DD.md (the directory name predates the TIL
pivot and is kept for continuity). Each becomes docs/YYYY-MM-DD.html where the
day's records and their blocks fade in as groups on scroll. Math is written as
$...$ / $$...$$ and rendered client-side by MathJax, so this script needs only
the standard library.
"""

import html
import http.server
import json
import re
import shutil
import sys
import threading
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "proofs"
OUT = ROOT / "docs"
ASSETS = ROOT / "assets"
THEME_MAP = ROOT / "theme_map.json"

MATHJAX_CDN = "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"
# Latin Modern — the typeface modern (Lua)LaTeX actually ships. Roman for body
# text, Sans for the gothic headings.
LM_BASE = "https://cdn.jsdelivr.net/gh/sugina-dev/latin-modern-web@1.0.1/style"
LM_ROMAN_CSS = f"{LM_BASE}/latinmodern-roman.css"
LM_SANS_CSS = f"{LM_BASE}/latinmodern-sans.css"


# --- markdown ----------------------------------------------------------------
# A small-but-real Markdown subset, enough to faithfully render pasted AI
# explanations: headings (###/####), paragraphs, unordered & ordered lists,
# blockquotes, GFM pipe tables, fenced code blocks, and bold/italic/code.
# Math spans are protected beforehand so markdown never mangles them.

MATH_RE = re.compile(r"(\$\$.+?\$\$|\$[^$\n]+?\$)", re.S)


def protect_math(text):
    store = []

    def repl(m):
        store.append(m.group(1))
        return f"\x00M{len(store) - 1}\x00"

    return MATH_RE.sub(repl, text), store


def restore_math(text, store):
    # Escape <, >, & inside the raw TeX so the browser doesn't read e.g. `$a<b$`
    # as an opening tag. MathJax reads the decoded DOM text, so it still sees the
    # original characters. & must be replaced first.
    for i, raw in enumerate(store):
        esc = raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00M{i}\x00", esc)
    return text


def inline(s):
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    return s


# Japanese runs (kana / kanji / full-width punctuation & forms) get wrapped so
# CSS can tint them darker than the lighter Latin Modern Roman they sit beside —
# the font-family fallback alone can't colour per script. Half-width Latin,
# digits, symbols and math stay the body default. Covers CJK symbols/punctuation
# (、。「」々…), hiragana, katakana (+ー), CJK ideographs (incl. ext-A), and
# full-width forms. Run on the final HTML: generated tags hold no CJK, and the
# ASCII math placeholders (\x00M…\x00) never match, so this can't corrupt either.
JP_RE = re.compile(
    r"[　-〿぀-ゟ゠-ヿ㐀-䶿一-鿿＀-￯]+"
)


def wrap_jp(s):
    return JP_RE.sub(r'<span class="jp">\g<0></span>', s)


RULE_RE = re.compile(r"^\s*([-*_])\1{2,}\s*$")
HEADING_RE = re.compile(r"^\s*(#{3,6})\s+(.*)$")
FENCE_RE = re.compile(r"^\s*```(.*)$")
FENCE_END_RE = re.compile(r"^\s*```\s*$")
QUOTE_RE = re.compile(r"^\s*>\s?")
UL_RE = re.compile(r"^\s*[-*]\s+(.*)$")
OL_RE = re.compile(r"^\s*\d+\.\s+(.*)$")
BLOCK_START_RE = re.compile(r"^\s*(#{1,6}\s|>|```|\d+\.\s|[-*]\s)")
# A GFM table separator row: cells of dashes with optional alignment colons.
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")


def _cells(row):
    """Split one pipe-table row into trimmed cells (ignoring the outer pipes)."""
    return [c.strip() for c in row.strip().strip("|").split("|")]


def render_blocks(lines):
    """Render already math-protected, html-escaped lines into block HTML.

    Shared by md_to_html and by blockquotes (which re-render their inner lines),
    so math placeholders are restored once by the caller, not here.
    """
    out = []
    para = []
    i, n = 0, len(lines)

    def flush_para():
        if para:
            out.append("<p>" + inline(" ".join(para).strip()) + "</p>")
            para.clear()

    while i < n:
        line = lines[i].rstrip()

        # Fenced code — raw, no inline formatting applied inside.
        m = FENCE_RE.match(line)
        if m:
            flush_para()
            i += 1
            code = []
            while i < n and not FENCE_END_RE.match(lines[i]):
                code.append(lines[i])
                i += 1
            i += 1  # skip the closing fence
            out.append("<pre><code>" + "\n".join(code) + "</code></pre>")
            continue

        # Sub-headings within a block (### and deeper; # / ## are structural).
        m = HEADING_RE.match(line)
        if m:
            flush_para()
            level = len(m.group(1))
            out.append(f"<h{level}>{inline(m.group(2).strip())}</h{level}>")
            i += 1
            continue

        # GFM pipe table: a header row immediately followed by a separator row.
        if "|" in line and i + 1 < n and "|" in lines[i + 1] \
                and TABLE_SEP_RE.match(lines[i + 1]):
            flush_para()
            head = _cells(line)
            i += 2
            body = []
            while i < n and "|" in lines[i] and lines[i].strip():
                body.append(_cells(lines[i]))
                i += 1
            thead = "".join(f"<th>{inline(c)}</th>" for c in head)
            rows = "".join(
                "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>"
                for r in body
            )
            out.append(
                f"<table><thead><tr>{thead}</tr></thead><tbody>{rows}</tbody></table>"
            )
            continue

        # Blockquote: strip the markers and re-render the inner lines.
        if QUOTE_RE.match(line):
            flush_para()
            inner = []
            while i < n and QUOTE_RE.match(lines[i]):
                inner.append(QUOTE_RE.sub("", lines[i], count=1))
                i += 1
            out.append("<blockquote>" + render_blocks(inner) + "</blockquote>")
            continue

        # Rule line: just a block separator, no <hr> (keeps stray --- harmless).
        if RULE_RE.match(line):
            flush_para()
            i += 1
            continue

        # Unordered / ordered lists, with lazy continuation of the last item.
        m = UL_RE.match(line) or OL_RE.match(line)
        if m:
            ordered = OL_RE.match(line) is not None
            item_re = OL_RE if ordered else UL_RE
            items = []
            while i < n:
                lm = item_re.match(lines[i])
                if lm:
                    items.append(inline(lm.group(1).strip()))
                    i += 1
                elif lines[i].strip() == "" or BLOCK_START_RE.match(lines[i]):
                    break
                else:
                    items[-1] += " " + inline(lines[i].strip())
                    i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{x}</li>" for x in items) + f"</{tag}>")
            continue

        if line.strip() == "":
            flush_para()
            i += 1
            continue

        para.append(line.strip())
        i += 1

    flush_para()
    return "\n".join(out)


def md_to_html(text):
    text, store = protect_math(text)
    # Escape prose <, >, & now (math is already out as placeholders) so body
    # text and inline code can contain them safely; math is escaped on restore.
    text = html.escape(text, quote=False)
    return restore_math(wrap_jp(render_blocks(text.split("\n"))), store)


def render_inline(text):
    """Inline-only render (for heading/record labels): math + bold/italic/code,
    with JP tinting — but no block structure."""
    text, store = protect_math(text)
    text = html.escape(text, quote=False)
    return restore_math(wrap_jp(inline(text)), store)


# --- source parsing ----------------------------------------------------------
# A day file holds one or more *records* (記録), separated by a single-`#`
# heading — each record is one pasted/curated explanation. Within a record,
# `##` headings slice the prose into fade-in *blocks*. `###`+ are ordinary
# sub-headings inside a block (handled by the markdown engine). The `#`/`##`
# text (if any) becomes the record title / block heading.

# `#` not followed by another `#`; `##` not followed by a third.
RECORD_RE = re.compile(r"^#(?!#)[ \t　]*(.*?)[ \t　]*$")
BLOCK_RE = re.compile(r"^##(?!#)[ \t　]*(.*?)[ \t　]*$")


def parse_records(text):
    """Return a list of records in document order.

    Each record is `(title, blocks)` where `blocks` is a list of
    `(heading, content)` in document order. A record opens on a `#` line (its
    title may be empty); content/`##` blocks before the first `#` form an
    implicit leading record. A block's leading, heading-less content is kept as
    a block with an empty heading. Empty blocks (and records with no non-empty
    block) are dropped. Anything before the first heading (e.g. a `tags:` line)
    is ignored here — see parse_tags.
    """
    records = []
    cur = None  # [title, [ [heading, [lines]], ... ]]

    for raw in text.strip().split("\n"):
        rm = RECORD_RE.match(raw)
        bm = BLOCK_RE.match(raw)
        if rm is not None:
            cur = [rm.group(1).strip(), []]
            records.append(cur)
        elif bm is not None:
            if cur is None:
                cur = ["", []]
                records.append(cur)
            cur[1].append([bm.group(1).strip(), []])
        else:
            if cur is None:
                continue  # preamble before the first heading (tags, blanks)
            if not cur[1]:
                cur[1].append(["", []])  # leading heading-less block
            cur[1][-1][1].append(raw)

    finished = []
    for title, blocks in records:
        kept = []
        for heading, lines in blocks:
            content = "\n".join(lines).strip()
            if content:
                kept.append((heading, content))
        if kept:
            finished.append((title, kept))
    return finished


def parse_tags(text):
    """Read a leading `tags:` line (before the first heading) into a list."""
    for line in text.strip().splitlines():
        line = line.strip()
        if line.startswith("#"):
            break  # reached a record / block heading; no tags line above it
        if line.startswith("tags:"):
            raw = line[len("tags:"):]
            return [t for t in re.split(r"[,、\s]+", raw.strip()) if t]
    return []


def _section(cls, inner):
    return f'<section class="{cls}">\n      {inner}\n    </section>'


def _block_inner(heading, content):
    label = f'<h3 class="label">{render_inline(heading)}</h3>\n      ' if heading else ""
    return f'{label}<div class="body">{md_to_html(content)}</div>'


def render_records(records, eyebrow_html="", with_divider=True):
    """Build the stacked fade-in <section>s for a day's records.

    Every record is introduced by a `記録` label (numbered `記録 N` when the day
    holds more than one), carrying its title as a small caption beside it. Each
    `##` block then becomes one `.block` section. `eyebrow_html` (the date) rides
    above the first section; the divider rides in the last when set.

    Tags are intentionally not rendered — they live in index.json only.
    """
    multi = len(records) > 1
    items = []  # (css class, inner html)
    for ri, (title, blocks) in enumerate(records, 1):
        num = f" {ri}" if multi else ""
        cap = f'<span class="caption">{render_inline(title)}</span>' if title else ""
        items.append(("record reveal", f'<h2 class="record-label">記録{num}{cap}</h2>'))
        for heading, content in blocks:
            items.append(("block reveal", _block_inner(heading, content)))

    if not items:
        return ""
    if eyebrow_html:
        cls, inner = items[0]
        items[0] = (cls, f'<p class="eyebrow">{eyebrow_html}</p>\n      {inner}')
    if with_divider:
        cls, inner = items[-1]
        items[-1] = (cls, f'{inner}\n      <hr class="divider" aria-hidden="true" />')
    return "\n\n    ".join(_section(c, inner) for c, inner in items)


def assign_days_into_themes(d, records, assign, slugs, theme_items):
    """File each of a day's records under its theme.

    `assign[d]` is a single theme name (the whole day) or a list of names, one
    per record in document order; a single name is broadcast to every record.
    Unknown theme names or a length mismatch are hard errors; an unassigned day
    is skipped with a warning (its day page is unaffected).
    """
    if d not in assign:
        print(f"  warning: {d} has no theme in theme_map.json — skipped")
        return
    if not records:
        return
    names = assign[d]
    if isinstance(names, str):
        names = [names] * len(records)
    if len(names) != len(records):
        raise SystemExit(
            f"{d}: theme_map has {len(names)} theme(s) but the day has "
            f"{len(records)} record(s); list one theme per record (or a single one)"
        )
    for name, record in zip(names, records):
        if name not in slugs:
            raise SystemExit(f"{d}: unknown theme '{name}' (add it to themes[])")
        theme_items[name].append((d, record))


def render_theme(items):
    """Render a theme article: each item is one record, titled by its heading,
    oldest first — no source-day eyebrow and no dividers, just stacked blocks."""
    parts = []
    for d, (title, blocks) in items:
        secs = []
        if title:
            secs.append(_section("record reveal", f'<h2 class="record-label">{render_inline(title)}</h2>'))
        for heading, content in blocks:
            secs.append(_section("block reveal", _block_inner(heading, content)))
        parts.append("\n\n    ".join(secs))
    return "\n\n    ".join(parts)


def date_jp(d):
    y, m, day = d.split("-")
    return f"{int(y)}年{int(m)}月{int(day)}日"


# --- templates ---------------------------------------------------------------

DAY_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{date_jp} — TIL</title>
  <link rel="stylesheet" href="{lm_roman}" />
  <link rel="stylesheet" href="{lm_sans}" />
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@500;700&family=Shippori+Mincho&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="./assets/style.css" />
  <script>
    window.MathJax = {{
      tex: {{
        inlineMath: [["$", "$"], ["\\\\(", "\\\\)"]],
        displayMath: [["$$", "$$"], ["\\\\[", "\\\\]"]]
      }},
      startup: {{ typeset: false }},
      options: {{ enableMenu: false }}
    }};
  </script>
  <script defer src="{mathjax}"></script>
</head>
<body data-date="{date}">
  <main class="container">
    {content}

    <nav class="calendar-wrap reveal" aria-label="カレンダー">
      <div id="calendar"></div>
    </nav>
  </main>

  <script defer src="./assets/reveal.js"></script>
  <script defer src="./assets/calendar.js"></script>
</body>
</html>
"""

THEME_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{theme} — TIL</title>
  <link rel="stylesheet" href="{lm_roman}" />
  <link rel="stylesheet" href="{lm_sans}" />
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@500;700&family=Shippori+Mincho&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="./assets/style.css" />
  <script>
    window.MathJax = {{
      tex: {{
        inlineMath: [["$", "$"], ["\\\\(", "\\\\)"]],
        displayMath: [["$$", "$$"], ["\\\\[", "\\\\]"]]
      }},
      startup: {{ typeset: false }},
      options: {{ enableMenu: false }}
    }};
  </script>
  <script defer src="{mathjax}"></script>
</head>
<body data-theme="{theme}">
  <main class="container">
    <header class="theme-head">
      <h1 class="theme-title">{theme}</h1>
    </header>

    {content}
  </main>

  <script defer src="./assets/reveal.js"></script>
</body>
</html>
"""

INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>TIL</title>
  <style>
    html, body { height: 100%; margin: 0; }
    body { display: grid; place-items: center; background: #fff; color: #9a9a9a;
           font-family: serif; }
  </style>
  <script>
    fetch('./index.json')
      .then(function (r) { return r.json(); })
      .then(function (list) {
        if (!list.length) { document.body.textContent = 'まだ記録がありません。'; return; }
        var pick = list[Math.floor(Math.random() * list.length)];
        location.replace('./' + pick.date + '.html');
      })
      .catch(function () { document.body.textContent = '読み込みに失敗しました。'; });
  </script>
</head>
<body>…</body>
</html>
"""

# A `#` line opens a 記録 (its text is the optional title; multi-record days are
# auto-numbered 記録 1 / 記録 2 …). `##` lines slice a record into blocks.
NEW_TEMPLATE = """tags:

#

##
"""

# Injected into day pages only in `--watch` (preview) mode — never by a plain
# `python3 build.py`, so the committed/CI `docs/` output stays untouched. It
# polls a server-only `./__reload` endpoint (a token that changes on every
# rebuild) and reloads the page when the token moves.
LIVE_RELOAD_SNIPPET = """  <script>
    (function () {
      var seen = null;
      (function poll() {
        fetch('./__reload', { cache: 'no-store' })
          .then(function (r) { return r.text(); })
          .then(function (t) {
            if (seen === null) seen = t;
            else if (t !== seen) location.reload();
          })
          .catch(function () {})
          .then(function () { setTimeout(poll, 700); });
      })();
    })();
  </script>
"""


# --- build -------------------------------------------------------------------

def build(live=False):
    """Regenerate docs/. With live=True, inject the preview live-reload script
    into day pages (used by `--watch`; a plain build never sets this)."""
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    shutil.copytree(ASSETS, OUT / "assets")

    theme_map = json.loads(THEME_MAP.read_text(encoding="utf-8"))
    slugs = {t["name"]: t["slug"] for t in theme_map["themes"]}
    assign = theme_map["assign"]
    # theme name -> list of (date, record), collected oldest-first (the glob is
    # ascending) so each article reads as it accumulated.
    theme_items = {t["name"]: [] for t in theme_map["themes"]}

    entries = []
    for md in sorted(SRC.glob("*.md")):
        d = md.stem  # YYYY-MM-DD
        text = md.read_text(encoding="utf-8")
        records = parse_records(text)
        tags = parse_tags(text)  # stored in index.json only, not rendered
        assign_days_into_themes(d, records, assign, slugs, theme_items)
        page = DAY_TEMPLATE.format(
            date=d,
            date_jp=date_jp(d),
            content=render_records(records, eyebrow_html=date_jp(d)),
            mathjax=MATHJAX_CDN,
            lm_roman=LM_ROMAN_CSS,
            lm_sans=LM_SANS_CSS,
        )
        if live:
            page = page.replace("</body>", LIVE_RELOAD_SNIPPET + "</body>")
        (OUT / f"{d}.html").write_text(page, encoding="utf-8")
        entries.append({"date": d, "tags": tags})

    entries.sort(key=lambda e: e["date"], reverse=True)
    (OUT / "index.json").write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "index.html").write_text(INDEX_TEMPLATE, encoding="utf-8")

    manifest = []
    for t in theme_map["themes"]:
        name, slug = t["name"], t["slug"]
        items = theme_items[name]
        if not items:
            continue  # a declared theme with nothing assigned yet: no page
        page = THEME_TEMPLATE.format(
            theme=name,
            content=render_theme(items),
            mathjax=MATHJAX_CDN,
            lm_roman=LM_ROMAN_CSS,
            lm_sans=LM_SANS_CSS,
        )
        (OUT / f"theme-{slug}.html").write_text(page, encoding="utf-8")
        # dates newest-first in the manifest, mirroring index.json's ordering.
        dates = sorted({d for d, _ in items}, reverse=True)
        manifest.append(
            {"name": name, "slug": slug, "file": f"theme-{slug}.html",
             "count": len(items), "dates": dates}
        )
    (OUT / "themes.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"built {len(entries)} day(s), {len(manifest)} theme(s) into {OUT}/")


def watch(port=8000):
    """Serve docs/ and rebuild on any change to proofs/, assets/ or build.py.

    A server-only `/__reload` endpoint returns a token that changes on each
    rebuild; the injected live-reload script polls it and reloads the open
    page. Standard-library only. Ctrl-C to stop.
    """
    state = {"token": str(time.time())}

    def rebuild():
        build(live=True)
        state["token"] = str(time.time())

    rebuild()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(OUT), **kwargs)

        def do_GET(self):
            if self.path.split("?", 1)[0].rstrip("/") == "/__reload":
                body = state["token"].encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def log_message(self, *args):
            pass  # keep the watch console to build messages only

    httpd = http.server.ThreadingHTTPServer(("", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"serving {OUT}/ at http://localhost:{port} — watching for changes")

    def snapshot():
        paths = list(SRC.glob("*.md")) + list(ASSETS.rglob("*")) + [ROOT / "build.py"]
        return {str(p): p.stat().st_mtime for p in paths if p.is_file()}

    prev = snapshot()
    try:
        while True:
            time.sleep(0.4)
            cur = snapshot()
            if cur != prev:
                prev = cur
                try:
                    rebuild()
                    print("rebuilt")
                except Exception as exc:  # keep serving even if a draft is broken
                    print(f"build error: {exc}")
    except KeyboardInterrupt:
        pass


def scaffold_today():
    SRC.mkdir(exist_ok=True)
    today = date.today().isoformat()
    f = SRC / f"{today}.md"
    if f.exists():
        print(f"{f} already exists")
        return
    f.write_text(NEW_TEMPLATE, encoding="utf-8")
    print(f"created {f}")


if __name__ == "__main__":
    if "--new" in sys.argv:
        scaffold_today()
    elif "--watch" in sys.argv:
        watch()
    else:
        build()

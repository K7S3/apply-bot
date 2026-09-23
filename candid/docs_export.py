"""Offline documentation export for candid.

Bundles the shipped docs (``candid/data/docs/*.md``, exposed at runtime via
``candid.docs_bundle.DOCS_DIR``) into either a single plain-text file or a
single self-contained HTML file. Everything is stdlib-only and nothing
touches the network.

The real docs bundle is imported lazily *inside* the export functions, so
this module imports cleanly even when the bundle is unavailable (for example
in unit tests, which pass fixture topics directly). Pass an explicit
``topics`` argument as a sequence of ``(title, markdown_text)`` tuples; when
it is omitted the topics are loaded from the bundled docs.
"""

from __future__ import annotations

import datetime as _dt
import html as _html
import re as _re
from pathlib import Path
from typing import Optional, Sequence, Tuple

PRODUCT_NAME = "candid"

# A topic is a (title, markdown_text) pair.
Topic = Tuple[str, str]

_HEADING_RE = _re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_RE = _re.compile(r"^```")
_LIST_BULLET_RE = _re.compile(r"^\s*[-*+]\s+(.*)$")
_LIST_ORDERED_RE = _re.compile(r"^\s*\d+[.)]\s+(.*)$")
_BLOCKQUOTE_RE = _re.compile(r"^\s*>\s?(.*)$")
_HR_RE = _re.compile(r"^\s*([-*_])\s*(\1\s*){2,}$")


def _docs_version() -> str:
    """Return the docs version, falling back gracefully if unknown."""
    try:
        from candid import __version__

        return str(__version__)
    except Exception:
        return "unknown"


def _generated_date(generated_at: Optional[str] = None) -> str:
    if generated_at:
        return generated_at
    return _dt.date.today().isoformat()


def _strip_inline_markup(text: str) -> str:
    """Remove common inline markdown markup, leaving plain text."""
    # images -> alt text
    text = _re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    # links -> text (url)
    text = _re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: f"{m.group(1)} ({m.group(2)})", text)
    # reference-style links [text][ref] -> text
    text = _re.sub(r"\[([^\]]+)\]\[[^\]]*\]", r"\1", text)
    # bold/italic
    text = _re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = _re.sub(r"__(.+?)__", r"\1", text)
    text = _re.sub(r"(?<!\w)\*(?!\*)(.+?)(?<!\*)\*(?!\w)", r"\1", text)
    text = _re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", text)
    # inline code
    text = _re.sub(r"`([^`]+)`", r"\1", text)
    # stray HTML tags
    text = _re.sub(r"<[^>]+>", "", text)
    return text


def _title_from_markdown(text: str, fallback: str) -> str:
    """Derive a topic title from the first ATX heading, else the filename stem."""
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            return _strip_inline_markup(m.group(2)).strip()
    return fallback.replace("_", " ").replace("-", " ").title()


def load_topics() -> list:
    """Load bundled doc topics as ``[(title, markdown_text), ...]``.

    The import of ``candid.docs_bundle`` is deferred so this module can be
    imported without the bundle present. Topics are the ``*.md`` files under
    ``candid.docs_bundle.DOCS_DIR``, in sorted filename order.
    """
    from candid import docs_bundle  # deferred: sibling-owned module

    docs_dir = Path(docs_bundle.DOCS_DIR)
    topics = []
    for md_path in sorted(docs_dir.glob("*.md")):
        text = md_path.read_text(encoding="utf-8")
        topics.append((_title_from_markdown(text, md_path.stem), text))
    return topics


def markdown_to_text(md: str) -> str:
    """Convert a small markdown subset to readable plain text."""
    out = []
    in_fence = False
    for line in md.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            out.append(line.rstrip())
            continue
        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            title = _strip_inline_markup(m.group(2)).strip()
            if level <= 2:
                out.append("")
                out.append(title)
                out.append("=" * len(title) if level == 1 else "-" * len(title))
            else:
                out.append("")
                out.append(title + ":")
            continue
        m = _BLOCKQUOTE_RE.match(line)
        if m:
            out.append("    " + _strip_inline_markup(m.group(1)).strip())
            continue
        m = _LIST_BULLET_RE.match(line)
        if m:
            out.append("  - " + _strip_inline_markup(m.group(1)).strip())
            continue
        m = _LIST_ORDERED_RE.match(line)
        if m:
            out.append("  * " + _strip_inline_markup(m.group(1)).strip())
            continue
        if _HR_RE.match(line):
            out.append("-" * 40)
            continue
        out.append(_strip_inline_markup(line).rstrip())
    # collapse runs of blank lines
    cleaned = []
    blank = False
    for line in out:
        if line.strip():
            cleaned.append(line)
            blank = False
        elif not blank:
            cleaned.append("")
            blank = True
    return "\n".join(cleaned).strip("\n")


def _slugify(title: str) -> str:
    slug = _re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "topic"


def _unique_slugs(titles: Sequence[str]) -> list:
    seen = {}
    slugs = []
    for title in titles:
        base = _slugify(title)
        n = seen.get(base, 0)
        seen[base] = n + 1
        slugs.append(base if n == 0 else f"{base}-{n + 1}")
    return slugs


def _escape_html(text: str) -> str:
    return _html.escape(text, quote=True)


def _inline_html(text: str) -> str:
    """Convert inline markdown to HTML. Absolute URLs are never linked."""
    text = _escape_html(text)

    # code spans first (protect contents with placeholders)
    codes = []

    def _stash(m):
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = _re.sub(r"`([^`]+)`", _stash, text)

    # images -> alt text only (never emit <img> / src)
    text = _re.sub(r"!\[([^\]]*)\]\([^)]*\)", lambda m: m.group(1), text)

    # links: fragment-only links keep an anchor; everything else becomes
    # plain text so no http(s) URL ever appears in an href attribute.
    def _link(m):
        label, url = m.group(1), m.group(2).strip()
        if url.startswith("#") and not url.startswith(("http://", "https://")):
            return f'<a href="{url}">{label}</a>'
        return f"{label} ({url})"

    text = _re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, text)
    text = _re.sub(r"\[([^\]]+)\]\[[^\]]*\]", r"\1", text)

    # bold, then italic
    text = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = _re.sub(r"__(.+?)__", r"<strong>\1</strong>", text)
    text = _re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = _re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<em>\1</em>", text)

    # restore code spans
    for i, code in enumerate(codes):
        text = text.replace(f"\x00{i}\x00", f"<code>{code}</code>")
    return text


def markdown_to_html(md: str) -> str:
    """Convert a small markdown subset to HTML fragment (no page wrapper)."""
    blocks = []
    para = []
    list_kind = None  # "ul" or "ol"
    list_items = []
    in_fence = False
    fence_lang = ""
    fence_lines = []

    def flush_para():
        if para:
            blocks.append("<p>" + " ".join(_inline_html(l) for l in para) + "</p>")
            para.clear()

    def flush_list():
        nonlocal list_kind
        if list_items:
            tag = list_kind or "ul"
            items = "".join(f"<li>{_inline_html(i)}</li>" for i in list_items)
            blocks.append(f"<{tag}>{items}</{tag}>")
            list_items.clear()
            list_kind = None

    def flush_fence():
        if fence_lines or fence_lang:
            cls = f' class="language-{fence_lang}"' if fence_lang else ""
            code = "\n".join(_escape_html(l) for l in fence_lines)
            blocks.append(f"<pre><code{cls}>{code}</code></pre>")
            fence_lines.clear()

    for raw in md.splitlines():
        line = raw.rstrip()
        fence = _FENCE_RE.match(line)
        if fence:
            if in_fence:
                flush_fence()
                in_fence = False
                fence_lang = ""
            else:
                flush_para()
                flush_list()
                in_fence = True
                fence_lang = line[3:].strip().split()[0] if line[3:].strip() else ""
            continue
        if in_fence:
            fence_lines.append(line)
            continue
        m = _HEADING_RE.match(line)
        if m:
            flush_para()
            flush_list()
            level = min(len(m.group(1)), 6)
            blocks.append(f"<h{level}>{_inline_html(m.group(2).strip())}</h{level}>")
            continue
        if _HR_RE.match(line):
            flush_para()
            flush_list()
            blocks.append("<hr>")
            continue
        m = _BLOCKQUOTE_RE.match(line)
        if m:
            flush_para()
            flush_list()
            blocks.append(f"<blockquote><p>{_inline_html(m.group(1).strip())}</p></blockquote>")
            continue
        bullet = _LIST_BULLET_RE.match(line)
        ordered = _LIST_ORDERED_RE.match(line)
        if bullet or ordered:
            flush_para()
            kind = "ul" if bullet else "ol"
            if list_kind and list_kind != kind:
                flush_list()
            list_kind = kind
            list_items.append((bullet or ordered).group(1).strip())
            continue
        if not line.strip():
            flush_para()
            flush_list()
            continue
        flush_list()
        para.append(line.strip())

    flush_para()
    flush_list()
    if in_fence:
        flush_fence()
    return "\n".join(blocks)


_CSS = """\
body { font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
       max-width: 48rem; margin: 2rem auto; padding: 0 1.25rem;
       line-height: 1.6; color: #1a1a1a; background: #fff; }
header.title { border-bottom: 3px solid #1a1a1a; padding-bottom: 1rem;
               margin-bottom: 2rem; }
header.title h1 { margin: 0 0 0.25rem; font-size: 1.9rem; }
header.title .meta { color: #555; font-size: 0.95rem; }
nav.toc { background: #f6f6f6; border: 1px solid #ddd; border-radius: 6px;
          padding: 1rem 1.5rem; margin-bottom: 2.5rem; }
nav.toc h2 { margin-top: 0; font-size: 1.1rem; }
nav.toc ol { margin: 0; padding-left: 1.5rem; }
nav.toc a { color: #0b5cad; text-decoration: none; }
nav.toc a:hover { text-decoration: underline; }
section.topic { margin-bottom: 3rem; }
section.topic > h2 { border-bottom: 2px solid #1a1a1a; padding-bottom: 0.35rem; }
pre { background: #f4f4f4; border: 1px solid #ddd; border-radius: 6px;
      padding: 0.9rem; overflow-x: auto; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
       font-size: 0.9em; background: #f4f4f4; padding: 0.1em 0.3em;
       border-radius: 3px; }
pre code { background: none; padding: 0; }
blockquote { border-left: 4px solid #ccc; margin: 1rem 0; padding: 0.25rem 1rem;
             color: #444; background: #fafafa; }
hr { border: none; border-top: 1px solid #ddd; margin: 2rem 0; }
footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #ddd;
         color: #777; font-size: 0.85rem; }
"""


def _resolve_topics(topics: Optional[Sequence[Topic]]) -> list:
    return list(topics) if topics is not None else load_topics()


def _write(out_path, content: str) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    return out


def export_txt(
    out_path,
    topics: Optional[Sequence[Topic]] = None,
    generated_at: Optional[str] = None,
) -> Path:
    """Export all topics as a single plain-text bundle.

    The bundle starts with a title page (product name, docs version,
    generation date), then a table of contents, then every topic rendered
    as plain text. Returns the output path.
    """
    topics = _resolve_topics(topics)
    date_str = _generated_date(generated_at)
    version = _docs_version()

    lines = []
    bar = "=" * 64
    lines.append(bar)
    lines.append(f"{PRODUCT_NAME} - Offline Documentation")
    lines.append(bar)
    lines.append(f"Docs version: {version}")
    lines.append(f"Generated:    {date_str}")
    lines.append("")
    lines.append("TABLE OF CONTENTS")
    lines.append("-" * 64)
    for i, (title, _md) in enumerate(topics, 1):
        lines.append(f"  {i}. {title}")
    lines.append("")
    for i, (title, md) in enumerate(topics, 1):
        lines.append(bar)
        lines.append(f"{i}. {title}")
        lines.append(bar)
        lines.append("")
        lines.append(markdown_to_text(md))
        lines.append("")
    return _write(out_path, "\n".join(lines).rstrip() + "\n")


def export_html(
    out_path,
    topics: Optional[Sequence[Topic]] = None,
    generated_at: Optional[str] = None,
) -> Path:
    """Export all topics as a single self-contained HTML file.

    The file has embedded CSS and no external references: no stylesheets,
    scripts, images, or fonts are loaded, and no ``src``/``href`` attribute
    points at an ``http(s)`` URL. The table of contents links to each topic
    via fragment anchors. Returns the output path.
    """
    topics = _resolve_topics(topics)
    date_str = _generated_date(generated_at)
    version = _docs_version()

    titles = [t for t, _m in topics]
    slugs = _unique_slugs(titles)

    toc_items = "\n".join(
        f'      <li><a href="#{_escape_html(s)}">{_escape_html(t)}</a></li>'
        for s, t in zip(slugs, titles)
    )
    sections = "\n".join(
        f'    <section class="topic" id="{_escape_html(s)}">\n'
        f'      <h2>{_escape_html(t)}</h2>\n'
        f"      {markdown_to_html(m)}\n"
        "    </section>"
        for s, t, m in zip(slugs, titles, [m for _t, m in topics])
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_escape_html(PRODUCT_NAME)} - Offline Documentation</title>
<style>
{_CSS}</style>
</head>
<body>
<header class="title">
  <h1>{_escape_html(PRODUCT_NAME)} - Offline Documentation</h1>
  <div class="meta">Docs version {_escape_html(version)} &middot;
  Generated {_escape_html(date_str)}</div>
</header>
<nav class="toc" aria-label="Table of contents">
  <h2>Table of contents</h2>
  <ol>
{toc_items}
  </ol>
</nav>
<main>
{sections}
</main>
<footer>Generated offline by {_escape_html(PRODUCT_NAME)} {_escape_html(version)}.</footer>
</body>
</html>
"""
    # Guard: the export must stay fully self-contained.
    for attr in _re.findall(r'''(?:src|href)\s*=\s*["']([^"']*)["']''', page):
        assert not attr.startswith(("http://", "https://")), f"external reference leaked: {attr}"
    return _write(out_path, page)

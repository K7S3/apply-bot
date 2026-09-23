"""Privacy tab fragment for the local dashboard.

No argparse here: exposes ``privacy_tab_html() -> str``, a self-contained
HTML fragment (a ``<section>`` using the dashboard's existing CSS classes).
The coordinator wires the ``/privacy?action=...`` GET routes; this module
only produces the fragment with those hrefs.
"""

from __future__ import annotations

import html
import urllib.parse

from . import privacy as P


def _privacy_url(action: str, category: str | None = None) -> str:
    """Build an HTML-escaped /privacy?action=... link."""
    q = f"/privacy?action={urllib.parse.quote(action)}"
    if category is not None:
        q += f"&category={urllib.parse.quote(category)}"
    return html.escape(q, quote=True)


def privacy_tab_html() -> str:
    """Render the Privacy section: totals, per-category table, quick actions."""
    inv = P.iter_inventory()
    rows = []
    for r in inv:
        rows.append({**r, "nfiles": len(P.category_files(r["name"]))})

    total_bytes = sum(r["bytes"] for r in rows)
    total_files = sum(r["nfiles"] for r in rows)
    ncat = sum(1 for r in rows if r["exists"])

    parts: list[str] = []
    parts.append('<section id="privacy">')
    parts.append("<h2>Privacy</h2>")
    parts.append(
        '<p class="sub">Everything candid holds about you, and controls to '
        "manage it. Exports made by <code>candid privacy</code> live in "
        "<code>privacy_exports</code> and survive a nuke.</p>"
    )

    parts.append('<div class="statcards">')
    parts.append(
        f'<div class="statcard"><div class="n">{html.escape(P.human_size(total_bytes))}</div>'
        '<div class="l">data held</div></div>'
    )
    parts.append(
        f'<div class="statcard"><div class="n">{total_files}</div>'
        '<div class="l">files</div></div>'
    )
    parts.append(
        f'<div class="statcard"><div class="n">{ncat}</div>'
        '<div class="l">categories with data</div></div>'
    )
    parts.append("</div>")

    parts.append("<table>")
    parts.append(
        "<tr><th>Category</th><th>What it holds</th><th>Files</th>"
        "<th>Size</th><th>Records</th><th>Actions</th></tr>"
    )
    for r in rows:
        name = html.escape(r["name"])
        label = html.escape(r["label"])
        size = html.escape(r["size"])
        records = "-" if r["records"] is None else html.escape(str(r["records"]))
        export_url = _privacy_url("export", r["name"])
        purge_url = _privacy_url("purge", r["name"])
        parts.append(
            "<tr>"
            f"<td><code>{name}</code></td>"
            f"<td>{label}</td>"
            f"<td>{r['nfiles']}</td>"
            f"<td>{size}</td>"
            f"<td>{records}</td>"
            f'<td><a href="{export_url}">Export</a> &middot; '
            f'<a href="{purge_url}">Purge</a></td>'
            "</tr>"
        )
    parts.append("</table>")

    parts.append('<div class="toolbar">')
    quick = [
        ("inventory", "Full inventory"),
        ("scan", "Scan for PII"),
        ("export", "Export everything"),
        ("audit", "Audit log"),
        ("retention", "Retention policy"),
    ]
    for action, label in quick:
        parts.append(
            f'<a class="chip" href="{_privacy_url(action)}">{html.escape(label)}</a>'
        )
    parts.append(
        f'<a class="chip" style="border-color:var(--red);color:var(--red)" '
        f'href="{_privacy_url("nuke")}">Nuke all data</a>'
    )
    parts.append("</div>")
    parts.append("</section>")
    return "\n".join(parts)

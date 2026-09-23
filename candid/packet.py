"""Application packet export: one PDF per tracked application.

A packet bundles the *already-tailored* resume and cover letter for an
application into a single PDF, plus an optional references page. Nothing is
re-tailored or invented here: resume and cover letter text come straight from
``candid.tailor.build_resume`` / ``candid.tailor.build_cover_letter``.

References (name, relationship, contact) are managed in
``C.DATA_DIR/references.json`` and are included as the packet's final page
only when the caller passes ``include_references=True``.

PDF generation is stdlib-only: a minimal hand-rolled writer emits text-only
pages using the standard 14 fonts (Helvetica / Helvetica-Bold), so no extra
dependency is needed. ``pypdf`` (optional) is used only for parsing, not for
writing.
"""

from __future__ import annotations

import json
import textwrap
from datetime import datetime
from pathlib import Path

from candid import config as C

# --- references ----------------------------------------------------------------


class PacketError(Exception):
    """Raised for invalid packet operations."""


def _references_path(path: str | Path | None = None) -> Path:
    if path is not None and Path(path).suffix == ".json":
        return Path(path)
    base = Path(path) if path is not None else C.DATA_DIR
    return base / "references.json"


def _load_refs(path: str | Path | None = None) -> list[dict]:
    p = _references_path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PacketError(f"References file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise PacketError(f"References file {p} should contain a JSON list.")
    return data


def add_reference(name: str, relationship: str, contact: str = "",
                  *, path: str | Path | None = None) -> dict:
    """Add a reference. Returns the new record."""
    name = (name or "").strip()
    relationship = (relationship or "").strip()
    if not name or not relationship:
        raise PacketError(
            "References need at least --name and --relationship, e.g.\n"
            "  python -m candid references add --name \"Sam Rivera\" "
            "--relationship \"former manager\" --contact sam@example.com"
        )
    refs = _load_refs(path)
    rec = {
        "name": name,
        "relationship": relationship,
        "contact": (contact or "").strip(),
        "added_at": datetime.now().isoformat(timespec="seconds"),
    }
    refs.append(rec)
    p = _references_path(path)
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(refs, indent=2), encoding="utf-8")
    return rec


def list_references(*, path: str | Path | None = None) -> list[dict]:
    """Return all saved references (oldest first)."""
    return [dict(r) for r in _load_refs(path)]


def render_references(refs: list[dict]) -> str:
    if not refs:
        return "No references saved yet."
    lines = ["References:"]
    for i, r in enumerate(refs, 1):
        contact = f" — {r['contact']}" if r.get("contact") else ""
        lines.append(f"  {i}. {r['name']} ({r['relationship']}){contact}")
    return "\n".join(lines)


# --- packet content ------------------------------------------------------------


def _require_app(app_id: int, path: str | Path | None = None) -> dict:
    from candid import tracker as T
    base = Path(path) if path is not None else None
    tpath = (base / "tracker.json") if base is not None else None
    apps = T.list_apps(path=tpath) if tpath is not None else T.list_apps()
    for app in apps:
        if app.get("id") == app_id:
            return app
    raise PacketError(
        f"No tracked application with id {app_id}.\n"
        "Run `python -m candid track list` to see application ids."
    )


def _resolve_jd(app_id: int, jd: str, path: str | Path | None = None) -> str:
    if jd:
        return jd
    from candid import jobs as J
    meta = J.get_job_meta(app_id)
    if meta.get("jd_text"):
        return meta["jd_text"]
    raise PacketError(
        f"No JD stored for application #{app_id} and none was passed.\n"
        "Pass --jd <file | url | ->, e.g.\n"
        f"  python -m candid packet --app-id {app_id} --jd jd.txt"
    )


def _references_page_text(refs: list[dict]) -> str:
    lines = ["REFERENCES", ""]
    for i, r in enumerate(refs, 1):
        lines.append(f"{i}. {r['name']}")
        lines.append(f"   {r['relationship']}")
        if r.get("contact"):
            lines.append(f"   {r['contact']}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_packet(app_id: int, *, include_references: bool = False,
                 jd: str = "", company: str = "", role: str = "",
                 tone: str = "confident", length: str = "one-page",
                 hook: str = "", profile: dict | None = None,
                 path: str | Path | None = None) -> bytes:
    """Build the application packet PDF. Returns the PDF as bytes.

    Reuses ``candid.tailor`` output verbatim — nothing is re-tailored or
    invented. The references page is appended only when
    ``include_references=True``.
    """
    from candid import profile as P
    from candid import tailor as T

    app = _require_app(app_id, path)
    company = company or app.get("company", "")
    role = role or app.get("role", "")
    jd_text = _resolve_jd(app_id, jd, path)
    prof = profile if profile is not None else P.load_profile()

    resume = T.build_resume(prof, jd_text, company=company, role=role,
                            tone=tone, length=length)
    cover = T.build_cover_letter(prof, jd_text, company=company, role=role,
                                 tone=tone, hook=hook)

    title_suffix = f" — {role} @ {company}" if role or company else ""
    pages = [
        (f"Resume{title_suffix}", resume),
        (f"Cover Letter{title_suffix}", cover),
    ]
    if include_references:
        refs = list_references(path=path)
        if not refs:
            raise PacketError(
                "No references saved yet — nothing to include.\n"
                "Add one first, then re-run with --include-references:\n"
                "  python -m candid references add --name \"Sam Rivera\" "
                "--relationship \"former manager\" --contact sam@example.com"
            )
        pages.append((f"References{title_suffix}",
                      _references_page_text(refs)))
    return _write_pdf(pages)


def save_packet(app_id: int, dest: str | Path, **kwargs) -> Path:
    """Build the packet and write it to ``dest``. Returns the path."""
    p = Path(dest)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(build_packet(app_id, **kwargs))
    return p


# --- minimal stdlib PDF writer -------------------------------------------------
# Text-only pages, standard 14 fonts (Helvetica, Helvetica-Bold). No images,
# no embedded fonts, no compression: simple and byte-inspectable.

_PAGE_W, _PAGE_H = 612.0, 792.0   # US Letter
_MARGIN = 72.0
_TITLE_SIZE, _BODY_SIZE, _FOOT_SIZE = 14.0, 10.0, 8.0
_LEADING = 13.0
_WRAP_WIDTH = 88  # chars at 10pt Helvetica within the margins

_FONT_HELVETICA = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
_FONT_HELVETICA_BOLD = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"

_GLYPH_FALLBACKS = {
    "\u2022": "-", "\u2013": "-", "\u2014": "-", "\u2212": "-",
    "\u2026": "...", "\u2018": "'", "\u2019": "'",
    "\u201c": '"', "\u201d": '"', "\u00a0": " ", "\u2192": "->",
    "\u2713": "v", "\u2714": "v",
}


def _pdf_text(s: str) -> bytes:
    """Clean text to Latin-1 and escape it for a PDF literal string."""
    s = "".join(_GLYPH_FALLBACKS.get(ch, ch) for ch in s)
    out = []
    for ch in s:
        code = ord(ch)
        out.append(chr(code) if code < 256 else "?")
    s = "".join(out)
    s = s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return s.encode("latin-1")


def _flow_pages(title: str, body: str) -> list[list[bytes]]:
    """Wrap a (title, body) pair into lines, split across pages."""
    usable_h = _PAGE_H - 2 * _MARGIN - 24.0  # room for title gap + footer
    body_lines_per_page = int(usable_h // _LEADING)
    wrapped: list[bytes] = []
    for raw in body.splitlines():
        if not raw.strip():
            wrapped.append(b"")
        else:
            for piece in textwrap.wrap(raw, width=_WRAP_WIDTH,
                                       break_long_words=True,
                                       break_on_hyphens=False) or [b""]:
                wrapped.append(_pdf_text(piece))
    chunks = [wrapped[i:i + body_lines_per_page]
              for i in range(0, len(wrapped), body_lines_per_page)] or [[b""]]
    title_b = _pdf_text(title)
    out: list[list[bytes]] = []
    for i, chunk in enumerate(chunks):
        head = title_b if i == 0 else title_b + b" (continued)"
        out.append([head] + chunk)
    return out


def _content_stream(page_lines: list[bytes], page_no: int, page_total: int) -> bytes:
    x, y_top, y_foot = int(_MARGIN), int(_PAGE_H - _MARGIN), int(_MARGIN - 24)
    parts = [
        b"BT /F1 %d Tf %d %d Td" % (_FOOT_SIZE, x, y_foot),
        b"(%s) Tj ET" % _pdf_text(f"Page {page_no} of {page_total}"),
        b"BT /F2 %d Tf %d %d Td %.1f TL" % (_TITLE_SIZE, x, y_top, _LEADING * 1.4),
        b"(%s) Tj" % page_lines[0],
        b"T* T* /F1 %d Tf %.1f TL" % (_BODY_SIZE, _LEADING),
    ]
    for line in page_lines[1:]:
        parts.append(b"T*" if not line else b"(%s) Tj T*" % line)
    parts.append(b"ET")
    return b"\n".join(parts) + b"\n"


def _write_pdf(pages: list[tuple[str, str]]) -> bytes:
    """Render (title, body-text) pages into a complete PDF document."""
    flat: list[list[bytes]] = []
    for title, body in pages:
        flat.extend(_flow_pages(title, body))
    total = len(flat)

    # Object numbering is fixed up front, so the /Pages object can list its
    # kids immediately: 1 catalog, 2 pages, 3-4 fonts, then page/content pairs.
    page_obj_nums = [5 + 2 * i for i in range(total)]
    kids = b" ".join(b"%d 0 R" % n for n in page_obj_nums)

    buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []

    def _obj(body: bytes) -> None:
        nonlocal buf
        offsets.append(len(buf))
        buf += b"%d 0 obj\n" % len(offsets)  # object number after append
        buf += body + b"\nendobj\n"

    _obj(b"<< /Type /Catalog /Pages 2 0 R >>")                    # 1
    _obj(b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, total))  # 2
    _obj(_FONT_HELVETICA)                                          # 3
    _obj(_FONT_HELVETICA_BOLD)                                     # 4

    for i, page_lines in enumerate(flat, 1):
        stream = _content_stream(page_lines, i, total)
        _obj(b"<< /Type /Page /Parent 2 0 R "
             b"/MediaBox [0 0 612 792] "
             b"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
             b"/Contents %d 0 R >>" % (len(offsets) + 2))
        _obj(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"endstream")

    xref_pos = len(buf)
    n = len(offsets) + 1
    buf += b"xref\n0 %d\n" % n
    buf += b"0000000000 65535 f \n"
    for off in offsets:
        buf += b"%010d 00000 n \n" % off
    buf += (b"trailer\n<< /Size %d /Root 1 0 R >>\n"
            b"startxref\n%d\n%%%%EOF\n" % (n, xref_pos))
    return bytes(buf)

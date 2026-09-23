"""Question-pack import for the template gallery (batch 106, worker E).

Integrates kind="questions" template packs (served by candid/templates.py,
worker A) with the verified interview-question bank format used by
candid/prep_questions.py.

CLI surface (wired in candid/__main__.py)::

    python -m candid templates questions import <pack> [--company C] [--dry-run] [--json]
    python -m candid templates questions list [--company C] [--json]

Packs are read through the candid.templates contract (lazy import, so this
module keeps working when the gallery module is absent)::

    list_packs(kind="questions") -> pack names
    get_pack(name) -> {"manifest": {...}, "templates": {...}}
    TemplateError                    # raised for malformed packs

A kind="questions" pack carries its questions as Markdown templates
(templates/*.md). Each question is a ``##`` block and MUST carry a
``Source:`` line with a link - enforced end to end (the verified-only rule:
a question without a citable source is rejected, never imported).

Imported questions land in the user data dir (CANDID_DATA_DIR-overridable)
as an overlay in the same entry shape as
candid.prep_questions.QUESTIONS_DB, tagged with the pack name + version.
A small registry records which pack versions were imported, so re-importing
the same version is a no-op and a newer version imports only genuinely new
questions (dedupe by normalized question text).

Stdlib only, no network calls: packs are local files.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone

from candid import config as C

__all__ = [
    "QuestionPackError",
    "OVERLAY_FILENAME",
    "REGISTRY_FILENAME",
    "slugify_company",
    "parse_question_templates",
    "import_pack",
    "list_pack_questions",
    "merged_questions_db",
    "load_overlay",
    "load_registry",
    "render_import_summary",
    "render_pack_questions",
]

#: Overlay of pack-imported questions, in QUESTIONS_DB entry shape.
OVERLAY_FILENAME = "question_pack_questions.json"
#: Which pack versions have been imported.
REGISTRY_FILENAME = "question_pack_imports.json"

_URL_RE = re.compile(r"https?://\S+")
_BLOCK_RE = re.compile(r"^##\s+(.*\S)?\s*$")
_META_RE = re.compile(
    r"^(category|difficulty|frequency|reported)\s*:\s*(.+?)\s*$", re.IGNORECASE
)
_SOURCE_RE = re.compile(r"^source\s*:\s*(.+?)\s*$", re.IGNORECASE)


class QuestionPackError(Exception):
    """Raised when the template gallery (candid/templates.py) is unavailable."""


def _templates_module():
    """Lazy import of candid.templates with a graceful error message.

    sys.modules is checked first so tests can inject a stub.
    """
    mod = sys.modules.get("candid.templates")
    if mod is not None:
        return mod
    try:
        import importlib

        return importlib.import_module("candid.templates")
    except ImportError:
        raise QuestionPackError(
            "The template gallery is not available: candid/templates.py "
            "could not be imported, so `templates questions` cannot run. "
            "The gallery module is built by batch-106 worker A."
        ) from None


def _pack_error(message: str) -> Exception:
    """Pack validation errors surface as TemplateError when the gallery exists."""
    mod = sys.modules.get("candid.templates")
    if mod is None:
        try:
            import importlib

            mod = importlib.import_module("candid.templates")
        except ImportError:
            return QuestionPackError(message)
    return mod.TemplateError(message)


def slugify_company(company: str) -> str:
    """Normalize a company name the same way candid.prep._find_company does."""
    return "".join(c for c in str(company).lower() if c.isalnum())


def _norm(text: str) -> str:
    """Dedupe key: whitespace-collapsed, case-folded question text."""
    return " ".join(str(text).split()).casefold()


# ---------------------------------------------------------------------------
# Storage: overlay + registry in the user data dir
# ---------------------------------------------------------------------------

def _overlay_path():
    return C.DATA_DIR / OVERLAY_FILENAME


def _registry_path():
    return C.DATA_DIR / REGISTRY_FILENAME


def load_overlay() -> dict:
    """Pack-imported questions: {"version": 1, "companies": {slug: [entries]}}."""
    path = _overlay_path()
    if not path.exists():
        return {"version": 1, "companies": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "companies": {}}
    if not isinstance(data, dict) or not isinstance(data.get("companies"), dict):
        return {"version": 1, "companies": {}}
    return data


def save_overlay(data: dict) -> None:
    path = _overlay_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def load_registry() -> dict:
    """{pack_name: {"version", "company", "imported_at", "added"}}."""
    path = _registry_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_registry(data: dict) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def merged_questions_db() -> dict:
    """QUESTIONS_DB merged with the pack overlay (module constant untouched).

    Overlay entries keep the exact entry shape of prep_questions
    (q/category/source/url/reported [+ difficulty/frequency]) plus
    ``pack`` and ``pack_version`` provenance tags.
    """
    from candid.prep_questions import QUESTIONS_DB

    merged = {slug: [dict(e) for e in entries]
              for slug, entries in QUESTIONS_DB.items()}
    for slug, entries in load_overlay().get("companies", {}).items():
        merged.setdefault(slug, []).extend(dict(e) for e in entries)
    return merged


def _known_question_texts() -> set:
    known = set()
    for entries in merged_questions_db().values():
        for e in entries:
            q = e.get("q")
            if q:
                known.add(_norm(q))
    return known


# ---------------------------------------------------------------------------
# Parsing: templates/*.md -> question entries
# ---------------------------------------------------------------------------

def _iter_template_texts(pack: dict, pack_name: str) -> list:
    """Normalize get_pack()['templates'] into (filename, markdown) pairs."""
    templates = pack.get("templates") if isinstance(pack, dict) else None
    if templates is None:
        raise _pack_error(
            f"pack '{pack_name}' has no templates to read "
            "(expected get_pack() -> {'manifest': ..., 'templates': ...})"
        )
    if isinstance(templates, dict):
        items = list(templates.items())
    elif isinstance(templates, (list, tuple)):
        items = [(None, t) for t in templates]
    else:
        raise _pack_error(
            f"pack '{pack_name}': unsupported templates shape "
            f"{type(templates).__name__} (expected a dict or list)"
        )
    out = []
    for i, (name, payload) in enumerate(items):
        if isinstance(payload, str):
            text = payload
        elif isinstance(payload, dict):
            text = (payload.get("content") or payload.get("text")
                    or payload.get("body") or payload.get("markdown") or "")
            if name is None:
                name = (payload.get("name") or payload.get("filename")
                        or payload.get("title"))
        else:
            text = str(payload)
        out.append((name or f"template-{i + 1}.md",
                    text if isinstance(text, str) else str(text)))
    return out


def _finalize_block(tname: str, block: dict) -> dict:
    """Validate one ``##`` block (verified-only rule) and build the entry."""
    start = block["start_line"]
    heading = block["heading"] or "untitled question"
    qtext = "\n".join(block["lines"]).strip()
    if not qtext:
        raise _pack_error(
            f"template '{tname}' line {start}: question block '{heading}' "
            "has no question text"
        )
    if not block["source"]:
        raise _pack_error(
            f"template '{tname}' line {start}: question '{heading}' is "
            "missing a Source: link - every imported question must cite "
            "where it was reported"
        )
    src_line = block["source"][0]
    url_m = _URL_RE.search(src_line)
    if not url_m:
        raise _pack_error(
            f"template '{tname}' line {block['source_line']}: the Source: "
            f"line for '{heading}' has no link ({src_line!r}) - a URL is "
            "required so the question stays verifiable"
        )
    url = url_m.group(0).rstrip(").,;")
    source = _URL_RE.sub("", src_line).strip(" -–—:\t")
    entry = {
        "q": qtext,
        "category": block["meta"].get("category", "general"),
        "source": source or url,
        "url": url,
        "reported": block["meta"].get("reported", ""),
    }
    for opt in ("difficulty", "frequency"):
        if opt in block["meta"]:
            entry[opt] = block["meta"][opt]
    entry["template"] = tname
    return entry


def _parse_one_template(tname: str, text: str) -> list:
    questions = []
    block = None

    def flush():
        nonlocal block
        if block is not None:
            questions.append(_finalize_block(tname, block))
            block = None

    for lineno, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        m = _BLOCK_RE.match(stripped)
        if m:
            flush()
            block = {"heading": (m.group(1) or "").strip(),
                     "start_line": lineno, "meta": {},
                     "source": [], "source_line": 0, "lines": []}
            continue
        if block is None:
            continue  # title / preamble outside any question block
        if not stripped:
            continue
        mm = _META_RE.match(stripped)
        if mm:
            block["meta"][mm.group(1).lower()] = mm.group(2).strip()
            continue
        sm = _SOURCE_RE.match(stripped)
        if sm:
            block["source"].append(sm.group(1).strip())
            block["source_line"] = lineno
            continue
        block["lines"].append(stripped)
    flush()
    return questions


def parse_question_templates(template_texts: list, pack_name: str = "") -> list:
    """Parse ``[(filename, markdown), ...]`` into question-bank entries.

    Raises the gallery's TemplateError (verified-only rule) when a block
    lacks a Source: link, has no question text, or the Source: line has
    no URL. Error messages name the template file and the line number.
    """
    questions = []
    for tname, text in template_texts:
        questions.extend(_parse_one_template(tname, text or ""))
    return questions


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def import_pack(pack_name: str, company: str = "", dry_run: bool = False) -> dict:
    """Import a kind="questions" pack into the question-bank overlay.

    Returns a summary dict (also used for --json). Raises TemplateError /
    QuestionPackError for: unknown pack, wrong kind, missing Source: links,
    missing company target, or an empty pack.
    """
    T = _templates_module()
    pack = T.get_pack(pack_name)  # TemplateError propagates for unknown packs
    if not isinstance(pack, dict):
        raise _pack_error(
            f"pack '{pack_name}': get_pack() returned "
            f"{type(pack).__name__}, expected a dict"
        )
    manifest = pack.get("manifest") or {}
    if not isinstance(manifest, dict):
        manifest = {}
    kind = manifest.get("kind")
    if kind != "questions":
        raise _pack_error(
            f"pack '{pack_name}' is a '{kind or 'unknown'}' pack, not a "
            "'questions' pack - refusing to import into the question bank"
        )
    version = str(manifest.get("version") or "0")
    target = (company or manifest.get("company") or "").strip()
    if not target:
        raise _pack_error(
            f"pack '{pack_name}' does not name a company and --company was "
            "not given - pass --company \"Acme\" to choose where the "
            "questions land"
        )
    slug = slugify_company(target)
    if not slug:
        raise _pack_error(f"company {target!r} normalizes to an empty slug")

    parsed = parse_question_templates(
        _iter_template_texts(pack, pack_name), pack_name=pack_name)
    if not parsed:
        raise _pack_error(
            f"pack '{pack_name}' contains no question blocks - expected "
            "'##' blocks with a Source: link in templates/*.md"
        )
    for q in parsed:
        q["pack"] = pack_name
        q["pack_version"] = version

    registry = load_registry()
    prev = registry.get(pack_name) or {}
    if prev.get("version") == version and prev.get("company") == slug \
            and not dry_run:
        return {
            "status": "no-op",
            "pack": pack_name,
            "version": version,
            "company": target,
            "slug": slug,
            "detail": (f"version {version} already imported for "
                       f"'{target}' - nothing to do"),
        }

    existing = _known_question_texts()
    new, dupes, seen = [], 0, set()
    for q in parsed:
        n = _norm(q["q"])
        if n in existing or n in seen:
            dupes += 1
            continue
        seen.add(n)
        new.append(q)

    if dry_run:
        return {
            "status": "dry-run",
            "pack": pack_name,
            "version": version,
            "company": target,
            "slug": slug,
            "total_in_pack": len(parsed),
            "would_add": len(new),
            "skipped_duplicates": dupes,
            "questions": new,
        }

    overlay = load_overlay()
    overlay.setdefault("companies", {}).setdefault(slug, []).extend(new)
    save_overlay(overlay)
    registry[pack_name] = {
        "version": version,
        "company": slug,
        "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "added": len(new),
    }
    save_registry(registry)
    return {
        "status": "imported",
        "pack": pack_name,
        "version": version,
        "company": target,
        "slug": slug,
        "total_in_pack": len(parsed),
        "added": len(new),
        "skipped_duplicates": dupes,
        "questions": new,
    }


def list_pack_questions(company: str = "") -> list:
    """Questions contributed by packs, tagged with pack name + version."""
    companies = load_overlay().get("companies", {})
    if company:
        slug = slugify_company(company)
        items = [(slug, e) for e in companies.get(slug, [])]
    else:
        items = [(s, e) for s, es in sorted(companies.items())
                 for e in es]
    return [{"company_slug": s, **dict(e)} for s, e in items]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_import_summary(res: dict) -> str:
    """Human-readable summary of an import_pack() result."""
    head = (f"Pack '{res['pack']}' v{res['version']} -> "
            f"{res['company']} ({res['slug']})")
    if res["status"] == "no-op":
        return head + f"\nNo-op: {res['detail']}"
    if res["status"] == "dry-run":
        lines = [head,
                 f"Dry run: would add {res['would_add']} of "
                 f"{res['total_in_pack']} questions "
                 f"({res['skipped_duplicates']} duplicates skipped).",
                 ""]
    else:
        lines = [head,
                 f"Imported {res['added']} of {res['total_in_pack']} "
                 f"questions ({res['skipped_duplicates']} duplicates "
                 "skipped).",
                 ""]
    for i, q in enumerate(res["questions"], 1):
        lines.append(f"{i}. [{q.get('category', 'general')}] {q['q']}")
        lines.append(f"   Source: {q.get('source', '')} - {q.get('url', '')}")
    if res["status"] == "dry-run":
        lines += ["", "Re-run without --dry-run to import."]
    return "\n".join(lines)


def render_pack_questions(qs: list, company: str = "") -> str:
    """Human-readable listing of pack-contributed questions."""
    title = "Pack-contributed questions" + (f" for {company}" if company else "")
    if not qs:
        return (f"{title}\nNo pack-contributed questions"
                + (f" for {company}" if company else "")
                + " yet - import one with "
                  "`python -m candid templates questions import <pack>`.")
    lines = [title, f"{len(qs)} question(s)", ""]
    for i, q in enumerate(qs, 1):
        tag = f"[pack: {q.get('pack', '?')} v{q.get('pack_version', '?')}]"
        lines.append(f"{i}. {tag} [{q.get('category', 'general')}] {q['q']}")
        lines.append(f"   Source: {q.get('source', '')} - {q.get('url', '')}")
    return "\n".join(lines)

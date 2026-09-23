"""Morning-of interview ritual: ordered review materials bundle.

``python -m candid ritual materials --company X --role Y`` (CLI wired by a
separate worker via lazy imports) collects everything candid already knows
about an upcoming interview into ONE ordered review list:

  1. latest tailored resume variant (candid_data/tailored/)
  2. cover letter, if one exists (candid_data/tailored/)
  3. prep pack questions (candid_data/prep_packs/)
  4. debriefs from earlier rounds, if any (candid_data/debriefs/)
  5. company brief, if one exists (candid_data/company_briefs/)
  6. tracker notes for the application

Every source is optional. Missing dirs or files are skipped silently and
recorded in the ``notes`` list, never crash the build. Each item carries an
estimated review time in minutes.

Completion tracking is persisted per ritual under
candid_data/rituals/<ritual_id>/materials.json; mark items reviewed with
``check_item(ritual_id, n)``.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date
from pathlib import Path

from candid import config as C

try:
    from candid import tracker as _tracker
except Exception:  # pragma: no cover - tracker is optional here
    _tracker = None


class RitualError(Exception):
    """Raised for ritual usage problems (bad input, unknown ritual/item)."""


# ---------------------------------------------------------------------------
# paths (resolved fresh each call so CANDID_DATA_DIR overrides always work)
# ---------------------------------------------------------------------------

def data_dir() -> Path:
    """User data dir, honoring CANDID_DATA_DIR even if set after import."""
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return C.DATA_DIR


def rituals_dir() -> Path:
    return data_dir() / "rituals"


def _tailored_dir() -> Path:
    return data_dir() / "tailored"


def _prep_packs_dir() -> Path:
    return data_dir() / "prep_packs"


def _debriefs_dir() -> Path:
    return data_dir() / "debriefs"


def _briefs_dir() -> Path:
    return data_dir() / "company_briefs"


_TEXT_EXTS = {".md", ".txt", ".markdown"}


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")


def _tokens(text: str) -> list[str]:
    return [t for t in _slug(text).split("_") if len(t) > 1]


def new_ritual_id(company: str, role: str) -> str:
    """Fresh ritual id like ``acme_data-scientist_2026-09-22_a1b2c3``."""
    return f"{_slug(company)}_{_slug(role)}_{date.today().isoformat()}_{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------
# file discovery (all defensive: missing dirs, unreadable files -> skip)
# ---------------------------------------------------------------------------

def _safe_list(dirpath: Path) -> list[Path]:
    try:
        if not dirpath.is_dir():
            return []
        return [p for p in dirpath.iterdir()
                if p.is_file() and p.suffix.lower() in _TEXT_EXTS]
    except OSError:
        return []


def _match_score(path: Path, company: str, role: str) -> int:
    """How well a filename matches company+role. 0 = no match."""
    name = _slug(path.stem)
    ctoks = _tokens(company)
    rtoks = _tokens(role)
    c = sum(1 for t in ctoks if t in name)
    r = sum(1 for t in rtoks if t in name)
    if not c and not r:
        return 0
    if not c or not r:
        return 1  # partial: company or role only
    return 2  # both


def _best_match(dirpath: Path, company: str, role: str,
                extra_filter=None) -> Path | None:
    """Newest file in dirpath matching company+role (and extra_filter)."""
    cands = []
    for p in _safe_list(dirpath):
        if extra_filter is not None and not extra_filter(p):
            continue
        score = _match_score(p, company, role)
        if score:
            try:
                cands.append((score, p.stat().st_mtime, p))
            except OSError:
                continue
    if not cands:
        return None
    cands.sort(key=lambda t: (t[0], t[1]))
    return cands[-1][2]


def _all_matches(dirpath: Path, company: str, role: str) -> list[Path]:
    """All company+role matches, oldest first (earlier rounds first)."""
    cands = []
    for p in _safe_list(dirpath):
        score = _match_score(p, company, role)
        if score:
            try:
                cands.append((p.stat().st_mtime, p))
            except OSError:
                continue
    cands.sort(key=lambda t: t[0])
    return [p for _, p in cands]


def _is_cover_letter(p: Path) -> bool:
    return "cover" in _slug(p.stem)


def _tracker_notes(company: str, role: str) -> str:
    """Notes on the tracker record for company+role, or ''."""
    if _tracker is None:
        return ""
    try:
        apps = _tracker.list_apps(path=data_dir() / "tracker.json")
    except Exception:
        return ""
    cl, rl = company.strip().lower(), role.strip().lower()
    for a in apps:
        if (a.get("company", "").strip().lower() == cl
                and a.get("role", "").strip().lower() == rl):
            return str(a.get("notes", "") or "").strip()
    return ""


# ---------------------------------------------------------------------------
# build / save / load / check
# ---------------------------------------------------------------------------

# estimated review minutes per item kind
_MINUTES = {
    "resume": 10,
    "cover_letter": 5,
    "prep_pack": 20,
    "debrief": 10,
    "company_brief": 10,
    "tracker_notes": 5,
}


def build_materials(company: str, role: str,
                    ritual_id: str | None = None) -> dict:
    """Build the ordered review bundle and persist it. Returns the dict.

    The dict has keys: ritual_id, company, role, created, items, notes,
    total_minutes. Each item: n, kind, title, path, minutes, reviewed.
    """
    company = (company or "").strip()
    role = (role or "").strip()
    if not company or not role:
        raise RitualError("Both company and role are required.")

    ritual_id = ritual_id or new_ritual_id(company, role)
    items: list[dict] = []
    notes: list[str] = []

    def add(kind: str, title: str, path: Path | str | None,
            detail: str = "", text: str = "") -> None:
        item = {
            "n": len(items) + 1,
            "kind": kind,
            "title": title + (f" ({detail})" if detail else ""),
            "path": str(path) if path else "",
            "minutes": _MINUTES[kind],
            "reviewed": False,
        }
        if text:
            item["text"] = text
        items.append(item)

    # 1. latest tailored resume variant
    resume = _best_match(_tailored_dir(), company, role,
                         extra_filter=lambda p: not _is_cover_letter(p))
    if resume is not None:
        add("resume", "Tailored resume (latest variant)", resume)
    else:
        notes.append("No tailored resume found in tailored/ - "
                     "run tailor first so you review the right version.")

    # 2. cover letter
    letter = _best_match(_tailored_dir(), company, role,
                         extra_filter=_is_cover_letter)
    if letter is not None:
        add("cover_letter", "Cover letter", letter)
    else:
        notes.append("No cover letter found in tailored/ - skipped.")

    # 3. prep pack
    pack = _best_match(_prep_packs_dir(), company, role)
    if pack is not None:
        add("prep_pack", "Prep pack questions", pack)
    else:
        notes.append("No prep pack found in prep_packs/ - "
                     "run prep first for interview questions.")

    # 4. debriefs from earlier rounds (oldest round first)
    debriefs = _all_matches(_debriefs_dir(), company, role)
    if debriefs:
        for p in debriefs:
            add("debrief", "Debrief: earlier round", p, p.stem)
    else:
        notes.append("No debriefs found in debriefs/ - nothing to learn from yet.")

    # 5. company brief
    brief = _best_match(_briefs_dir(), company, role)
    if brief is not None:
        add("company_brief", "Company brief", brief)
    else:
        notes.append("No company brief found in company_briefs/ - skipped.")

    # 6. tracker notes
    tn = _tracker_notes(company, role)
    if tn:
        add("tracker_notes", "Tracker notes for this application", "",
            f"{len(tn.split())} words", text=tn)
    else:
        notes.append("No tracker notes for this application - "
                     "add context with track update --notes.")

    materials = {
        "ritual_id": ritual_id,
        "company": company,
        "role": role,
        "created": date.today().isoformat(),
        "items": items,
        "notes": notes,
        "total_minutes": sum(i["minutes"] for i in items),
    }
    save_materials(ritual_id, materials)
    return materials


def save_materials(ritual_id: str, materials: dict) -> Path:
    """Persist a materials bundle. Returns the file path."""
    out = rituals_dir() / ritual_id / "materials.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(materials, indent=2), encoding="utf-8")
    return out


def load_materials(ritual_id: str) -> dict | None:
    """Load a persisted bundle, or None if it does not exist."""
    p = rituals_dir() / ritual_id / "materials.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def check_item(ritual_id: str, n: int) -> dict:
    """Mark item n reviewed and persist. Returns the updated item."""
    materials = load_materials(ritual_id)
    if materials is None:
        raise RitualError(f"No ritual found with id '{ritual_id}'.")
    for item in materials.get("items", []):
        if item.get("n") == n:
            item["reviewed"] = True
            save_materials(ritual_id, materials)
            return item
    raise RitualError(f"Item {n} not found in ritual '{ritual_id}'.")


def uncheck_item(ritual_id: str, n: int) -> dict:
    """Mark item n not reviewed and persist. Returns the updated item."""
    materials = load_materials(ritual_id)
    if materials is None:
        raise RitualError(f"No ritual found with id '{ritual_id}'.")
    for item in materials.get("items", []):
        if item.get("n") == n:
            item["reviewed"] = False
            save_materials(ritual_id, materials)
            return item
    raise RitualError(f"Item {n} not found in ritual '{ritual_id}'.")


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def render_materials(materials: dict) -> str:
    """Review-order summary with per-item minutes and check-off state."""
    lines = [
        f"Morning-of review: {materials['role']} @ {materials['company']}",
        f"Ritual id: {materials['ritual_id']} "
        f"(mark reviewed: python -m candid ritual materials check <n> "
        f"--ritual-id {materials['ritual_id']})",
        "",
    ]
    done = sum(1 for i in materials["items"] if i.get("reviewed"))
    total = len(materials["items"])
    lines.append(f"Progress: {done}/{total} reviewed")
    lines.append("")
    for item in materials["items"]:
        box = "[x]" if item.get("reviewed") else "[ ]"
        lines.append(f"{box} {item['n']}. {item['title']} "
                     f"~{item['minutes']} min")
        if item.get("path"):
            lines.append(f"       {item['path']}")
        if item.get("text"):
            snippet = item["text"].replace("\n", " ")
            if len(snippet) > 160:
                snippet = snippet[:157] + "..."
            lines.append(f"       \"{snippet}\"")
    lines.append("")
    lines.append(f"Estimated total: ~{materials['total_minutes']} minutes")
    if materials.get("notes"):
        lines.append("")
        lines.append("Notes:")
        for note in materials["notes"]:
            lines.append(f"  - {note}")
    return "\n".join(lines)

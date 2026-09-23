"""Professional reference sheet generator.

Referees are USER-SUPPLIED ONLY — this module stores and renders them,
and never invents anyone. Data lives in
``<DATA_DIR>/references.json`` (git-ignored), with ``CANDID_DATA_DIR``
honored at call time so tests and overrides work even when the env var
is set after import.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from candid import config as C


class ReferencesError(Exception):
    """Raised for invalid references data or operations on it."""


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------

def _data_dir() -> Path:
    """User data dir, honoring CANDID_DATA_DIR at call time."""
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return C.DATA_DIR


def _store_path() -> Path:
    return _data_dir() / "references.json"


def _load() -> list[dict]:
    p = _store_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReferencesError(
            f"References file {p} is not valid JSON: {exc}. "
            "Delete it to start over, or fix the formatting."
        ) from exc
    if not isinstance(data, list):
        raise ReferencesError(
            f"References file {p} is corrupt (expected a list)."
        )
    return [r for r in data if isinstance(r, dict)]


def _save(refs: list[dict]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(refs, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def add_reference(name: str, relationship: str,
                  contact: str = "", notes: str = "") -> dict:
    """Add a referee. Referees are user-supplied only — never invented.

    ``relationship`` describes how you know them, e.g. "Former manager".
    Raises ReferencesError if the name is blank or already stored.
    """
    name = (name or "").strip()
    relationship = (relationship or "").strip()
    if not name:
        raise ReferencesError("Referee name is required.")
    if not relationship:
        raise ReferencesError(
            f"Relationship is required for '{name}' "
            "(e.g. 'Former manager', 'Colleague')."
        )
    refs = _load()
    if any(r.get("name", "").lower() == name.lower() for r in refs):
        raise ReferencesError(f"'{name}' is already in your reference list.")
    ref = {
        "name": name,
        "relationship": relationship,
        "contact": (contact or "").strip(),
        "notes": (notes or "").strip(),
    }
    refs.append(ref)
    _save(refs)
    return ref


def list_references() -> list[dict]:
    """Return all stored referees, in the order they were added."""
    return _load()


def remove_reference(name: str) -> dict:
    """Remove a referee by name (case-insensitive). Returns the removed entry."""
    refs = _load()
    for i, r in enumerate(refs):
        if r.get("name", "").lower() == (name or "").strip().lower():
            removed = refs.pop(i)
            _save(refs)
            return removed
    raise ReferencesError(
        f"No referee named '{name}' found. "
        f"Stored referees: {', '.join(r.get('name', '') for r in refs) or '(none)'}."
    )


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

AVAILABLE_UPON_REQUEST = "References available upon request."


def _require_refs() -> list[dict]:
    refs = _load()
    if not refs:
        raise ReferencesError(
            "No referees stored yet — refusing to render an empty sheet.\n"
            "Next step: add_referee() one per person, e.g.\n"
            "    add_reference(name='Jane Doe', "
            "relationship='Former manager', contact='jane@example.com')"
        )
    return refs


def _entry_markdown(ref: dict) -> str:
    lines = [
        f"### {ref.get('name', '')}",
        "",
        f"- **Relationship:** {ref.get('relationship', '')}",
    ]
    if ref.get("contact"):
        lines.append(f"- **Contact:** {ref.get('contact', '')}")
    if ref.get("notes"):
        lines.append(f"- **Notes:** {ref.get('notes', '')}")
    return "\n".join(lines)


def _entry_text(ref: dict) -> str:
    lines = [
        f"Name:         {ref.get('name', '')}",
        f"Relationship: {ref.get('relationship', '')}",
    ]
    if ref.get("contact"):
        lines.append(f"Contact:      {ref.get('contact', '')}")
    if ref.get("notes"):
        lines.append(f"Notes:        {ref.get('notes', '')}")
    return "\n".join(lines)


def render_sheet(profile_name: str, output: str = "markdown",
                 on_request: bool = False) -> str:
    """Render a professional one-page reference sheet.

    ``output`` is "markdown" or "text". With ``on_request=True``, renders
    the short "References available upon request." alternative instead of
    listing referees. Raises ReferencesError (refusing to render) when no
    referees have been added.
    """
    if output not in ("markdown", "text"):
        raise ReferencesError(
            f"Unknown output '{output}'. Choose 'markdown' or 'text'."
        )
    name = (profile_name or "").strip() or "[fill in: your name]"

    if on_request:
        if output == "markdown":
            return f"# Professional References — {name}\n\n{AVAILABLE_UPON_REQUEST}\n"
        return (f"PROFESSIONAL REFERENCES — {name}\n\n"
                f"{AVAILABLE_UPON_REQUEST}\n")

    refs = _require_refs()
    if output == "markdown":
        body = [f"# Professional References — {name}", ""]
        for ref in refs:
            body.append(_entry_markdown(ref))
            body.append("")
        return "\n".join(body).rstrip() + "\n"
    body = [f"PROFESSIONAL REFERENCES — {name}", ""]
    for i, ref in enumerate(refs):
        body.append(_entry_text(ref))
        if i < len(refs) - 1:
            body.append("")
    return "\n".join(body) + "\n"

"""Persistent polished-answer library with a mandatory human approval gate.

Answers produced by ``candid polish run`` are parked here via
``polish_library.save_entry`` and start life as ``pending``. Nothing is
"accepted" until a human reviews the unified diff produced by
``render_approval`` and explicitly calls ``approve``. Approved answers are
the ones the interview-prep machinery should surface; rejected ones are
kept for reference.

All rule-based and deterministic. No network, no APIs, no LLM calls.

Storage: DATA_DIR/polish_library.json — a JSON list of entries:
    {id, name, question, original, polished, status, story_id,
     created_at}
``status`` is one of "pending", "approved", "rejected".
"""

from __future__ import annotations

import difflib
import json
import uuid
from datetime import datetime, timezone

from candid import config as C

LIBRARY_PATH = C.DATA_DIR / "polish_library.json"
LAST_PATH = C.DATA_DIR / "polish_last.json"

STATUSES = ("pending", "approved", "rejected")


class LibraryError(Exception):
    """Raised for library misuse: missing files, unknown ids, bad input."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load() -> list[dict]:
    if not LIBRARY_PATH.exists():
        return []
    try:
        data = json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LibraryError(f"Corrupt library file {LIBRARY_PATH}: {exc}") from exc
    if not isinstance(data, list):
        raise LibraryError(f"Corrupt library file {LIBRARY_PATH}: expected a list")
    return data


def _save(entries: list[dict]) -> None:
    LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIBRARY_PATH.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _new_id() -> str:
    return "pl-" + uuid.uuid4().hex[:8]


def read_last() -> dict:
    """Load DATA_DIR/polish_last.json written by the core engine's `polish run`.

    Returns the dict as written (expected keys: original, polished, and
    optionally question). Raises LibraryError if the file is absent or
    unreadable.
    """
    if not LAST_PATH.exists():
        raise LibraryError(
            f"No {LAST_PATH.name} found - run `candid polish run` first, "
            "or pass original/polished text explicitly."
        )
    try:
        data = json.loads(LAST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LibraryError(f"Could not read {LAST_PATH}: {exc}") from exc
    if not isinstance(data, dict):
        raise LibraryError(f"Could not read {LAST_PATH}: expected a JSON object")
    return data


def save_entry(
    name: str,
    question: str | None = None,
    original: str | None = None,
    polished: str | None = None,
    star: dict | None = None,
) -> str:
    """Save a polished answer to the library. Status starts as "pending".

    When original/polished are not given, they (and question, if unset)
    are pulled from read_last(). ``star`` optionally records the STAR
    breakdown the polisher produced. Returns the new entry id.
    """
    if not name or not name.strip():
        raise LibraryError("Entry name is required")
    name = name.strip()

    last: dict | None = None
    if original is None or polished is None:
        last = read_last()
    if original is None:
        original = last.get("original") if isinstance(last, dict) else None
    if polished is None:
        polished = last.get("polished") if isinstance(last, dict) else None
    if question is None and last:
        question = last.get("question")

    if not original or not original.strip():
        raise LibraryError("Original answer text is missing (or empty)")
    if not polished or not polished.strip():
        raise LibraryError("Polished answer text is missing (or empty)")

    entries = _load()
    entry = {
        "id": _new_id(),
        "name": name,
        "question": question or "",
        "original": original,
        "polished": polished,
        "status": "pending",
        "story_id": None,
        "created_at": _utcnow(),
    }
    if star is not None:
        entry["star"] = star
    entries.append(entry)
    _save(entries)
    return entry["id"]


def get_entry(entry_id: str) -> dict:
    """Return a copy of the entry with ``entry_id``. Raises LibraryError."""
    for entry in _load():
        if entry.get("id") == entry_id:
            return dict(entry)
    raise LibraryError(f"Unknown library entry: {entry_id!r}")


def list_entries(status: str | None = None, query: str | None = None) -> list[dict]:
    """List entries, optionally filtered by status and/or substring query.

    ``query`` matches case-insensitively against name and question.
    """
    if status is not None and status not in STATUSES:
        raise LibraryError(f"Unknown status {status!r}. Choose from {STATUSES}.")
    results = _load()
    if status is not None:
        results = [e for e in results if e.get("status") == status]
    if query:
        q = query.lower()
        results = [
            e
            for e in results
            if q in str(e.get("name", "")).lower()
            or q in str(e.get("question", "")).lower()
        ]
    return results


def _diff_stats(diff_text: str) -> tuple[int, int]:
    added = removed = 0
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def _word_count(text: str) -> int:
    return len(text.split())


def render_approval(entry_id: str) -> str:
    """Render the approval view for an entry: header, unified diff, stats.

    This is what the user reviews before calling approve() or reject().
    """
    entry = get_entry(entry_id)
    original = entry.get("original", "")
    polished = entry.get("polished", "")

    diff_lines = list(
        difflib.unified_diff(
            original.splitlines(),
            polished.splitlines(),
            fromfile="original",
            tofile="polished",
            lineterm="",
        )
    )
    diff_text = "\n".join(diff_lines) if diff_lines else "(no differences)"
    added, removed = _diff_stats(diff_text)
    w_orig = _word_count(original)
    w_pol = _word_count(polished)
    saved = w_orig - w_pol
    saved_txt = f"{saved:+d}" if saved != 0 else "0"

    header = (
        f"Answer: {entry.get('name', '')} [{entry_id}]\n"
        f"Question: {entry.get('question') or '(none)'}\n"
        f"Status: {entry.get('status', '')}\n"
        f"Story: {entry.get('story_id') or '(none)'}\n"
    )
    stats = (
        f"lines: +{added} -{removed} | words: {w_orig} -> {w_pol} "
        f"({saved_txt} saved)"
    )
    return f"{header}\n{diff_text}\n\n{stats}\n"


def _set_status(entry_id: str, status: str) -> dict:
    entries = _load()
    for entry in entries:
        if entry.get("id") == entry_id:
            entry["status"] = status
            _save(entries)
            return entry
    raise LibraryError(f"Unknown library entry: {entry_id!r}")


def approve(entry_id: str) -> str:
    """Approve an entry after human review. Returns the diff text again."""
    _set_status(entry_id, "approved")
    return render_approval(entry_id)


def reject(entry_id: str) -> str:
    """Reject an entry. Returns the diff text for the record."""
    _set_status(entry_id, "rejected")
    return render_approval(entry_id)


def delete(entry_id: str) -> None:
    """Delete an entry from the library."""
    entries = _load()
    kept = [e for e in entries if e.get("id") != entry_id]
    if len(kept) == len(entries):
        raise LibraryError(f"Unknown library entry: {entry_id!r}")
    _save(kept)


def link_story(entry_id: str, story_id: str) -> dict:
    """Attach a story-bank id to an entry (stored as a plain string id).

    candid/stories.py lives on another branch; this function takes the
    story id as a string on purpose - no hard dependency either way.
    """
    if not story_id or not str(story_id).strip():
        raise LibraryError("story_id is required")
    entries = _load()
    for entry in entries:
        if entry.get("id") == entry_id:
            entry["story_id"] = str(story_id).strip()
            _save(entries)
            return dict(entry)
    raise LibraryError(f"Unknown library entry: {entry_id!r}")


def stats() -> dict:
    """Counts by status, plus total words saved (original - polished)."""
    entries = _load()
    counts = {s: 0 for s in STATUSES}
    words_saved = 0
    for entry in entries:
        status = entry.get("status")
        if status in counts:
            counts[status] += 1
        words_saved += _word_count(entry.get("original", "")) - _word_count(
            entry.get("polished", "")
        )
    return {
        "total": len(entries),
        "pending": counts["pending"],
        "approved": counts["approved"],
        "rejected": counts["rejected"],
        "words_saved": words_saved,
    }

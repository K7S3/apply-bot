"""Per-application notes and file attachments.

Notes are timestamped text entries stored per application id in
``C.DATA_DIR/app_notes.json`` (git-ignored).

Attachments copy user-supplied files into ``C.DATA_DIR/attachments/<app_id>/``
(git-ignored, never committed to the repo), with metadata recorded in
``C.DATA_DIR/attachments.json``. Filenames are sanitized and the total stored
size per application is capped at :data:`MAX_ATTACHMENT_BYTES`.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from candid import config as C

#: Maximum total attachment size per application (25 MiB).
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


class AppNotesError(Exception):
    """Raised for invalid notes/attachment operations."""


# --- path resolution ----------------------------------------------------------


def _data_dir(path: str | Path | None) -> Path:
    if path is None:
        return C.DATA_DIR
    p = Path(path)
    return p if p.suffix != ".json" else p.parent


def _notes_path(path: str | Path | None = None) -> Path:
    if path is not None and Path(path).suffix == ".json":
        return Path(path)
    return _data_dir(path) / "app_notes.json"


def _attachments_path(path: str | Path | None = None) -> Path:
    return _data_dir(path) / "attachments.json"


def _attachments_dir(app_id: int, path: str | Path | None = None) -> Path:
    return _data_dir(path) / "attachments" / str(app_id)


def _require_app(app_id: int, path: str | Path | None = None) -> dict:
    """Validate that app_id exists in the tracker; return the record."""
    from candid import tracker as T
    data_dir = _data_dir(path) if path is not None else None
    tpath = data_dir / "tracker.json" if data_dir is not None else None
    apps = T.list_apps(path=tpath) if tpath is not None else T.list_apps()
    for app in apps:
        if app.get("id") == app_id:
            return app
    raise AppNotesError(
        f"No tracked application with id {app_id}.\n"
        "Run `python -m candid track list` to see application ids."
    )


def _load_json(p: Path, what: str) -> dict:
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AppNotesError(f"{what} file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise AppNotesError(f"{what} file {p} should contain a JSON object.")
    return data


def _save_json(p: Path, data: dict) -> None:
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


# --- notes --------------------------------------------------------------------


def add_note(app_id: int, text: str, *, path: str | Path | None = None) -> dict:
    """Add a timestamped note to an application. Returns the new entry."""
    _require_app(app_id, path)
    text = (text or "").strip()
    if not text:
        raise AppNotesError(
            "Cannot add an empty note. Provide the note text as the argument, "
            "e.g. `python -m candid note add --app-id 3 \"met hiring manager\"`."
        )
    p = _notes_path(path)
    notes = _load_json(p, "Notes")
    key = str(app_id)
    entries = notes.setdefault(key, [])
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "text": text,
    }
    entries.append(entry)
    _save_json(p, notes)
    return entry


def list_notes(app_id: int, *, path: str | Path | None = None) -> list[dict]:
    """Return the timestamped notes for an application (oldest first)."""
    _require_app(app_id, path)
    notes = _load_json(_notes_path(path), "Notes")
    return [dict(e) for e in notes.get(str(app_id), [])]


def render_notes(app_id: int, entries: list[dict]) -> str:
    """Human-readable rendering of a note list."""
    if not entries:
        return f"No notes for application #{app_id} yet."
    lines = [f"Notes for application #{app_id}:"]
    for e in entries:
        lines.append(f"  [{e.get('timestamp', '?')}] {e.get('text', '')}")
    return "\n".join(lines)


# --- attachments --------------------------------------------------------------


def _sanitize_filename(name: str) -> str:
    """Strip path components and unsafe characters from a filename."""
    base = Path(name).name.strip()
    base = base.lstrip(".")
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    base = re.sub(r"_+", "_", base).strip("._")
    if not base:
        base = "file"
    stem, dot, ext = base.rpartition(".")
    if dot and len(ext) <= 10:
        stem = stem[:100] or "file"
        base = f"{stem}.{ext}"
    else:
        base = base[:110]
    return base


def _unique_name(directory: Path, name: str) -> str:
    """Avoid overwriting: resume.pdf, resume_2.pdf, resume_3.pdf, ..."""
    candidate = name
    stem, dot, ext = name.rpartition(".")
    i = 2
    while (directory / candidate).exists():
        candidate = f"{stem}_{i}{dot}{ext}" if dot else f"{name}_{i}"
        i += 1
    return candidate


def _used_bytes(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(f.stat().st_size for f in directory.iterdir() if f.is_file())


def attach(app_id: int, src: str | Path, *, path: str | Path | None = None) -> dict:
    """Copy a user file into the app's attachment store. Returns metadata.

    The source file is never moved or modified; a sanitized copy is stored.
    Raises AppNotesError if the per-app size cap would be exceeded.
    """
    _require_app(app_id, path)
    src = Path(src)
    if not src.is_file():
        raise AppNotesError(
            f"Attachment source not found: {src}\n"
            "Pass an existing file, e.g. `python -m candid attach add "
            f"--app-id {app_id} resume_tailored.pdf`."
        )
    size = src.stat().st_size
    dest_dir = _attachments_dir(app_id, path)
    dest_dir.mkdir(parents=True, exist_ok=True)
    used = _used_bytes(dest_dir)
    if used + size > MAX_ATTACHMENT_BYTES:
        raise AppNotesError(
            f"Attachment ({size / 1024 / 1024:.1f} MiB) would exceed the "
            f"{MAX_ATTACHMENT_BYTES // 1024 // 1024} MiB per-application cap "
            f"({used / 1024 / 1024:.1f} MiB already stored for app #{app_id}).\n"
            f"Remove an attachment first: "
            f"`python -m candid attach list --app-id {app_id}`."
        )
    stored = _unique_name(dest_dir, _sanitize_filename(src.name))
    shutil.copyfile(src, dest_dir / stored)

    meta_path = _attachments_path(path)
    meta = _load_json(meta_path, "Attachments")
    entries = meta.setdefault(str(app_id), [])
    entries = [e for e in entries if (dest_dir / e.get("filename", "")).exists()]
    record = {
        "filename": stored,
        "original_name": src.name,
        "size_bytes": size,
        "added_at": datetime.now().isoformat(timespec="seconds"),
    }
    entries.append(record)
    meta[str(app_id)] = entries
    _save_json(meta_path, meta)
    return record


def list_attachments(app_id: int, *, path: str | Path | None = None) -> list[dict]:
    """Return attachment metadata for an application (oldest first)."""
    _require_app(app_id, path)
    meta = _load_json(_attachments_path(path), "Attachments")
    return [dict(e) for e in meta.get(str(app_id), [])]


def open_path(app_id: int, filename: str, *, path: str | Path | None = None) -> Path:
    """Return the on-disk path of a stored attachment.

    Callers open the file themselves (candid never executes attachments).
    """
    _require_app(app_id, path)
    safe = _sanitize_filename(filename)
    dest = _attachments_dir(app_id, path) / safe
    if not dest.is_file():
        raise AppNotesError(
            f"No attachment '{filename}' for application #{app_id}.\n"
            f"Run `python -m candid attach list --app-id {app_id}` to see "
            "stored attachments."
        )
    return dest


def render_attachments(app_id: int, entries: list[dict]) -> str:
    """Human-readable rendering of an attachment list."""
    if not entries:
        return f"No attachments for application #{app_id} yet."
    lines = [f"Attachments for application #{app_id}:"]
    for e in entries:
        mb = e.get("size_bytes", 0) / 1024 / 1024
        lines.append(
            f"  {e.get('filename', '?')} ({mb:.1f} MiB, "
            f"added {e.get('added_at', '?')})"
        )
    return "\n".join(lines)

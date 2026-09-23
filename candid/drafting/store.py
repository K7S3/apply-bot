"""Per-application draft storage.

Drafts (subject + body) are persisted as JSON files under the drafts dir
inside candid's data dir (see candid/config.py). Each ``save_draft`` call
creates a *new version* -- existing files are never overwritten -- so a
per-application version history accumulates and can be listed, diffed, and
reloaded.

All paths honor the ``data_dir`` parameter (tests) or fall back to the
``CANDID_DATA_DIR`` env override / default from candid/config.py.
"""

from __future__ import annotations

import difflib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from candid import config


def drafts_dir(data_dir: "str | Path | None" = None) -> Path:
    """Resolve the drafts directory, creating it if needed."""
    base = Path(data_dir) if data_dir is not None else config.DATA_DIR
    d = base / "drafts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_app_id(app_id: str) -> str:
    """Make an app id safe for use as a directory name."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(app_id))


def _next_version(app_dir: Path) -> int:
    """Next 1-based version number for an app directory."""
    highest = 0
    for p in app_dir.glob("v*.json"):
        m = re.fullmatch(r"v(\d+)", p.stem)
        if m:
            highest = max(highest, int(m.group(1)))
    return highest + 1


def save_draft(
    app_id: str,
    draft: dict,
    kind: str | None = None,
    data_dir: "str | Path | None" = None,
) -> str:
    """Persist a draft (``{"subject": ..., "body": ...}``) as a new version.

    Never overwrites: every call writes a fresh ``vN`` JSON file under
    ``drafts/<app_id>/``. Returns the new ``draft_id`` (``"v1"``, ``"v2"`` ...).
    """
    app_dir = drafts_dir(data_dir) / _safe_app_id(app_id)
    app_dir.mkdir(parents=True, exist_ok=True)
    version = _next_version(app_dir)
    draft_id = f"v{version}"
    record = {
        "draft_id": draft_id,
        "app_id": app_id,
        "kind": kind,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "subject": str(draft.get("subject", "")),
        "body": str(draft.get("body", "")),
    }
    (app_dir / f"{draft_id}.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return draft_id


def list_drafts(
    app_id: str, data_dir: "str | Path | None" = None
) -> list[dict]:
    """List draft versions for an app_id: [{draft_id, kind, created}], sorted."""
    app_dir = drafts_dir(data_dir) / _safe_app_id(app_id)
    if not app_dir.is_dir():
        return []
    out = []
    for p in sorted(app_dir.glob("v*.json")):
        try:
            record = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append(
            {
                "draft_id": record.get("draft_id", p.stem),
                "kind": record.get("kind"),
                "created": record.get("created"),
            }
        )
    out.sort(key=lambda r: (r["created"] or "", r["draft_id"]))
    return out


def _find_draft_file(draft_id: str, data_dir: "str | Path | None") -> Path:
    root = drafts_dir(data_dir)
    stem = draft_id[:-5] if draft_id.endswith(".json") else draft_id
    if not re.fullmatch(r"v\d+", stem):
        raise ValueError(f"invalid draft_id: {draft_id!r}")
    for p in root.rglob(f"{stem}.json"):
        return p
    raise FileNotFoundError(f"no draft found with id {draft_id!r}")


def get_draft(draft_id: str, data_dir: "str | Path | None" = None) -> dict:
    """Load a draft record by draft_id. Raises FileNotFoundError if unknown."""
    p = _find_draft_file(draft_id, data_dir)
    return json.loads(p.read_text(encoding="utf-8"))


def _draft_text(record: dict) -> str:
    return f"Subject: {record.get('subject', '')}\n\n{record.get('body', '')}\n"


def diff_drafts(
    id_a: str, id_b: str, data_dir: "str | Path | None" = None
) -> str:
    """Unified diff of subject+body between two draft versions."""
    a = get_draft(id_a, data_dir)
    b = get_draft(id_b, data_dir)
    return "".join(
        difflib.unified_diff(
            _draft_text(a).splitlines(keepends=True),
            _draft_text(b).splitlines(keepends=True),
            fromfile=f"draft {a.get('draft_id', id_a)}",
            tofile=f"draft {b.get('draft_id', id_b)}",
        )
    )


def render_markdown(draft: dict) -> str:
    """Render a draft as Markdown: ``# <subject>`` heading followed by body."""
    subject = str(draft.get("subject", "")).strip()
    body = str(draft.get("body", "")).rstrip()
    if subject:
        return f"# {subject}\n\n{body}\n"
    return f"{body}\n"

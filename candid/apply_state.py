"""Per-application state for the apply pipeline.

Ports applybot/state.py to candid conventions. Each job's state is a JSON
file under ``<root>/state/<job_id>.json``; per-run logs live under
``candid_data/runs/<job_id>/<utc-timestamp>/``.

States: new -> filling -> needs_input -> ready_for_review -> approved
        -> submitting -> submitted
        blocked / failed are terminal without user action.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from candid import config

STATES = (
    "new",
    "filling",
    "needs_input",
    "ready_for_review",
    "approved",
    "submitting",
    "submitted",
    "blocked",
    "failed",
)

_SAFE_JOB_ID = re.compile(r"[^A-Za-z0-9_-]")


def sanitize_job_id(job_id: str) -> str:
    """Make a job id safe for use as a file or directory name.

    Characters outside [A-Za-z0-9_-] are replaced with "_".
    """
    return _SAFE_JOB_ID.sub("_", str(job_id))


class Store:
    """JSON-file backed store for per-job apply state."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root is not None else config.DATA_DIR / "apply"
        self.state_dir = self.root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        return self.state_dir / f"{sanitize_job_id(job_id)}.json"

    def load(self, job_id: str) -> dict:
        """Return the stored record, or a fresh ``new`` record."""
        p = self._path(job_id)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return {"job_id": job_id, "state": "new", "history": []}

    def save(self, job_id: str, data: dict) -> None:
        """Persist a record, stamping ``updated_at``."""
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._path(job_id).write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )

    def transition(self, job_id: str, to: str, note: str = "") -> dict:
        """Move a job to ``to``, appending a history entry. Returns the record."""
        if to not in STATES:
            raise ValueError(f"unknown state: {to}")
        data = self.load(job_id)
        data["history"].append(
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "from": data.get("state"),
                "to": to,
                "note": note,
            }
        )
        data["state"] = to
        self.save(job_id, data)
        return data

    def run_dir(self, job_id: str) -> Path:
        """Create and return candid_data/runs/<job_id>/<utc-timestamp>/."""
        d = (
            config.DATA_DIR
            / "runs"
            / sanitize_job_id(job_id)
            / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        )
        d.mkdir(parents=True, exist_ok=True)
        return d

"""Wizard session persistence: save/resume named answer sets as JSON.

Stored under ``<CONFIG_DIR>/wizard_sessions/<name>.json``. The config dir
is resolved at call time so ``CANDID_CONFIG_DIR`` is honored even when
changed after import (``candid.config.CONFIG_DIR`` is bound at import time).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


def _sessions_dir() -> Path:
    """Config-dir wizard session store. Reads CANDID_CONFIG_DIR at call time."""
    override = os.environ.get("CANDID_CONFIG_DIR")
    base = Path(override).expanduser() if override else Path.home() / ".config" / "candid"
    return base / "wizard_sessions"


def _sanitize(name: str) -> str:
    """Restrict session names to a safe filename character set."""
    if not isinstance(name, str):
        raise ValueError(f"Session name must be a string, got {type(name).__name__}.")
    safe = re.sub(r"[^a-z0-9_-]", "-", name.strip().lower())
    if not safe:
        raise ValueError(f"Session name {name!r} has no usable characters "
                         f"(allowed: [a-z0-9_-]).")
    return safe


def _path(name: str) -> Path:
    return _sessions_dir() / (_sanitize(name) + ".json")


def save_session(name: str, answers: dict) -> Path:
    """Save a wizard answer dict under ``name``. Returns the file path."""
    if not isinstance(answers, dict):
        raise ValueError("Session answers must be a dict.")
    p = _path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(answers, indent=2), encoding="utf-8")
    return p


def load_session(name: str) -> dict | None:
    """Load a saved session; None if missing, corrupt, or not a JSON object."""
    p = _path(name)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def list_sessions() -> list[str]:
    """Sorted list of saved session names."""
    d = _sessions_dir()
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def clear_session(name: str) -> bool:
    """Delete a saved session. True if one existed, False otherwise."""
    p = _path(name)
    if not p.exists():
        return False
    p.unlink()
    return True

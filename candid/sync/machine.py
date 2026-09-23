"""Stable per-machine identity for sync bundles.

The id is a random hex token stored at CONFIG_DIR / "machine_id".
It is created once and never changes, so peers can recognise each other.
Respects CANDID_CONFIG_DIR via candid.config.
"""

from __future__ import annotations

import secrets

from candid import config


def get_machine_id() -> str:
    """Return this machine's stable id, creating it on first use."""
    path = config.CONFIG_DIR / "machine_id"
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except OSError:
        existing = ""
    if existing:
        return existing
    new_id = "m-" + secrets.token_hex(8)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_id + "\n", encoding="utf-8")
    except OSError:
        # Best effort: still return a usable id for this session.
        pass
    return new_id

"""Shared JSON store helpers for the networking modules (private)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from candid import config as C


def net_dir() -> Path:
    d = C.DATA_DIR / "network"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load(name: str, default: dict) -> dict:
    path = net_dir() / name
    if not path.exists():
        return json.loads(json.dumps(default))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(default))
    if not isinstance(data, dict):
        return json.loads(json.dumps(default))
    return data


def save(name: str, data: dict) -> Path:
    path = net_dir() / name
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return path


def today_iso() -> str:
    return date.today().isoformat()


def parse_date(value: str | None, field: str = "date") -> str:
    """Validate/normalize an ISO date string. Never silently accepts garbage."""
    if not value:
        return today_iso()
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        raise ValueError(
            f"Bad {field} '{value}'. Use YYYY-MM-DD (e.g. 2026-09-22)."
        )

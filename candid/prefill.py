"""Smart default pre-fill for candid interactive prompts.

Resolution order for ``get_default(command, key)``:

1. ``CONFIG_DIR/defaults.json`` -- explicit user-saved defaults, shaped as
   ``{command: {key: value}}``.
2. ``CONFIG_DIR/history.json`` -- ``{"last": {command: {key: value}}}``,
   recording the most-recent explicit value the user gave for that key.
3. ``BUILTIN_FALLBACKS`` in this module -- sensible out-of-the-box values.

Paths honor the ``CANDID_CONFIG_DIR`` environment override at *call* time
(never cached at import time), matching the pattern used by candid.config.
All file reads are defensive: missing or corrupt JSON is treated as empty.
``record_history`` never raises for bad on-disk state -- it rewrites clean.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# --- builtin fallbacks (level 3) ---------------------------------------------
# Kept deliberately minimal: only keys where a stable, non-surprising
# fallback exists. Everything else resolves to None and the prompt shows
# no default suffix. (e.g. match/min_score is intentionally NOT here --
# a numeric threshold should always come from the user or saved config.)
BUILTIN_FALLBACKS: dict[str, dict[str, str]] = {
    "tailor": {
        "tone": "confident",
        "length": "one-page",
    },
    "jobs": {
        "location": "",
    },
}

DEFAULTS_FILENAME = "defaults.json"
HISTORY_FILENAME = "history.json"


def _config_dir() -> Path:
    """Config dir, honoring CANDID_CONFIG_DIR at call time."""
    override = os.environ.get("CANDID_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "candid"


def _defaults_path() -> Path:
    return _config_dir() / DEFAULTS_FILENAME


def _history_path() -> Path:
    return _config_dir() / HISTORY_FILENAME


def _read_json(path: Path) -> dict:
    """Read a JSON object defensively: missing/corrupt/non-dict -> {}."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _lookup(mapping: dict, command: str, key: str) -> str | None:
    """Fetch mapping[command][key] if both levels are dicts holding a str."""
    section = mapping.get(command)
    if not isinstance(section, dict):
        return None
    value = section.get(key)
    return value if isinstance(value, str) else None


def get_default(command: str, key: str) -> str | None:
    """Resolve the smart default for ``command``/``key``.

    Order: defaults.json -> history.json ("last") -> BUILTIN_FALLBACKS.
    Returns None when nothing is recorded and no builtin exists.
    """
    found = _lookup(_read_json(_defaults_path()), command, key)
    if found is not None:
        return found
    found = _lookup(_read_json(_history_path()).get("last", {}), command, key)
    if found is not None:
        return found
    return _lookup(BUILTIN_FALLBACKS, command, key)


def record_history(command: str, key: str, value: str) -> None:
    """Upsert ``value`` into history.json's "last" section.

    Never crashes on corrupt JSON: a corrupt file is rewritten clean.
    Other commands/keys in the file are preserved.
    """
    try:
        data = _read_json(_history_path())
        last = data.get("last")
        if not isinstance(last, dict):
            last = {}
            data["last"] = last
        section = last.get(command)
        if not isinstance(section, dict):
            section = {}
            last[command] = section
        section[key] = value
        path = _history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def format_default(value: str | None) -> str:
    """Render the prompt suffix for a default.

    None or "" -> "" (no suffix). Otherwise " [default: X]".
    """
    if value is None or value == "":
        return ""
    return f" [default: {value}]"

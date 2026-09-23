"""Per-category auto-resolve rules for sync conflicts.

Each sync category can have its own conflict-resolution strategy, stored in
``DATA_DIR/sync/rules.json`` as ``{category: strategy}``. Any category without
an explicit rule falls back to ``"auto"``.

Strategies:

- ``"auto"``        default three-way resolution against the base snapshot
- ``"local-wins"``  keep the local copy, never raise
- ``"remote-wins"`` take the incoming copy, never raise
- ``"newer-wins"``  keep whichever side has the newer mtime
- ``"manual"``      always raise the conflict for the user to decide

``apply_strategy`` is a pure function: it takes content and mtimes and
returns ``"local"``, ``"remote"``, or ``"conflict"``. It is JSON-agnostic,
working on bytes or str, so other workers can reuse it for any payload.
"""

from __future__ import annotations

import json
from pathlib import Path

from candid import config
from candid.sync import categories
from candid.sync.errors import SyncError

#: all valid strategies
STRATEGIES = ("auto", "local-wins", "remote-wins", "newer-wins", "manual")

DEFAULT_STRATEGY = "auto"

_RULES_FILENAME = "rules.json"


def _rules_path() -> Path:
    d = Path(config.DATA_DIR) / categories.SYNC_STATE_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d / _RULES_FILENAME


def _load_stored() -> dict:
    path = _rules_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise SyncError(f"rules file {path} is corrupt: {exc}") from exc
    if not isinstance(data, dict):
        raise SyncError(f"rules file {path} is corrupt")
    return data


def _save_stored(stored: dict) -> None:
    _rules_path().write_text(
        json.dumps(stored, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _validate_category(category: str) -> str:
    # raises SyncError on unknown category
    categories.resolve(category)
    return category


def _validate_strategy(strategy: str) -> str:
    if strategy not in STRATEGIES:
        raise SyncError(
            f"unknown strategy {strategy!r}; "
            f"choose from: {', '.join(STRATEGIES)}"
        )
    return strategy


def get_rules() -> dict:
    """Return every category's effective strategy, merged over defaults.

    Categories without an explicit rule report ``"auto"``. The returned dict
    always covers ``categories.all_categories()``.
    """
    stored = _load_stored()
    return {
        cat: stored.get(cat, DEFAULT_STRATEGY)
        for cat in categories.all_categories()
    }


def strategy_for(category: str) -> str:
    """Return the effective strategy for one category (SyncError if unknown)."""
    _validate_category(category)
    return _load_stored().get(category, DEFAULT_STRATEGY)


def set_rule(category: str, strategy: str) -> dict:
    """Set a category's strategy (both validated; SyncError on unknown).

    Returns the merged rules dict (as ``get_rules``).
    """
    _validate_category(category)
    _validate_strategy(strategy)
    stored = _load_stored()
    stored[category] = strategy
    _save_stored(stored)
    return get_rules()


def clear_rule(category: str) -> dict:
    """Remove a category's explicit rule, restoring the ``"auto"`` default.

    Returns the merged rules dict. Clearing a category with no explicit rule
    is a no-op.
    """
    _validate_category(category)
    stored = _load_stored()
    stored.pop(category, None)
    _save_stored(stored)
    return get_rules()


def apply_strategy(
    content_local,
    content_remote,
    base_content,
    strategy: str,
    local_mtime: float | None,
    remote_mtime: float | None,
) -> str:
    """Resolve one file's conflict according to ``strategy``.

    Arguments are the local content, the incoming (remote) content, and the
    content at the last sync base (any may be ``None`` when the file is
    absent on that side). Contents are compared opaquely, so bytes, str, or
    None all work. Mtimes are POSIX timestamps; ``None`` means unknown.

    Returns ``"local"``, ``"remote"``, or ``"conflict"``:

    - ``"auto"``: three-way. No changes or identical changes keep the winner
      trivially; a change on one side only takes that side; changes on both
      sides that differ raise a conflict.
    - ``"local-wins"`` / ``"remote-wins"``: that side, unconditionally.
    - ``"newer-wins"``: the side with the newer mtime wins. Tie-break
      (documented here): an exact tie keeps ``"local"``. Rationale: when
      timestamps give no signal, silently overwriting the local copy is the
      riskier outcome, so we fail safe toward the user's own data.
    - ``"manual"``: always ``"conflict"``.

    Raises SyncError on an unknown strategy.
    """
    _validate_strategy(strategy)
    if strategy == "local-wins":
        return "local"
    if strategy == "remote-wins":
        return "remote"
    if strategy == "manual":
        return "conflict"
    if strategy == "newer-wins":
        local_ts = local_mtime if local_mtime is not None else float("-inf")
        remote_ts = remote_mtime if remote_mtime is not None else float("-inf")
        if remote_ts > local_ts:
            return "remote"
        # exact tie (or local newer) falls back to local, see docstring
        return "local"
    # "auto": three-way resolution against the base
    if content_local == content_remote:
        return "local"
    if content_local == base_content:
        return "remote"  # only the remote side changed
    if content_remote == base_content:
        return "local"  # only the local side changed
    return "conflict"  # both changed differently

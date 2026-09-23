"""Config migration registry for candid's versioned config.yaml.

Each migration is a ``(from_version, to_version, function)`` triple.
``candid migrate`` walks the chain from the config's current version up to
``config.CONFIG_VERSION``, applying each step in order. To add a new schema
version:

1. Bump ``CONFIG_VERSION`` in ``candid/config.py``.
2. Add a ``(old, new, fn)`` entry below; ``fn(cfg) -> (new_cfg, notes)``.
3. Document what it normalizes here.
"""

from __future__ import annotations

from collections import namedtuple
from typing import Callable

from candid import config as C

Migration = namedtuple("Migration", ["from_version", "to_version", "apply"])

MigrationFn = Callable[[dict], tuple[dict, list[str]]]


def _migrate_v0_to_v1(cfg: dict) -> tuple[dict, list[str]]:
    """Stamp config_version and backfill v1 defaults.

    Version 0 means "written before config_version existed" — there was no
    earlier versioned schema, so there are no legacy keys to rename or drop.
    The migration therefore:

    * stamps ``config_version: 1`` (save_config does this on write anyway;
      stamping here keeps the in-memory dict honest too),
    * backfills any missing v1 keys from ``config.DEFAULT_CONFIG``
      (``log_level``, ``dashboard_port``),
    * preserves every unknown key untouched — nothing is dropped or renamed.

    If you hand-wrote a config.yaml before this framework landed, this is the
    migration that adopts it.
    """
    out = dict(cfg)
    notes: list[str] = []
    out["config_version"] = 1
    for key, default in C.DEFAULT_CONFIG.items():
        if key not in out:
            out[key] = default
            notes.append(f"backfilled {key}={default!r}")
    return out, notes


#: Ordered migration chain. Each step moves exactly one version forward.
MIGRATIONS: list[Migration] = [
    Migration(0, 1, _migrate_v0_to_v1),
]


def migrations_from(version: int) -> list[Migration]:
    """Migrations needed to go from ``version`` to ``C.CONFIG_VERSION``, in order.

    Raises config.ConfigError when no migration chain covers the gap (e.g. a
    config written by a *newer* candid than this one).
    """
    if version > C.CONFIG_VERSION:
        raise C.ConfigError(
            f"Config version {version} is newer than this candid supports "
            f"(max {C.CONFIG_VERSION}). Upgrade candid, or restore a backup "
            f"from config.yaml.bak.*."
        )
    steps: list[Migration] = []
    current = version
    while current < C.CONFIG_VERSION:
        nxt = next((m for m in MIGRATIONS if m.from_version == current), None)
        if nxt is None:
            raise C.ConfigError(
                f"No migration from config version {current} to "
                f"{C.CONFIG_VERSION}; cannot upgrade safely."
            )
        steps.append(nxt)
        current = nxt.to_version
    return steps

"""`candid migrate` engine: upgrade config.yaml through the migration chain.

Safety rules:

* A timestamped backup (``config.yaml.bak.<YYYYMMDDHHMMSS>``) is written
  BEFORE anything changes. No backup = no write.
* Idempotent: when the config is already at ``CONFIG_VERSION``, this is a
  no-op (no backup, no rewrite).
* Downgrades are refused — a config newer than this candid errors out
  instead of being rewritten.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from candid import config as C
from candid import migrations as M


def _timestamp(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y%m%d%H%M%S")


def backup_path(config_path: Path, now: datetime | None = None) -> Path:
    """Sibling path for the pre-migration backup."""
    return config_path.with_name(f"{config_path.name}.bak.{_timestamp(now)}")


def migrate_config(config_path: Path | None = None,
                   now: datetime | None = None) -> dict:
    """Upgrade the config at ``config_path`` (default: CONFIG_DIR/config.yaml).

    Returns a report dict::

        {
            "config_path": str, "backup_path": str | None,
            "created": bool,    # True when no config existed and one was written
            "noop": bool,       # True when already current (nothing changed)
            "from_version": int, "to_version": int,
            "applied": [(from_v, to_v, fn_name)],  # migrations run
            "steps": [str],    # human-readable log lines, in order
        }

    Raises config.ConfigError when the config is newer than this candid or
    no migration chain covers the version gap.
    """
    path = Path(config_path) if config_path else Path(C.CONFIG_PATH)
    steps: list[str] = []

    if not path.exists():
        fresh = C.save_config(dict(C.DEFAULT_CONFIG), path)
        msg = f"no config found — wrote a fresh v{C.CONFIG_VERSION} config at {fresh}"
        return {
            "config_path": str(path), "backup_path": None, "created": True,
            "noop": False, "from_version": 0, "to_version": C.CONFIG_VERSION,
            "applied": [], "steps": [msg],
        }

    cfg = C.load_config(path)
    version = C.config_version_of(cfg)

    pending = M.migrations_from(version)  # raises on newer-than-known configs
    if not pending:
        return {
            "config_path": str(path), "backup_path": None, "created": False,
            "noop": True, "from_version": version, "to_version": version,
            "applied": [],
            "steps": [f"config is already at v{version} — nothing to do"],
        }

    # Backup BEFORE touching anything.
    bak = backup_path(path, now)
    shutil.copy2(path, bak)
    steps.append(f"backup written to {bak}")

    applied: list[tuple[int, int, str]] = []
    for mig in pending:
        new_cfg, notes = mig.apply(cfg)
        cfg = new_cfg
        applied.append((mig.from_version, mig.to_version, mig.apply.__name__))
        steps.append(f"v{mig.from_version} -> v{mig.to_version}: {mig.apply.__name__}")
        steps.extend(f"  - {n}" for n in notes)

    C.save_config(cfg, path)
    steps.append(f"wrote upgraded config v{C.CONFIG_VERSION} to {path}")

    return {
        "config_path": str(path), "backup_path": str(bak), "created": False,
        "noop": False, "from_version": version, "to_version": C.CONFIG_VERSION,
        "applied": applied, "steps": steps,
    }

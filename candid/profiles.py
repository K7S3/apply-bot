"""Multiple user profiles for the candid package.

A *profile* is a named slice of user data (tracker, offers, tailored
resumes, prep packs, ...). The ``default`` profile is special: its data
dir is the legacy ``config.DATA_DIR`` itself, so all pre-existing
single-profile data keeps working untouched. Non-default profiles live
under ``config.DATA_DIR / "profiles" / <name>``.

Profile metadata (names, target roles, current profile) lives in a
registry at ``config.CONFIG_DIR / "profiles.json"``::

    {"current": "default",
     "profiles": {"default": {"target_role": None, "created": "<iso>"}}}

Resolution order for a profile name:
    explicit argument > ``--profile`` flag (request scoping) >
    ``CANDID_PROFILE`` env var > registry ``current`` > ``default``.

``candid.config`` must NOT import this module at top level; it imports
it lazily inside its profile-aware helpers (this module imports
``candid.config`` at top level, and a top-level reverse import would be
circular).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from candid import config

DEFAULT_PROFILE = "default"


class ContextError(Exception):
    """Raised for invalid profile names, unknown profiles, collisions,
    and operations that are refused (e.g. deleting the default profile)."""


# ---------------------------------------------------------------------------
# names
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def validate_name(name: object) -> str:
    """Return ``name`` if it is a legal profile name, else raise ContextError."""
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ContextError(
            f"Invalid profile name {name!r}: use 1-64 chars, "
            "letters/digits, '_' or '-', and start with a letter or digit."
        )
    return name


def profile_dir(name: str) -> Path:
    """Data directory for a profile.

    The ``default`` profile maps to ``config.DATA_DIR`` itself (legacy
    files are the default profile). Other profiles live under
    ``config.DATA_DIR / "profiles" / <name>``.
    """
    validate_name(name)
    if name == DEFAULT_PROFILE:
        return config.DATA_DIR
    return config.DATA_DIR / "profiles" / name


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


def registry_path() -> Path:
    return config.CONFIG_DIR / "profiles.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _blank_registry() -> dict:
    return {
        "current": DEFAULT_PROFILE,
        "profiles": {DEFAULT_PROFILE: {"target_role": None, "created": _now_iso()}},
    }


def _load_registry() -> dict:
    """Load the registry; tolerate missing or corrupt files."""
    path = registry_path()
    try:
        reg = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _blank_registry()
    if not isinstance(reg, dict):
        return _blank_registry()
    profiles_ = reg.get("profiles")
    if not isinstance(profiles_, dict):
        return _blank_registry()
    current = reg.get("current")
    if not isinstance(current, str) or current not in profiles_:
        current = DEFAULT_PROFILE
    profiles_.setdefault(
        DEFAULT_PROFILE, {"target_role": None, "created": _now_iso()}
    )
    return {"current": current, "profiles": profiles_}


def _save_registry(reg: dict) -> None:
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(reg, indent=2))
    tmp.replace(path)


def _require_exists(reg: dict, name: str) -> None:
    if name not in reg["profiles"]:
        raise ContextError(f"Unknown profile {name!r}.")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def list_profiles() -> list[str]:
    """Sorted list of profile names."""
    return sorted(_load_registry()["profiles"].keys())


def profile_info(name: str) -> dict:
    """Return details for a profile.

    Keys: ``name``, ``target_role``, ``created``, plus ``is_current``,
    ``has_profile`` (an onboarding profile.json exists), ``tracker_count``
    (number of tracked applications), and ``data_dir``.
    """
    validate_name(name)
    reg = _load_registry()
    _require_exists(reg, name)
    entry = reg["profiles"][name] or {}
    data_dir = profile_dir(name)
    tracker_file = data_dir / "tracker.json"
    count = 0
    if tracker_file.exists():
        try:
            records = json.loads(tracker_file.read_text())
            count = len(records) if isinstance(records, list) else 0
        except (json.JSONDecodeError, OSError):
            count = 0
    return {
        "name": name,
        "target_role": entry.get("target_role"),
        "created": entry.get("created"),
        "is_current": get_current() == name,
        "has_profile": (data_dir / "profile.json").exists(),
        "tracker_count": count,
        "data_dir": str(data_dir),
    }


def _copy_dir_contents(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        if child.is_dir():
            shutil.copytree(child, dst / child.name, dirs_exist_ok=True)
        else:
            shutil.copy2(child, dst / child.name)


def create_profile(
    name: str,
    target_role: str | None = None,
    clone_from: str | None = None,
) -> dict:
    """Create a profile and its data dir; return its info dict.

    ``clone_from`` copies the source profile's data dir contents into
    the new one (and inherits the source's target role when
    ``target_role`` is not given).
    """
    validate_name(name)
    reg = _load_registry()
    if name in reg["profiles"]:
        raise ContextError(f"Profile {name!r} already exists.")

    info: dict = {"target_role": target_role, "created": _now_iso()}
    if clone_from is not None:
        validate_name(clone_from)
        _require_exists(reg, clone_from)
        if target_role is None:
            src_entry = reg["profiles"][clone_from] or {}
            info["target_role"] = src_entry.get("target_role")
        _copy_dir_contents(profile_dir(clone_from), profile_dir(name))
    else:
        profile_dir(name).mkdir(parents=True, exist_ok=True)

    reg["profiles"][name] = info
    _save_registry(reg)
    return {"name": name, **info}


def clone_profile(src: str, dst: str) -> dict:
    """Clone profile ``src`` into a new profile ``dst``."""
    return create_profile(dst, clone_from=src)


def rename_profile(old: str, new: str) -> dict:
    """Rename a profile (moves its data dir for non-default profiles).

    The ``default`` profile cannot be renamed: it is pinned to the
    legacy data dir, so renaming it would orphan that data.
    """
    validate_name(old)
    validate_name(new)
    if old == DEFAULT_PROFILE:
        raise ContextError("The default profile cannot be renamed.")
    reg = _load_registry()
    _require_exists(reg, old)
    if new in reg["profiles"]:
        raise ContextError(f"Profile {new!r} already exists.")
    if old != DEFAULT_PROFILE:
        shutil.move(str(profile_dir(old)), str(profile_dir(new)))
    reg["profiles"][new] = reg["profiles"].pop(old)
    if reg.get("current") == old:
        reg["current"] = new
    _save_registry(reg)
    return profile_info(new)


def _has_tracker_entries(name: str) -> bool:
    """True when the profile's tracker file holds any entries."""
    tracker = profile_dir(name) / "tracker.json"
    try:
        data = json.loads(tracker.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    return bool(data)


def delete_profile(name: str, force: bool = False) -> None:
    """Delete a profile, its registry entry, and its data dir.

    The ``default`` profile can never be deleted. Without ``force``, a
    profile that has tracker entries is refused (to avoid losing
    application history by accident).
    """
    validate_name(name)
    if name == DEFAULT_PROFILE:
        raise ContextError("The default profile cannot be deleted.")
    reg = _load_registry()
    _require_exists(reg, name)
    if not force and _has_tracker_entries(name):
        raise ContextError(
            f"Profile {name!r} has tracker entries; pass force=True to delete it."
        )
    shutil.rmtree(profile_dir(name), ignore_errors=True)
    del reg["profiles"][name]
    if reg.get("current") == name:
        reg["current"] = DEFAULT_PROFILE
    _save_registry(reg)


# ---------------------------------------------------------------------------
# current profile
# ---------------------------------------------------------------------------


def get_current() -> str:
    """Name of the current profile (``default`` when unset)."""
    return _load_registry().get("current") or DEFAULT_PROFILE


def set_current(name: str) -> None:
    """Make ``name`` the current profile."""
    validate_name(name)
    reg = _load_registry()
    _require_exists(reg, name)
    reg["current"] = name
    _save_registry(reg)


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------


def resolve(name: str | None = None) -> str:
    """Resolve a profile name to a validated, existing profile.

    Order: explicit ``name`` > ``CANDID_PROFILE`` env var > registry
    ``current`` > ``default``. Raises ContextError for invalid or
    unknown names.
    """
    candidate = name if name is not None else os.environ.get("CANDID_PROFILE")
    if not candidate:
        candidate = get_current()
    validate_name(candidate)
    _require_exists(_load_registry(), candidate)
    return candidate


# ---------------------------------------------------------------------------
# request scoping (for the CLI ``--profile`` flag)
# ---------------------------------------------------------------------------

_REQUEST_PROFILE: str | None = None


def set_request_profile(name: str | None) -> None:
    """Scope this process/request to one profile (e.g. from ``--profile``).

    ``None`` clears the scoping. The name must already exist.
    """
    global _REQUEST_PROFILE
    if name is None:
        _REQUEST_PROFILE = None
        return
    validate_name(name)
    _require_exists(_load_registry(), name)
    _REQUEST_PROFILE = name


def clear_request_profile() -> None:
    """Clear request scoping."""
    global _REQUEST_PROFILE
    _REQUEST_PROFILE = None


def active_profile() -> str:
    """Profile currently in effect: request scope or normal resolution."""
    return resolve(_REQUEST_PROFILE)


# ---------------------------------------------------------------------------
# sharing: export / import
# ---------------------------------------------------------------------------

_META_NAME = "meta.json"


def _iter_profile_files(name: str):
    """Yield (source path, archive name) for a profile's data dir.

    The default profile's dir also holds the ``profiles/`` subtree;
    those belong to other profiles and are excluded.
    """
    base = profile_dir(name)
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(base)
        if name == DEFAULT_PROFILE and rel.parts[0] == "profiles":
            continue
        yield path, rel.as_posix()


def export_profile(name: str, dest_zip_path: str | Path) -> Path:
    """Zip a profile's data dir plus a meta.json into ``dest_zip_path``.

    meta.json holds the profile ``name``, ``target_role``, and the
    candid version.
    """
    from candid import __version__

    validate_name(name)
    reg = _load_registry()
    _require_exists(reg, name)
    dest = Path(dest_zip_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "name": name,
        "target_role": profile_info(name)["target_role"],
        "candid_version": __version__,
    }
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(_META_NAME, json.dumps(meta, indent=2))
        for src, arcname in _iter_profile_files(name):
            zf.write(src, arcname)
    return dest


def _safe_extract(zf: zipfile.ZipFile, dest: Path, members: list) -> None:
    """Extract the given zip members, refusing absolute paths and ``..`` escapes."""
    for member in members:
        arcname = Path(member.filename)
        if member.is_dir():
            continue
        if arcname.is_absolute() or ".." in arcname.parts:
            raise ContextError(f"Refusing unsafe zip entry {member.filename!r}.")
    dest.mkdir(parents=True, exist_ok=True)
    for member in members:
        if member.is_dir():
            continue
        target = dest / member.filename
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)


def import_profile(src_zip: str | Path, name: str | None = None) -> dict:
    """Restore a profile exported by :func:`export_profile`.

    ``name`` defaults to the meta.json name. A name collision raises
    ContextError (pass an explicit free ``name`` instead).
    """
    src = Path(src_zip)
    if not src.is_file():
        raise ContextError(f"Archive not found: {src_zip!r}.")
    with zipfile.ZipFile(src, "r") as zf:
        try:
            meta = json.loads(zf.read(_META_NAME).decode("utf-8"))
        except KeyError:
            raise ContextError("Archive has no meta.json; not a candid profile export.")
        dest_name = name if name is not None else meta.get("name")
    validate_name(dest_name)
    reg = _load_registry()
    if dest_name in reg["profiles"]:
        raise ContextError(
            f"Profile {dest_name!r} already exists; pass a free name to import under."
        )
    with zipfile.ZipFile(src, "r") as zf:
        members = [m for m in zf.infolist() if m.filename != _META_NAME]
        _safe_extract(zf, profile_dir(dest_name), members)
    info = {
        "target_role": meta.get("target_role"),
        "created": _now_iso(),
    }
    reg["profiles"][dest_name] = info
    _save_registry(reg)
    return {"name": dest_name, **info}

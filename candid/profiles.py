"""Target-role config profiles.

A profile is a named set of job-search defaults stored as JSON under
``CONFIG_DIR/profiles/<name>.json``::

    {
      "name": "ml-nyc",
      "target_role": "Machine Learning Engineer",
      "seniority": "senior",
      "domains": ["ads ranking", "recommendations"],
      "locations": ["New York, NY", "Remote"],
      "min_salary": 180000,
      "notes": "Prefer product-facing teams."
    }

``profiles use <name>`` marks one profile active (pointer file at
``CONFIG_DIR/active_profile``). Other candid modules can read the active
profile's defaults with :func:`get_active_profile`.

Everything resolves ``CANDID_CONFIG_DIR`` at call time, so tests can point
candid at a temp dir via the env var even after ``candid.config`` was
imported.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from candid import config as C

__all__ = [
    "ProfilesError",
    "PROFILES_SCHEMA",
    "profiles_dir",
    "active_profile_path",
    "list_profiles",
    "create_profile",
    "show_profile",
    "use_profile",
    "delete_profile",
    "update_profile",
    "get_active_profile",
    "get_active_profile_name",
    "register",
]


class ProfilesError(Exception):
    """Raised when a profile is missing, invalid, or cannot be saved."""


NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

SENIORITY_CHOICES = [
    "entry", "junior", "mid", "senior", "lead", "staff",
    "principal", "director", "director+", "vp", "vp+",
]

#: Field -> (required?, expected type description). Used by validation errors.
PROFILES_SCHEMA = {
    "target_role": (True, "string"),
    "seniority": (False, "string, one of: " + ", ".join(SENIORITY_CHOICES)),
    "domains": (False, "list of strings"),
    "locations": (False, "list of strings"),
    "min_salary": (False, "number >= 0, or null"),
    "notes": (False, "string"),
}


def _config_dir() -> Path:
    """Config dir, honoring CANDID_CONFIG_DIR even if set after import."""
    override = os.environ.get("CANDID_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    return C.CONFIG_DIR


def profiles_dir() -> Path:
    return _config_dir() / "profiles"


def active_profile_path() -> Path:
    return _config_dir() / "active_profile"


def _profile_path(name: str) -> Path:
    return profiles_dir() / f"{name}.json"


def _check_name(name: str) -> str:
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise ProfilesError(
            f"Invalid profile name {name!r}. "
            "Fix: use only letters, numbers, hyphens, and underscores, "
            "e.g. `ml-nyc` or `ds_remote`."
        )
    return name


def _parse_csv(value: str | None) -> list[str]:
    """Split a comma-separated CLI flag into a clean list of strings."""
    if value is None:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _validate(data: dict, name: str) -> dict:
    """Strictly validate a profile dict; return a normalized copy.

    Raises ProfilesError naming the exact fix on any problem.
    """
    if not isinstance(data, dict):
        raise ProfilesError(
            f"Profile {name!r} must be a JSON object. "
            f"Fix: rewrite {_profile_path(name)} as an object with "
            "a 'target_role' field."
        )
    unknown = sorted(set(data) - set(PROFILES_SCHEMA) - {"name"})
    if unknown:
        raise ProfilesError(
            f"Profile {name!r} has unknown field(s): {', '.join(unknown)}. "
            f"Allowed fields: {', '.join(sorted(PROFILES_SCHEMA))}. "
            f"Fix: remove the unknown field(s) from {_profile_path(name)}."
        )
    out: dict = {"name": name}
    for field, (required, expected) in PROFILES_SCHEMA.items():
        value = data.get(field)
        if value is None:
            if required:
                raise ProfilesError(
                    f"Profile {name!r} is missing required field 'target_role'. "
                    f"Fix: add \"target_role\": \"<role>\" to {_profile_path(name)}."
                )
            out[field] = [] if expected.startswith("list") else ("" if expected == "string" else None)
            if field == "min_salary":
                out[field] = None
            continue
        if field == "target_role":
            if not isinstance(value, str) or not value.strip():
                raise ProfilesError(
                    f"Profile {name!r}: 'target_role' must be a non-empty string. "
                    f"Fix: set \"target_role\": \"<role>\" in {_profile_path(name)}."
                )
            out[field] = value.strip()
        elif field == "seniority":
            if not isinstance(value, str) or value.strip().lower() not in SENIORITY_CHOICES:
                raise ProfilesError(
                    f"Profile {name!r}: 'seniority' must be one of: "
                    f"{', '.join(SENIORITY_CHOICES)}. "
                    f"Fix: set \"seniority\" to one of those values in {_profile_path(name)}."
                )
            out[field] = value.strip().lower()
        elif field in ("domains", "locations"):
            if (not isinstance(value, list)
                    or any(not isinstance(v, str) or not v.strip() for v in value)):
                raise ProfilesError(
                    f"Profile {name!r}: '{field}' must be a list of strings. "
                    f"Fix: set \"{field}\": [\"a\", \"b\"] in {_profile_path(name)}."
                )
            out[field] = [v.strip() for v in value]
        elif field == "min_salary":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ProfilesError(
                    f"Profile {name!r}: 'min_salary' must be a number >= 0 (or null). "
                    f"Fix: set \"min_salary\": 150000 in {_profile_path(name)}."
                )
            out[field] = value
        elif field == "notes":
            if not isinstance(value, str):
                raise ProfilesError(
                    f"Profile {name!r}: 'notes' must be a string. "
                    f"Fix: set \"notes\": \"...\" in {_profile_path(name)}."
                )
            out[field] = value
    return out


def _read(name: str) -> dict:
    name = _check_name(name)
    path = _profile_path(name)
    if not path.exists():
        raise ProfilesError(
            f"No profile named {name!r}. "
            f"Fix: create it with `python -m candid profiles create {name} --role \"<role>\"`, "
            f"or pick from `python -m candid profiles list`."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProfilesError(
            f"Profile {name!r} is not valid JSON ({exc}). "
            f"Fix: repair {_profile_path(name)} or delete and re-create it."
        ) from exc
    return _validate(data, name)


def _write(name: str, data: dict) -> None:
    profiles_dir().mkdir(parents=True, exist_ok=True)
    # "name" is the filename; keep it out of the stored JSON so the
    # strict validator accepts the file on re-read.
    stored = {k: v for k, v in data.items() if k != "name"}
    tmp = _profile_path(name).with_suffix(".tmp")
    tmp.write_text(json.dumps(stored, indent=2) + "\n", encoding="utf-8")
    tmp.replace(_profile_path(name))


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def list_profiles() -> list[str]:
    """Return sorted profile names."""
    d = profiles_dir()
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def create_profile(name: str, *, role: str = "", seniority: str = "",
                   domains: str | None = None, locations: str | None = None,
                   min_salary: float | None = None,
                   notes: str = "") -> dict:
    """Create a profile; error if it already exists."""
    name = _check_name(name)
    if _profile_path(name).exists():
        raise ProfilesError(
            f"Profile {name!r} already exists. "
            f"Fix: edit it with `python -m candid profiles update {name} ...` "
            f"or delete it first with `python -m candid profiles delete {name}`."
        )
    data = _validate({
        "target_role": role,
        "seniority": seniority or None,
        "domains": _parse_csv(domains),
        "locations": _parse_csv(locations),
        "min_salary": min_salary,
        "notes": notes or "",
    }, name)
    _write(name, data)
    return data


def show_profile(name: str | None = None) -> dict:
    """Show one profile (default: the active one)."""
    return _read(get_active_profile_name() if name is None else name)


def use_profile(name: str) -> str:
    """Mark a profile active. Returns the name."""
    _read(name)  # validates existence + schema first
    name = _check_name(name)
    _config_dir().mkdir(parents=True, exist_ok=True)
    active_profile_path().write_text(name + "\n", encoding="utf-8")
    return name


def delete_profile(name: str) -> None:
    """Delete a profile; clears the active pointer if it pointed here."""
    _read(name)  # validates existence first
    name = _check_name(name)
    _profile_path(name).unlink()
    if get_active_profile_name() == name:
        active_profile_path().unlink(missing_ok=True)


def update_profile(name: str, *, role: str | None = None,
                   seniority: str | None = None,
                   domains: str | None = None, locations: str | None = None,
                   min_salary: float | None = None,
                   notes: str | None = None) -> dict:
    """Partially update a profile; only flags that were passed change."""
    current = _read(name)
    name = _check_name(name)
    patch: dict = {}
    if role is not None:
        patch["target_role"] = role
    if seniority is not None:
        patch["seniority"] = seniority or None
    if domains is not None:
        patch["domains"] = _parse_csv(domains)
    if locations is not None:
        patch["locations"] = _parse_csv(locations)
    if min_salary is not None:
        patch["min_salary"] = min_salary
    if notes is not None:
        patch["notes"] = notes
    data = _validate({**current, **patch}, name)
    _write(name, data)
    return data


def get_active_profile_name() -> str | None:
    """Return the active profile name, or None if none is set."""
    path = active_profile_path()
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip() or None


def get_active_profile() -> dict:
    """Return the active profile dict.

    Raises ProfilesError with the exact fix when nothing is active, the
    pointer is stale, or the JSON is invalid. Other candid modules call
    this to pick up target-role defaults.
    """
    name = get_active_profile_name()
    if not name:
        raise ProfilesError(
            "No active profile set. "
            "Fix: run `python -m candid profiles use <name>` "
            "(see names with `python -m candid profiles list`)."
        )
    path = _profile_path(name)
    if not path.exists():
        raise ProfilesError(
            f"Active profile {name!r} no longer exists "
            f"(expected {_profile_path(name)}). "
            "Fix: run `python -m candid profiles list` and "
            "`python -m candid profiles use <name>` again."
        )
    return _read(name)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _fail(msg: str) -> int:
    import sys
    sys.stderr.write(f"Error: {msg}\n")
    return 1


def cmd_profiles(a: argparse.Namespace) -> int:
    """Dispatch `profiles <subcommand>`; clean errors, no tracebacks."""
    try:
        if a.what == "list":
            names = list_profiles()
            active = get_active_profile_name()
            if not names:
                print("No profiles yet. Create one with:\n"
                      "  python -m candid profiles create <name> --role \"<target role>\"")
            else:
                for n in names:
                    mark = " *" if n == active else ""
                    print(f"{n}{mark}")
                if active:
                    print("\n* = active")
            return 0
        if a.what == "create":
            data = create_profile(
                a.name, role=a.role or "", seniority=a.seniority or "",
                domains=a.domains, locations=a.locations,
                min_salary=a.min_salary, notes=a.notes or "")
            print(f"Created profile {data['name']!r} "
                  f"(target_role={data['target_role']!r}).")
            print(f"Activate it with: python -m candid profiles use {data['name']}")
            return 0
        if a.what == "use":
            name = use_profile(a.name)
            print(f"Active profile: {name}")
            return 0
        if a.what == "show":
            print(json.dumps(show_profile(a.name), indent=2))
            return 0
        if a.what == "delete":
            delete_profile(a.name)
            print(f"Deleted profile {a.name!r}.")
            return 0
        if a.what == "update":
            data = update_profile(
                a.name, role=a.role, seniority=a.seniority,
                domains=a.domains, locations=a.locations,
                min_salary=a.min_salary, notes=a.notes)
            print(f"Updated profile {data['name']!r}.")
            return 0
    except ProfilesError as exc:
        return _fail(str(exc))
    return _fail(f"Unknown profiles subcommand {getattr(a, 'what', None)!r}. "
                 "Run `python -m candid profiles --help`.")


def _add_profile_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--role", default=None,
                   help="Target role, e.g. 'Machine Learning Engineer'")
    p.add_argument("--seniority", default=None,
                   choices=SENIORITY_CHOICES,
                   help="Seniority level")
    p.add_argument("--domains", default=None,
                   help="Comma-separated domains, e.g. 'ads ranking,recommendations'")
    p.add_argument("--locations", default=None,
                   help="Comma-separated locations, e.g. 'New York, NY,Remote'")
    p.add_argument("--min-salary", type=float, default=None,
                   help="Minimum acceptable annual salary, e.g. 180000")
    p.add_argument("--notes", default=None, help="Free-text notes")


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the top-level `profiles` command and its subcommands."""
    p = subparsers.add_parser(
        "profiles",
        help="Manage target-role config profiles",
        description="Named sets of job-search defaults (role, seniority, "
                    "domains, locations, salary floor). Activate one with "
                    "`profiles use` and other commands pick up its defaults.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n"
               "  python -m candid profiles create mle --role \"ML Engineer\" --seniority senior\n"
               "  python -m candid profiles use mle\n"
               "  python -m candid profiles list",
    )
    sub = p.add_subparsers(dest="what", metavar="<subcommand>")
    sub.required = True

    s = sub.add_parser("list", help="List profiles (* = active)",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="examples:\n  python -m candid profiles list")
    s.set_defaults(func=cmd_profiles)

    s = sub.add_parser("create", help="Create a profile",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="examples:\n"
                              "  python -m candid profiles create mle "
                              "--role \"ML Engineer\" --seniority senior --domains ml,ranking")
    s.add_argument("name", help="Profile name: letters, numbers, hyphens, underscores")
    _add_profile_flags(s)
    s.set_defaults(func=cmd_profiles)

    s = sub.add_parser("use", help="Set the active profile",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="examples:\n  python -m candid profiles use mle")
    s.add_argument("name", help="Profile name")
    s.set_defaults(func=cmd_profiles)

    s = sub.add_parser("show", help="Show a profile as JSON (default: active)",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="examples:\n"
                              "  python -m candid profiles show\n"
                              "  python -m candid profiles show mle")
    s.add_argument("name", nargs="?", default=None, help="Profile name")
    s.set_defaults(func=cmd_profiles)

    s = sub.add_parser("delete", help="Delete a profile",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="examples:\n  python -m candid profiles delete mle")
    s.add_argument("name", help="Profile name")
    s.set_defaults(func=cmd_profiles)

    s = sub.add_parser("update", help="Update profile fields (only flags passed change)",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="examples:\n"
                              "  python -m candid profiles update mle --min-salary 200000")
    s.add_argument("name", help="Profile name")
    _add_profile_flags(s)
    s.set_defaults(func=cmd_profiles)

"""Apply profile: the safe contact store used for form auto-fill.

profile.yaml holds ONLY safe contact fields. It must never contain answers
to sensitive questions (visa, compensation, EEO, ...). It is git-ignored.

As a defense in depth, load_apply_profile also rejects any key whose name
classifies as sensitive via candid.apply_fields.classify, so a key like
"desired_salary" can never sneak into the contact store even if it were
not caught by the known-key allowlist.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "pyyaml is required to load the apply profile "
        "(pip install pyyaml)"
    ) from exc

from candid.apply_fields import classify


class ApplyProfileError(Exception):
    """Raised when the apply profile is missing, unreadable, or invalid."""


@dataclass
class ApplyProfile:
    first_name: str = ""
    last_name: str = ""
    full_name: str = ""
    email: str = ""
    phone: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    country: str = ""
    linkedin: str = ""
    website: str = ""
    github: str = ""

    def value(self, key: str) -> str:
        """Return the profile value for key, or "" for missing keys."""
        return getattr(self, key, "") or ""


PROFILE_KEYS = frozenset(ApplyProfile.__dataclass_fields__)


def load_apply_profile(path: str | Path = "profile.yaml") -> ApplyProfile:
    """Load an ApplyProfile from a YAML file.

    Raises ApplyProfileError if the file is missing, is not valid YAML, or
    contains unknown keys / keys that classify as sensitive.
    """
    path = Path(path)
    if not path.exists():
        raise ApplyProfileError(
            f"Apply profile not found: {path}. "
            "Copy profile.yaml.example to profile.yaml and fill in your "
            "contact details. profile.yaml is git-ignored: never commit it."
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ApplyProfileError(
            f"Apply profile {path} is not valid YAML: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ApplyProfileError(
            f"Apply profile {path} must be a YAML mapping of contact fields."
        )
    unknown = set(data) - PROFILE_KEYS
    if unknown:
        raise ApplyProfileError(
            f"apply profile {path} contains unexpected keys "
            f"{sorted(unknown)}; only safe contact fields are allowed here."
        )
    sensitive = {
        key
        for key in data
        if classify(str(key).replace("_", " "))[0] == "sensitive"
    }
    if sensitive:
        raise ApplyProfileError(
            f"apply profile {path} contains sensitive-looking keys "
            f"{sorted(sensitive)}; the contact store must never hold "
            "visa, compensation, or EEO answers."
        )
    return ApplyProfile(
        **{k: str(v if v is not None else "") for k, v in data.items()}
    )

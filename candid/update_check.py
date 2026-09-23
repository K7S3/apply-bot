"""Update checker for candid.

Compares the installed candid version against the latest GitHub release,
caches the result on disk, and produces a one-line startup nudge when an
update is available.

Local-first: the only network call in this module is a public,
unauthenticated GET to api.github.com (short timeout, candid-specific
User-Agent). Offline or API failure degrades gracefully to
``update_available=None`` and never raises.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
from importlib import metadata

from candid import __version__
from candid import config as C

RELEASES_URL = "https://api.github.com/repos/K7S3/candid/releases"
REPO_URL = "https://github.com/K7S3/candid"
USER_AGENT = "candid-update-check"

# frequency -> cache TTL in hours
FREQUENCY_TTL_HOURS = {"daily": 24.0, "weekly": 168.0}
VALID_FREQUENCIES = ("daily", "weekly", "never")

DEFAULT_SETTINGS = {"check_enabled": True, "frequency": "daily"}

_SECURITY_RE = re.compile(r"security|cve-\d", re.IGNORECASE)


class UpdateCheckError(Exception):
    """Expected update-check failure (network, parse, no releases)."""


@dataclass
class UpdateInfo:
    current_version: str
    latest_version: str | None
    update_available: bool | None  # None = could not determine
    security: bool
    release_url: str | None
    notes: str | None
    checked_at: str | None  # ISO 8601
    error: str | None


def _data_dir():
    # Resolved lazily so CANDID_DATA_DIR overrides work even when the
    # environment is patched after import (as tests do).
    return C._data_dir()


def _settings_path():
    return _data_dir() / "update_settings.json"


def _cache_path():
    return _data_dir() / "update_check.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- version comparison ------------------------------------------------------


def parse_version(s: str) -> tuple[int, ...]:
    """Parse a version string into an int tuple.

    Strips a leading "v" and ignores any non-numeric components, so
    "v1.2.3rc1" -> (1, 2). Never raises.
    """
    s = (s or "").strip()
    if s[:1].lower() == "v":
        s = s[1:]
    parts: list[int] = []
    for piece in s.split("."):
        piece = piece.strip()
        if piece.isdigit():
            parts.append(int(piece))
    return tuple(parts)


def is_newer(latest: str, current: str) -> bool:
    """True when ``latest`` is strictly newer than ``current``.

    Versions of unequal length are padded with zeros, so "1.2.0" is
    not newer than "1.2".
    """
    lp, cp = parse_version(latest), parse_version(current)
    width = max(len(lp), len(cp))
    lp = lp + (0,) * (width - len(lp))
    cp = cp + (0,) * (width - len(cp))
    return lp > cp


def is_security_release(name: str, body: str) -> bool:
    """True if the release name or body mentions security or a CVE id."""
    return bool(_SECURITY_RE.search(f"{name or ''}\n{body or ''}"))


# --- release feed ------------------------------------------------------------


def _fetch_releases(timeout: float) -> list[dict]:
    """GET the public releases feed. Raises UpdateCheckError on failure."""
    req = urllib.request.Request(
        RELEASES_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except Exception as exc:
        raise UpdateCheckError(f"could not reach the release feed: {exc}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UpdateCheckError(f"could not parse the release feed: {exc}")
    if not isinstance(data, list):
        raise UpdateCheckError("unexpected release feed format")
    return data


def _latest_non_draft(releases: list[dict]) -> dict | None:
    for rel in releases:
        if isinstance(rel, dict) and not rel.get("draft"):
            return rel
    return None


def check_now(timeout: float = 8.0) -> UpdateInfo:
    """Check the latest release right now. Never raises.

    On any network or parse error returns an UpdateInfo with
    ``update_available=None`` and ``error`` set.
    """
    current = __version__
    checked = _now_iso()
    try:
        releases = _fetch_releases(timeout)
        rel = _latest_non_draft(releases)
        if rel is None:
            raise UpdateCheckError("no published releases found")
        raw_tag = str(rel.get("tag_name") or "").strip()
        latest = raw_tag[1:] if raw_tag[:1].lower() == "v" else raw_tag
        if not latest:
            raise UpdateCheckError("latest release has no tag name")
        name = str(rel.get("name") or "")
        body = str(rel.get("body") or "")
        url = rel.get("html_url")
        notes = body.strip()[:500] or None
        return UpdateInfo(
            current_version=current,
            latest_version=latest,
            update_available=is_newer(latest, current),
            security=is_security_release(name, body),
            release_url=str(url) if url else None,
            notes=notes,
            checked_at=checked,
            error=None,
        )
    except UpdateCheckError as exc:
        return UpdateInfo(current, None, None, False, None, None, checked, str(exc))
    except Exception as exc:  # defensive: this function never raises
        return UpdateInfo(current, None, None, False, None, None, checked, str(exc))


# --- settings ----------------------------------------------------------------


def get_settings() -> dict:
    """Return update-check settings, merged over the stored file."""
    merged = dict(DEFAULT_SETTINGS)
    try:
        data = json.loads(_settings_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key in DEFAULT_SETTINGS:
                if key in data:
                    merged[key] = data[key]
    except (OSError, ValueError):
        pass
    if merged.get("frequency") not in VALID_FREQUENCIES:
        merged["frequency"] = DEFAULT_SETTINGS["frequency"]
    if not isinstance(merged.get("check_enabled"), bool):
        merged["check_enabled"] = DEFAULT_SETTINGS["check_enabled"]
    return merged


def set_settings(
    enabled: bool | None = None, frequency: str | None = None
) -> dict:
    """Store update-check settings. Validates and returns the new dict."""
    if enabled is not None and not isinstance(enabled, bool):
        raise ValueError("enabled must be True or False")
    if frequency is not None and frequency not in VALID_FREQUENCIES:
        raise ValueError(f"frequency must be one of {sorted(VALID_FREQUENCIES)}")
    settings = get_settings()
    if enabled is not None:
        settings["check_enabled"] = enabled
    if frequency is not None:
        settings["frequency"] = frequency
    _data_dir().mkdir(parents=True, exist_ok=True)
    _settings_path().write_text(
        json.dumps(settings, indent=2), encoding="utf-8"
    )
    return settings


# --- cache -------------------------------------------------------------------


def save_cache(info: UpdateInfo) -> None:
    """Persist an UpdateInfo result to the on-disk cache."""
    _data_dir().mkdir(parents=True, exist_ok=True)
    _cache_path().write_text(json.dumps(asdict(info), indent=2), encoding="utf-8")


def load_cache() -> dict | None:
    """Return the cached check result, or None if missing/corrupt."""
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def cache_is_fresh(ttl_hours: float | None = None) -> bool:
    """True when the cached check is newer than the configured TTL."""
    cached = load_cache()
    if not cached:
        return False
    frequency = get_settings().get("frequency")
    if frequency == "never":
        return False
    if ttl_hours is None:
        ttl_hours = FREQUENCY_TTL_HOURS.get(frequency, FREQUENCY_TTL_HOURS["daily"])
    try:
        checked = datetime.fromisoformat(str(cached.get("checked_at") or ""))
    except ValueError:
        return False
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - checked
    return age <= timedelta(hours=ttl_hours)


def _info_from_cache(cached: dict) -> UpdateInfo:
    """Rebuild an UpdateInfo from cached fields, ignoring unknown keys."""
    known = {f.name for f in fields(UpdateInfo)}
    return UpdateInfo(**{k: v for k, v in cached.items() if k in known})


# --- startup nudge -----------------------------------------------------------


def _nudge_text(info: UpdateInfo) -> str:
    msg = (
        f"Update available: candid {info.latest_version} "
        f"(you have {info.current_version}) - "
        f"{info.release_url or REPO_URL}"
    )
    if info.security:
        msg += " [security update]"
    return msg


def maybe_startup_nudge() -> str | None:
    """One-line update nudge, or None when nothing should be shown.

    Fast and side-effect safe: returns None if checks are disabled or set
    to "never"; uses a fresh cache without any network; only checks the
    network (short timeout) when the cache is stale, and saves the cache
    even on failure so offline startups do not hammer the API. Swallows
    all exceptions.
    """
    try:
        settings = get_settings()
        if not settings.get("check_enabled") or settings.get("frequency") == "never":
            return None
        cached = load_cache()
        if cached is not None and cache_is_fresh():
            info = _info_from_cache(cached)
            return _nudge_text(info) if info.update_available else None
        info = check_now(timeout=2.5)
        try:
            save_cache(info)
        except Exception:
            pass
        return _nudge_text(info) if info.update_available else None
    except Exception:
        return None


# --- install mode / upgrade steps --------------------------------------------


def detect_install_mode() -> str:
    """How was candid installed: "git", "pip", or "unknown"."""
    if (C.PROJECT_ROOT / ".git").exists():
        return "git"
    try:
        metadata.distribution("candid")
    except metadata.PackageNotFoundError:
        return "unknown"
    except Exception:
        return "unknown"
    return "pip"


def upgrade_steps() -> list[str]:
    """Human-readable, safe upgrade steps for the detected install mode."""
    mode = detect_install_mode()
    if mode == "git":
        root = C.PROJECT_ROOT
        return [
            f"cd {root} && git pull --ff-only origin main",
            "Restart candid (python -m candid) to use the new version.",
        ]
    if mode == "pip":
        return [
            "pip install -U candid",
            "Restart candid (python -m candid) to use the new version.",
        ]
    return [
        "candid was installed in an unrecognized way, so no automatic upgrade is available.",
        f"Download the latest release from {REPO_URL}/releases and follow the README install steps.",
    ]

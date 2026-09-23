"""Version info and PyPI update checking for the candid CLI.

Everything here is offline-safe: any network error, cache read/write
failure, config problem, or unexpected PyPI payload yields "no update
info" (None) instead of raising, so the check can run on CLI startup
without ever breaking it.

The single source of truth for the installed version is
``candid.__version__``.
"""

from __future__ import annotations

import json
import platform
import re
import sys
import time
import urllib.request

from candid import __version__
from candid import config as C

#: PyPI JSON endpoint for the latest released version.
PYPI_JSON_URL = "https://pypi.org/pypi/candid/json"

#: Hard cap on the update-check HTTP round trip (seconds). Must stay <= 5
#: so a slow network can never stall CLI startup.
REQUEST_TIMEOUT = 5.0

#: How long a fetched PyPI answer is reused before re-checking.
CACHE_TTL = 24 * 3600


def _cache_path():
    """Where the last check result lives (per-user data dir)."""
    return C.DATA_DIR / "update_check.json"


def version_banner() -> str:
    """Human-readable one-liner: version + Python + platform."""
    py = sys.version.split()[0]
    plat = f"{platform.system()} {platform.machine()}".strip()
    return f"candid {__version__} (Python {py}, {plat})"


def _version_key(value: str) -> tuple[int, ...]:
    """Numeric prefix of a version string, for safe comparison.

    Handles "0.3.0", "0.10", "1.2.3rc1" (stops at the first non-numeric
    chunk). Malformed input sorts as empty, i.e. older than everything.
    """
    parts: list[int] = []
    for chunk in re.split(r"[.\-+_]", str(value)):
        if chunk.isdigit():
            parts.append(int(chunk))
        else:
            break
    return tuple(parts)


def is_newer(candidate: str, current: str = __version__) -> bool:
    """True when *candidate* is a newer release than *current*."""
    a, b = _version_key(candidate), _version_key(current)
    width = max(len(a), len(b))
    a += (0,) * (width - len(a))
    b += (0,) * (width - len(b))
    return a > b


def fetch_latest_version(timeout: float = REQUEST_TIMEOUT) -> str | None:
    """Ask PyPI for the newest released candid version.

    Returns the version string, or None on any network/parse failure.
    Never raises.
    """
    req = urllib.request.Request(
        PYPI_JSON_URL,
        headers={"User-Agent": f"candid/{__version__} update-check"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return str(payload["info"]["version"])
    except Exception:
        return None


def read_cache() -> dict | None:
    """Last cached check result, or None if missing/unreadable."""
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def write_cache(data: dict) -> None:
    """Persist a check result. Best effort; never raises."""
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def check_for_update(now: float | None = None,
                     timeout: float = REQUEST_TIMEOUT) -> dict | None:
    """Check PyPI for a newer candid, with a 24h disk cache.

    Returns ``{"current", "latest", "update_available"}`` or None when
    there is no usable info (offline, PyPI down, bad payload, timeout).
    Never raises.
    """
    now = time.time() if now is None else now
    cached = read_cache()
    if cached and now - float(cached.get("checked_at", 0)) < CACHE_TTL:
        latest = cached.get("latest")
        if latest:
            return _result(latest)
        return None
    latest = fetch_latest_version(timeout=timeout)
    if not latest:
        return None
    write_cache({
        "latest": latest,
        "checked_at": now,
        "notified_version": (cached or {}).get("notified_version", ""),
    })
    return _result(latest)


def _result(latest: str) -> dict:
    return {
        "current": __version__,
        "latest": latest,
        "update_available": is_newer(latest, __version__),
    }


def maybe_print_update_notice(is_json: bool = False) -> bool:
    """Print a one-line update notice when a newer candid exists.

    Returns True only when the notice was actually printed. Gated on:
    not ``--json`` output, stdout is a TTY, the user hasn't opted out
    via ``check_updates: false`` in the config file, and the notice for
    this exact version hasn't been shown before. Never raises.
    """
    try:
        if is_json:
            return False
        if not sys.stdout.isatty():
            return False
        if not C.updates_enabled():
            return False
        info = check_for_update()
        if not info or not info["update_available"]:
            return False
        cached = read_cache() or {}
        if cached.get("notified_version") == info["latest"]:
            return False
        print(f"candid {info['latest']} is available, run pip install -U candid")
        cached["latest"] = info["latest"]
        cached["checked_at"] = cached.get("checked_at", time.time())
        cached["notified_version"] = info["latest"]
        write_cache(cached)
        return True
    except Exception:
        return False

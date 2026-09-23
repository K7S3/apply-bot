"""Windows/POSIX portability helpers for the candid package.

All path policy lives here so the rest of the codebase stays
platform-agnostic. The Windows branches key off the module-level
``_ON_WINDOWS`` flag (instead of ``os.name`` directly) so tests can
flip branches on any OS via ``monkeypatch``.

Stdlib only.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Testable OS flag: monkeypatch this (not os.name) to exercise branches.
_ON_WINDOWS = os.name == "nt"


def is_windows() -> bool:
    """True when running on Windows."""
    return _ON_WINDOWS


def is_posix() -> bool:
    """True when running on a POSIX system (Linux/macOS)."""
    return not _ON_WINDOWS


def data_dir(app: str = "candid") -> Path:
    """Per-user data directory for *app*.

    Windows: ``%APPDATA%\\<app>`` (falls back to
    ``%USERPROFILE%\\AppData\\Roaming\\<app>`` when ``APPDATA`` is unset).
    POSIX: ``~/.<app>``.
    """
    if _ON_WINDOWS:
        appdata = os.environ.get("APPDATA")
        if not appdata:
            appdata = os.path.join(
                os.environ.get("USERPROFILE", str(Path.home())),
                "AppData",
                "Roaming",
            )
        return Path(appdata) / app
    return Path.home() / f".{app}"


def config_dir(app: str = "candid") -> Path:
    """Per-user config directory for *app*.

    Windows: ``%APPDATA%\\<app>`` (same as :func:`data_dir`).
    POSIX: ``~/.config/<app>``.
    """
    if _ON_WINDOWS:
        return data_dir(app)
    return Path.home() / ".config" / app


def long_path(p: os.PathLike | str) -> Path:
    """Apply the Windows ``\\\\?\\`` extended-length prefix when needed.

    On Windows, absolute paths longer than ~240 characters are returned in
    the ``\\\\?\\`` form so the Win32 ``MAX_PATH`` limit is bypassed.
    Short paths, already-prefixed paths, and all paths on POSIX are
    returned unchanged.
    """
    if not _ON_WINDOWS:
        return Path(p)
    s = str(p)
    if s.startswith("\\\\?\\"):
        return Path(s)
    if os.path.isabs(s) and len(s) > 240:
        return Path("\\\\?\\" + s)
    return Path(p)


_WIN_VAR_RE = re.compile(r"%([^%\s]+)%")


def _expand_windows_vars(s: str) -> str:
    """Expand ``%VAR%`` references using the environment.

    ``os.path.expandvars`` handles ``%VAR%`` natively on Windows, but does
    not on POSIX, so do it explicitly here to keep the Windows branch
    testable everywhere.
    """
    return _WIN_VAR_RE.sub(
        lambda m: os.environ.get(m.group(1), m.group(0)), s
    )


def normalize_path(s: os.PathLike | str) -> Path:
    """Expand ``~`` and environment variables, return a :class:`Path`.

    On Windows both ``%VAR%`` and ``$VAR`` styles expand; on POSIX
    ``~``/``$VAR`` expand as usual.
    """
    s = os.path.expanduser(str(s))
    if _ON_WINDOWS:
        s = _expand_windows_vars(s)
    s = os.path.expandvars(s)
    return Path(s)


_RESERVED_CHARS = re.compile(r'[<>:"/\\|?*]')
_RESERVED_NAMES = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def safe_filename(s: str, max_len: int = 120) -> str:
    """Make *s* safe to use as a file name on Windows (and elsewhere).

    Strips Windows-reserved characters (``<>:"/\\\\|?*``), trailing dots,
    neutralises reserved device names (``CON``, ``PRN``, ``AUX``, ``NUL``,
    ``COM1``-``COM9``, ``LPT1``-``LPT9``, compared case-insensitively
    against the name stem) by prefixing an underscore, and truncates to
    *max_len* characters. Never returns an empty string.
    """
    s = _RESERVED_CHARS.sub("", str(s)).strip().rstrip(".")
    stem = s.rsplit(".", 1)[0] if "." in s else s
    if stem.upper() in _RESERVED_NAMES:
        s = "_" + s
    if len(s) > max_len:
        s = s[:max_len]
    return s or "_"

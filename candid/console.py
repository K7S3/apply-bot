"""candid console compatibility layer.

Makes the CLI behave on Windows consoles (cmd.exe / PowerShell) as well as
it does on POSIX terminals:

* ``ensure_utf8_console`` -- switch stdout/stderr to UTF-8 so unicode output
  (em dashes, arrows, box drawing, accented names) does not raise
  ``UnicodeEncodeError`` on the legacy Windows code pages. On POSIX it is a
  no-op unless the process is running with a pure-ASCII locale (``LANG=C``).
* ``enable_vt_processing`` -- best-effort opt-in to Windows 10+ ANSI
  virtual-terminal processing via ``kernel32.SetConsoleMode``. Returns True
  when the flag is (now) on, False otherwise, and never raises.
* ``supports_color`` / ``color`` -- cheap ANSI helpers honoring ``NO_COLOR``.

Everything is stdlib-only (``ctypes``) and safe to call repeatedly.
"""

from __future__ import annotations

import os
import sys

__all__ = [
    "ensure_utf8_console",
    "enable_vt_processing",
    "supports_color",
    "color",
    "setup_console",
]

#: SGR parameter per style name used by :func:`color`.
_STYLE_CODES = {
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "bold": "1",
    "dim": "2",
}

#: ENABLE_VIRTUAL_TERMINAL_PROCESSING for kernel32.SetConsoleMode.
_ENABLE_VT_PROCESSING = 0x0004
#: GetStdHandle pseudo-handle for the console output buffer.
_STD_OUTPUT_HANDLE = -11

#: Cached result of the last :func:`enable_vt_processing` call
#: (None = not attempted yet this process).
_vt_enabled: bool | None = None


def ensure_utf8_console() -> None:
    """Reconfigure stdout/stderr to UTF-8 where it helps.

    On Windows the console defaults to a legacy OEM code page; switching to
    UTF-8 prevents ``UnicodeEncodeError`` for the unicode characters candid
    prints (arrows, box drawing, em dashes, accented names). On POSIX this is
    a no-op unless the locale encoding is plain ASCII (e.g. ``LANG=C``).

    Streams that cannot be reconfigured (piped, replaced by tests, custom
    file-likes) are silently left alone -- this never raises.
    """
    if sys.platform != "win32":
        try:
            encoding = (sys.stdout.encoding or "").lower()
        except Exception:
            return
        if encoding not in ("ascii", "us-ascii", "ansi_x3.4-1968"):
            return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            # Non-reconfigurable stream (piped, dummy, closed): leave it.
            continue


def enable_vt_processing() -> bool:
    """Enable ANSI virtual-terminal processing on the Windows console.

    Best-effort ``kernel32.SetConsoleMode(..., ENABLE_VIRTUAL_TERMINAL_
    PROCESSING)`` on the stdout handle so ANSI color/style sequences are
    interpreted instead of printed literally. Returns True when VT
    processing is (now) active, False when it could not be enabled
    (piped output, old Windows, no console). Never raises; no-op on POSIX.
    """
    global _vt_enabled
    if sys.platform != "win32":
        _vt_enabled = False
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(_STD_OUTPUT_HANDLE)
        if not handle or handle == wintypes.HANDLE(-1).value:
            _vt_enabled = False
            return False
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            # Not a console (redirected/piped): nothing to enable.
            _vt_enabled = False
            return False
        if mode.value & _ENABLE_VT_PROCESSING:
            _vt_enabled = True
            return True
        ok = bool(kernel32.SetConsoleMode(handle, mode.value | _ENABLE_VT_PROCESSING))
        _vt_enabled = ok
        return ok
    except Exception:
        # ctypes unavailable, access denied, anything else: no VT.
        _vt_enabled = False
        return False


def supports_color() -> bool:
    """True when ANSI color output is wanted and likely to render.

    Honors the ``NO_COLOR`` convention (present => no color, whatever the
    value). Otherwise True when virtual-terminal processing is enabled on
    Windows, or on POSIX when stdout is a tty or a known color-capable
    terminal emulator (Windows Terminal ``WT_SESSION``, ``TERM_PROGRAM``)
    is detected.
    """
    if "NO_COLOR" in os.environ:
        return False
    if sys.platform == "win32":
        if _vt_enabled is None:
            return enable_vt_processing()
        return _vt_enabled
    if os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM"):
        return True
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def color(text: str, name: str) -> str:
    """Wrap *text* in an ANSI style when color is supported.

    Known style names: red, green, yellow, blue, bold, dim. Returns the
    plain *text* unchanged when :func:`supports_color` is False or the
    style name is unknown -- safe to use unconditionally.
    """
    code = _STYLE_CODES.get(name)
    if code is None or not supports_color():
        return text
    return f"\033[{code}m{text}\033[0m"


def setup_console() -> None:
    """One call to make the console UTF-8 + ANSI-ready.

    Idempotent and never raises; safe to call at the top of ``main()``.
    """
    ensure_utf8_console()
    enable_vt_processing()

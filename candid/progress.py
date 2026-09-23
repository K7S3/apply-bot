"""TTY-aware progress reporting for long-running CLI work. Stdlib only.

Two tools:

- ``Progress``: determinate bar. ``with Progress("Refreshing jobs", total=50) as p:``
  then ``p.update(n=1, msg="...")`` per step.
- ``spin``: indeterminate spinner for tasks with no known total.

Behavior depends on whether the output stream is a TTY:

- TTY: a single-line bar rendered with ``\\r``
  (``Refreshing jobs [####------] 12/50 msg``), cleaned up with a newline
  on exit; the spinner animates on its own thread.
- Not a TTY: silent except for one start line and one
  ``done in Xs`` end line. No ``\\r`` spam, so piped output never breaks.

Both are unit-testable without a terminal: pass any stream (a fake with
``write``/``flush``/``isatty`` works) or force the mode with ``tty=True/False``.
"""

from __future__ import annotations

import sys
import threading
import time


class Progress:
    """Context-managed progress bar.

    Usage::

        with Progress("Refreshing jobs", total=50) as p:
            for job in jobs:
                do_work(job)
                p.update(1, msg=job["title"])

    ``total`` may be ``None`` for a simple step counter (no bar).
    """

    BAR_WIDTH = 10

    def __init__(self, label: str, total: int | None = None,
                 stream=None, tty: bool | None = None):
        self.label = label
        self.total = total
        self.done = 0
        self.msg = ""
        self.stream = stream if stream is not None else sys.stdout
        if tty is None:
            isatty = getattr(self.stream, "isatty", None)
            tty = bool(isatty() if callable(isatty) else False)
        self.tty = tty
        self._start = 0.0

    def __enter__(self) -> "Progress":
        self._start = time.monotonic()
        if not self.tty:
            self._write(f"{self.label}... ")
        return self

    def update(self, n: int = 1, msg: str = "") -> None:
        """Advance by ``n`` steps; optionally replace the trailing message."""
        self.done += max(0, n)
        if msg:
            self.msg = msg
        if self.tty:
            self._render()

    def _render(self) -> None:
        if self.total:
            frac = min(self.done / self.total, 1.0)
            filled = int(frac * self.BAR_WIDTH)
            bar = "#" * filled + "-" * (self.BAR_WIDTH - filled)
            line = f"{self.label} [{bar}] {self.done}/{self.total}"
        else:
            line = f"{self.label} {self.done}"
        if self.msg:
            line += f" {self.msg}"
        self.stream.write("\r" + line)
        self.stream.flush()

    def __exit__(self, exc_type, exc, tb) -> bool:
        elapsed = time.monotonic() - self._start
        if self.tty:
            self.stream.write("\n")
            self.stream.flush()
        else:
            self._write(f"done in {elapsed:.1f}s\n")
        return False

    def _write(self, text: str) -> None:
        self.stream.write(text)
        flush = getattr(self.stream, "flush", None)
        if callable(flush):
            flush()


class Spinner:
    """Thread-based indeterminate spinner. TTY: animates; piped: start/end lines."""

    FRAMES = "|/-\\"

    def __init__(self, label: str, stream=None, tty: bool | None = None,
                 interval: float = 0.1):
        self.label = label
        self.stream = stream if stream is not None else sys.stdout
        if tty is None:
            isatty = getattr(self.stream, "isatty", None)
            tty = bool(isatty() if callable(isatty) else False)
        self.tty = tty
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "Spinner":
        if self.tty:
            self._stop.clear()
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        else:
            self.stream.write(f"{self.label}... ")
            self.stream.flush()
        return self

    def _spin(self) -> None:
        i = 0
        while not self._stop.wait(self.interval):
            frame = self.FRAMES[i % len(self.FRAMES)]
            self.stream.write(f"\r{self.label} {frame}")
            self.stream.flush()
            i += 1

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._thread is not None:
            self._stop.set()
            self._thread.join(timeout=2)
            self._thread = None
            self.stream.write("\n")
            self.stream.flush()
        else:
            self.stream.write("done\n")
            self.stream.flush()
        return False


def spin(label: str, **kwargs) -> Spinner:
    """Return a spinner context manager for indeterminate work.

    Usage::

        with spin("Working..."):
            slow_thing()
    """
    return Spinner(label, **kwargs)

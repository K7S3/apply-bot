"""`candid doctor`: environment diagnostics.

Runs a fixed set of checks (Python version, data dir, config files,
optional Ollama reachability, disk space) and prints one PASS/WARN/FAIL
line per check with a one-line fix suggestion on failures. Exit code is 0
when nothing FAILs, 1 otherwise. ``--json`` emits machine-readable output.

Ollama and disk space can only ever WARN, never FAIL: candid works fine
without a local LLM, and a full disk is worth flagging, not blocking on.

Like profiles.py, paths resolve ``CANDID_DATA_DIR`` / ``CANDID_CONFIG_DIR``
at call time so tests can redirect them after import.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from candid import config as C

__all__ = ["DoctorError", "Check", "run_checks", "render", "cmd_doctor", "register"]

MIN_PYTHON = (3, 10)
DISK_WARN_BYTES = 100 * 1024 * 1024  # 100 MB
OLLAMA_URL = "http://localhost:11434/api/tags"
OLLAMA_TIMEOUT_S = 2


class DoctorError(Exception):
    """Raised for doctor-internal failures (not for failed checks)."""


@dataclass
class Check:
    """One diagnostic result."""
    name: str
    status: str          # "PASS" | "WARN" | "FAIL"
    detail: str
    fix: str = ""        # one-line fix suggestion; set on FAIL (and WARN)

    def as_dict(self) -> dict:
        d = {"name": self.name, "status": self.status, "detail": self.detail}
        if self.fix:
            d["fix"] = self.fix
        return d


def _data_dir() -> Path:
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return C.DATA_DIR


def _config_dir() -> Path:
    override = os.environ.get("CANDID_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    return C.CONFIG_DIR


def _samples_dir() -> Path:
    return C.SAMPLES_DIR


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------

def _check_python() -> Check:
    v = sys.version_info
    ok = (v.major, v.minor) >= MIN_PYTHON
    return Check(
        name="python-version",
        status="PASS" if ok else "FAIL",
        detail=f"{v.major}.{v.minor}.{v.micro} "
               f"({'meets' if ok else 'below'} minimum {MIN_PYTHON[0]}.{MIN_PYTHON[1]})",
        fix="" if ok else "Install Python 3.10 or newer, then re-run candid.",
    )


def _check_data_dir() -> Check:
    d = _data_dir()
    if d.is_dir():
        return Check("data-dir", "PASS", f"{d} exists")
    return Check(
        "data-dir", "FAIL", f"{d} is missing",
        fix="Run `python -m candid onboard --resume <path-to-resume>` "
            "to create your data dir and profile.",
    )


def _check_data_writable() -> Check:
    d = _data_dir()
    if not d.is_dir():
        return Check("data-dir-writable", "FAIL", f"{d} is missing",
                     fix="Fix the data-dir check above first.")
    try:
        with tempfile.TemporaryFile(dir=d):
            pass
        return Check("data-dir-writable", "PASS", f"{d} is writable")
    except OSError as exc:
        return Check(
            "data-dir-writable", "FAIL", f"cannot write to {d}: {exc}",
            fix=f"Check permissions on {d} (must be writable by your user).",
        )


def _check_profile_json() -> Check:
    p = _data_dir() / "profile.json"
    if not p.exists():
        return Check(
            "profile-json", "FAIL", f"{p} is missing",
            fix="Run `python -m candid onboard --resume <path-to-resume>` "
                "to build your profile.",
        )
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return Check(
            "profile-json", "FAIL", f"{p} is not valid JSON: {exc}",
            fix=f"Repair or delete {p}, then re-run "
                "`python -m candid onboard --resume <path-to-resume>`.",
        )
    if not isinstance(data, dict) or not data.get("skills"):
        return Check(
            "profile-json", "WARN", f"{p} parsed but looks incomplete "
                                   "(no skills found)",
            fix="Re-run `python -m candid onboard --resume <path-to-resume>` "
                "to rebuild a complete profile.",
        )
    return Check("profile-json", "PASS", f"{p} is valid")


def _check_tracker_json() -> Check:
    p = _data_dir() / "tracker.json"
    if not p.exists():
        return Check(
            "tracker-json", "WARN", f"{p} is missing",
            fix="Run `python -m candid track add --company X --role Y` "
                "to start tracking applications.",
        )
    try:
        json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return Check(
            "tracker-json", "FAIL", f"{p} is not valid JSON: {exc}",
            fix=f"Repair or delete {p}; a fresh one is created on your "
                "next `python -m candid track add`.",
        )
    return Check("tracker-json", "PASS", f"{p} is valid")


def _check_samples_dir() -> Check:
    d = _samples_dir()
    if d.is_dir():
        return Check("samples-dir", "PASS", f"{d} present")
    return Check(
        "samples-dir", "WARN", f"{d} is missing",
        fix="Reinstall candid from the repo; sample data is optional.",
    )


def _check_config_writable() -> Check:
    d = _config_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return Check(
            "config-dir-writable", "FAIL", f"cannot create {d}: {exc}",
            fix=f"Check permissions on {d.parent} or set CANDID_CONFIG_DIR "
                "to a writable path.",
        )
    try:
        with tempfile.TemporaryFile(dir=d):
            pass
        return Check("config-dir-writable", "PASS", f"{d} is writable")
    except OSError as exc:
        return Check(
            "config-dir-writable", "FAIL", f"cannot write to {d}: {exc}",
            fix=f"Check permissions on {d} or set CANDID_CONFIG_DIR "
                "to a writable path.",
        )


def _check_ollama() -> Check:
    """Ollama reachability. WARN only, never FAIL."""
    try:
        req = urllib.request.Request(OLLAMA_URL, method="GET")
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT_S) as resp:
            if resp.status == 200:
                return Check("ollama", "PASS",
                             "reachable at localhost:11434")
    except Exception:
        pass
    return Check(
        "ollama", "WARN", "not reachable at localhost:11434",
        fix="Local LLM features will be skipped. To enable them, start "
            "Ollama with `ollama serve` (see docs for the local-first setup).",
    )


def _check_disk_space() -> Check:
    """Disk space on the data-dir filesystem. WARN only, never FAIL."""
    anchor = _data_dir() if _data_dir().exists() else Path.home()
    try:
        free = shutil.disk_usage(anchor).free
    except OSError:
        return Check("disk-space", "WARN", "could not measure disk usage",
                     fix="")
    free_mb = free / (1024 * 1024)
    if free < DISK_WARN_BYTES:
        return Check(
            "disk-space", "WARN",
            f"only {free_mb:.0f} MB free on {anchor}",
            fix="Free up disk space; candid data grows with tailored "
                "resumes and prep packs.",
        )
    return Check("disk-space", "PASS", f"{free_mb:.0f} MB free on {anchor}")


def run_checks() -> list[Check]:
    """Run every diagnostic check and return the results in order."""
    return [
        _check_python(),
        _check_data_dir(),
        _check_data_writable(),
        _check_profile_json(),
        _check_tracker_json(),
        _check_samples_dir(),
        _check_config_writable(),
        _check_ollama(),
        _check_disk_space(),
    ]


# ---------------------------------------------------------------------------
# rendering + CLI
# ---------------------------------------------------------------------------

def summarize(checks: list[Check]) -> tuple[int, int, int]:
    """Return (n_pass, n_warn, n_fail)."""
    n_pass = sum(1 for c in checks if c.status == "PASS")
    n_warn = sum(1 for c in checks if c.status == "WARN")
    n_fail = sum(1 for c in checks if c.status == "FAIL")
    return n_pass, n_warn, n_fail


def render_text(checks: list[Check]) -> int:
    """Print human-readable results. Returns the process exit code."""
    for c in checks:
        line = f"[{c.status}] {c.name}: {c.detail}"
        if c.fix:
            line += f"\n         Fix: {c.fix}"
        print(line)
    n_pass, n_warn, n_fail = summarize(checks)
    print(f"\ndoctor: {n_pass} PASS, {n_warn} WARN, {n_fail} FAIL")
    return 1 if n_fail else 0


def render_json(checks: list[Check]) -> int:
    """Print machine-readable results. Returns the process exit code."""
    n_pass, n_warn, n_fail = summarize(checks)
    payload = {
        "ok": n_fail == 0,
        "summary": {"pass": n_pass, "warn": n_warn, "fail": n_fail},
        "checks": [c.as_dict() for c in checks],
    }
    print(json.dumps(payload, indent=2))
    return 1 if n_fail else 0


def cmd_doctor(a: argparse.Namespace) -> int:
    """Run `candid doctor`. Returns 0 when no check FAILs, 1 otherwise."""
    checks = run_checks()
    if getattr(a, "json", False):
        return render_json(checks)
    return render_text(checks)


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the top-level `doctor` command."""
    p = subparsers.add_parser(
        "doctor",
        help="Diagnose your candid setup",
        description="Run environment diagnostics: Python version, data and "
                    "config dirs, profile/tracker JSON validity, sample data, "
                    "Ollama reachability (optional), and disk space. "
                    "Exit code 0 when nothing FAILs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n"
               "  python -m candid doctor\n"
               "  python -m candid doctor --json  # machine-readable output",
    )
    p.add_argument("--json", action="store_true",
                   help="Machine-readable JSON output")
    p.set_defaults(func=cmd_doctor)

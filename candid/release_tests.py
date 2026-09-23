"""Release gate: full test suite plus a coverage floor.

This module runs the repo's pytest suite in a subprocess and optionally
enforces a coverage minimum. It never touches the network or any secrets,
it only runs pytest locally. Results are returned as plain dicts so the
release checklist can render them.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

PASSED_RE = re.compile(r"(\d+) passed")
FAILED_RE = re.compile(r"(\d+) failed")
ERROR_RE = re.compile(r"(\d+) error")
TOTAL_RE = re.compile(r"^TOTAL\s+\d+\s+\d+(?:\s+\d+)*\s+(\d+(?:\.\d+)?)%", re.MULTILINE)

COV_DETAIL_MISSING = "pytest-cov not installed, coverage skipped"


def parse_summary(text: str) -> dict:
    """Parse passed/failed/error counts from pytest -q output.

    The last line that mentions a count wins, so a trailing summary such
    as "3 passed, 1 failed in 0.05s" overrides any earlier noise. Each
    summary line is parsed as a whole, so a bare "5 passed" line resets
    the failed/error counts from an earlier line.
    """
    passed = failed = errors = 0
    for line in text.splitlines():
        if PASSED_RE.search(line) or FAILED_RE.search(line) or ERROR_RE.search(line):
            m = PASSED_RE.search(line)
            passed = int(m.group(1)) if m else 0
            m = FAILED_RE.search(line)
            failed = int(m.group(1)) if m else 0
            m = ERROR_RE.search(line)
            errors = int(m.group(1)) if m else 0
    return {"passed": passed, "failed": failed, "errors": errors}


def parse_total_coverage(text: str) -> float | None:
    """Parse the TOTAL percent from a coverage term-missing report."""
    m = TOTAL_RE.search(text)
    if not m:
        return None
    return float(m.group(1))


def run_pytest(repo_root: Path, timeout: int = 600, extra_args: tuple = ()) -> dict:
    """Run the test suite: python -m pytest tests -q -p no:cacheprovider.

    Returns a dict with ok, passed, failed, errors, seconds and the last
    five output lines. A timeout yields ok=False with a detail message.
    """
    cmd = [sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"]
    cmd.extend(extra_args)
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "detail": "pytest timed out after %ds" % timeout,
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "seconds": round(time.monotonic() - start, 2),
            "tail": "",
        }
    seconds = round(time.monotonic() - start, 2)
    combined = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    counts = parse_summary(combined)
    tail = "\n".join(combined.strip().splitlines()[-5:])
    return {
        "ok": proc.returncode == 0,
        "passed": counts["passed"],
        "failed": counts["failed"],
        "errors": counts["errors"],
        "seconds": seconds,
        "tail": tail,
    }


def coverage_gate(repo_root: Path, minimum: float = 80.0) -> dict:
    """Run pytest under coverage and require the TOTAL to reach minimum.

    When pytest-cov is not installed the gate is skipped, not failed:
    {"ok": None, "detail": "pytest-cov not installed, coverage skipped"}.
    """
    import importlib.util

    if importlib.util.find_spec("pytest_cov") is None:
        return {"ok": None, "detail": COV_DETAIL_MISSING}
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests",
        "-q",
        "-p",
        "no:cacheprovider",
        "--cov=candid",
        "--cov-report=term-missing",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=900,
    )
    combined = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    total = parse_total_coverage(combined)
    if total is None:
        return {"ok": False, "detail": "could not parse TOTAL coverage line"}
    ok = total >= minimum
    return {
        "ok": ok,
        "total": total,
        "minimum": minimum,
        "detail": "coverage %.1f%% (minimum %.1f%%)" % (total, minimum),
    }


def run_checks(repo_root: Path) -> list[dict]:
    """Emit the two release test-gate results for the checklist."""
    results: list[dict] = []
    t = run_pytest(repo_root)
    if t["ok"]:
        detail = "%d passed in %.1fs" % (t["passed"], t["seconds"])
    elif "detail" in t and t["detail"]:
        detail = t["detail"]
    else:
        detail = "%d passed, %d failed, %d errors in %.1fs" % (
            t["passed"],
            t["failed"],
            t["errors"],
            t["seconds"],
        )
    results.append({"name": "test suite green", "ok": t["ok"], "detail": detail})
    cov = coverage_gate(repo_root)
    results.append(
        {
            "name": "coverage >= 80%",
            "ok": cov["ok"],
            "detail": cov["detail"],
        }
    )
    return results

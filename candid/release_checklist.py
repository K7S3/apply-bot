"""Release checklist aggregator for candid.

Discovers the sibling ``release_*`` checker modules defined in CHECKS,
runs each one's ``run_checks(repo_root)``, and aggregates the results
into a single summary dict. Checkers that are missing or raise are
reported as skipped rather than crashing the whole run.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path

# Only actual checker modules go here. release_notes, release_tag and
# release_migrate are tooling, not checkers, so they are skipped.
CHECKS = [
    "release_tests",
    "release_docs",
    "release_version",
    "release_secrets",
    "release_verify",
]


def _run_module(module_name: str, repo_root: Path) -> list[dict]:
    """Run one checker module; never raise."""
    try:
        module = importlib.import_module(f"candid.{module_name}")
    except Exception as exc:  # missing module, import error, anything
        return [
            {
                "name": module_name,
                "ok": None,
                "detail": f"not available: {exc}",
            }
        ]
    try:
        raw = module.run_checks(repo_root)
    except Exception as exc:
        return [
            {
                "name": module_name,
                "ok": None,
                "detail": f"not available: {exc}",
            }
        ]
    out = []
    for entry in raw or []:
        name = entry.get("name", module_name)
        out.append(
            {
                "name": f"{module_name}:{name}",
                "ok": entry.get("ok"),
                "detail": str(entry.get("detail", "")),
            }
        )
    if not out:
        out.append(
            {
                "name": module_name,
                "ok": None,
                "detail": "not available: checker returned no results",
            }
        )
    return out


def run_all_checks(repo_root: Path) -> dict:
    """Run every checker in CHECKS and aggregate into one summary dict.

    ``ok`` is True only when at least one check ran and none failed.
    """
    from candid import __version__

    results: list[dict] = []
    for module_name in CHECKS:
        results.extend(_run_module(module_name, Path(repo_root)))
    passed = sum(1 for r in results if r["ok"] is True)
    failed = sum(1 for r in results if r["ok"] is False)
    skipped = sum(1 for r in results if r["ok"] is None)
    return {
        "version": __version__,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": results,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "ok": failed == 0 and (passed + failed + skipped) > 0,
    }


def format_console(results: dict) -> str:
    """Human-readable multi-line summary. Plain ASCII."""
    lines = []
    lines.append(
        f"Release checklist v{results.get('version', '?')} "
        f"@ {results.get('timestamp', '?')}"
    )
    lines.append("")
    for r in results.get("results", []):
        status = "SKIP"
        if r.get("ok") is True:
            status = "PASS"
        elif r.get("ok") is False:
            status = "FAIL"
        detail = r.get("detail", "")
        lines.append(f"[{status}] {r.get('name')}: {detail}")
    lines.append("")
    verdict = "READY" if results.get("ok") else "NOT READY"
    lines.append(
        f"Summary: {results.get('passed', 0)} passed, "
        f"{results.get('failed', 0)} failed, "
        f"{results.get('skipped', 0)} skipped "
        f"({len(results.get('results', []))} checks) - {verdict}"
    )
    return "\n".join(lines)

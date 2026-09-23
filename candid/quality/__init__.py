"""Data quality checks for candid: find problems in tracker/profile data.

Run ``python -m candid quality`` for a full report, or
``python -m candid quality --fix --dry-run`` to preview safe auto-fixes.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from candid import config as C


class QualityError(Exception):
    """Raised when the quality engine itself cannot run a check."""


@dataclass
class Issue:
    """One data-quality finding."""
    check: str                 # machine name, e.g. "duplicate_applications"
    severity: str              # "error", "warning", or "info"
    record_id: int | None      # tracker id, or None for global issues
    message: str               # human-readable description
    suggestion: str = ""       # human-readable fix suggestion
    auto_fix: str | None = None  # safe auto-fix key honored by --fix
    fix_args: dict = field(default_factory=dict)


# Registry of check modules; each exposes run(apps, ctx) -> list[Issue],
# where apps is the tracker record list and ctx is a dict with keys:
#   data_dir (Path), profile (dict), today (datetime.date).
CHECKS: list[str] = [
    "candid.quality.duplicates",
    "candid.quality.consistency",
    "candid.quality.completeness",
    "candid.quality.staleness",
]


def _data_dir_of(data_dir: str | Path | None) -> Path:
    return Path(data_dir) if data_dir else C.DATA_DIR


def _load_tracker(data_dir: Path) -> list[dict]:
    p = data_dir / "tracker.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise QualityError(f"Tracker file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise QualityError(f"Tracker file {p} should contain a JSON list.")
    return data


def _load_profile(data_dir: Path) -> dict:
    """Profile loads defensively: missing / invalid file -> {}."""
    p = data_dir / "profile.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def run_all(data_dir: str | Path | None = None) -> tuple[list[dict], list[Issue]]:
    """Load tracker + profile, run every registered check, return (apps, issues)."""
    dd = _data_dir_of(data_dir)
    apps = _load_tracker(dd)
    profile = _load_profile(dd)
    ctx = {"data_dir": dd, "profile": profile, "today": date.today()}
    issues: list[Issue] = []
    for mod_name in CHECKS:
        try:
            mod = importlib.import_module(mod_name)
        except ModuleNotFoundError:
            # A registered check that isn't installed (yet) is skipped -
            # the registry is pluggable; absence is not a failure.
            continue
        except ImportError as exc:
            raise QualityError(
                f"Quality check module {mod_name} failed to import: {exc}") from exc
        run = getattr(mod, "run", None)
        if not callable(run):
            raise QualityError(
                f"Quality check module {mod_name} has no run(apps, ctx).")
        found = run(apps, ctx) or []
        issues.extend(found)
    return apps, issues


def quality_score(issues: list[Issue]) -> int:
    """100 minus 10/error, 3/warning, 1/info; floors at 0."""
    counts = {"error": 0, "warning": 0, "info": 0}
    for i in issues:
        if i.severity in counts:
            counts[i.severity] += 1
    return max(0, 100 - 10 * counts["error"]
               - 3 * counts["warning"] - counts["info"])


def _issue_dict(i: Issue) -> dict:
    return {
        "check": i.check,
        "severity": i.severity,
        "record_id": i.record_id,
        "message": i.message,
        "suggestion": i.suggestion,
        "auto_fix": i.auto_fix,
        "fix_args": i.fix_args,
    }


def render_report(issues: list[Issue], json_mode: bool = False) -> str:
    """Render issues grouped by severity (text), or as a JSON array (json_mode)."""
    if json_mode:
        return json.dumps([_issue_dict(i) for i in issues], indent=2)
    if not issues:
        return "No data-quality issues found."
    lines = []
    for sev in ("error", "warning", "info"):
        group = [i for i in issues if i.severity == sev]
        if not group:
            continue
        label = f"{sev.upper()}S"  # ERRORS / WARNINGS / INFOS
        lines.append(f"{label} ({len(group)}):")
        for i in group:
            rid = f"#{i.record_id}" if i.record_id is not None else "(global)"
            lines.append(f"  [{i.check}] {rid}")
            lines.append(f"    {i.message}")
            if i.suggestion:
                lines.append(f"    Suggestion: {i.suggestion}")
        lines.append("")
    return "\n".join(lines).rstrip()

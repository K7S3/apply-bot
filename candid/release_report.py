"""Release readiness report rendering and persistence for candid.

Renders the aggregated dict from ``release_checklist.run_all_checks``
as Markdown or JSON and stores reports under the candid data dir,
pruning old ones so the folder stays small.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def _data_dir() -> Path:
    """Read at call time so tests can override CANDID_DATA_DIR late."""
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".candid"


def _safe_stamp(timestamp: str | None) -> str:
    """Filename-safe stamp. Falls back to now (UTC)."""
    if not timestamp:
        timestamp = datetime.now(timezone.utc).isoformat()
    return (
        timestamp.replace(":", "-")
        .replace("+", "-")
        .replace("T", "-")
        .replace(".", "-")
    )


def render_markdown(results: dict) -> str:
    """Render the aggregated results as Markdown."""
    version = results.get("version", "?")
    timestamp = results.get("timestamp", "?")
    entries = results.get("results", [])
    passed = results.get("passed", 0)
    failed = results.get("failed", 0)
    skipped = results.get("skipped", 0)
    verdict = "READY" if results.get("ok") else "NOT READY"

    lines = [f"# Release Readiness Report - v{version}", ""]
    lines.append(f"Generated: {timestamp}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| Version | {version} |")
    lines.append(f"| Checks | {len(entries)} |")
    lines.append(f"| Passed | {passed} |")
    lines.append(f"| Failed | {failed} |")
    lines.append(f"| Skipped | {skipped} |")
    lines.append(f"| Verdict | {verdict} |")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    if not entries:
        lines.append("No checks ran.")
    for r in entries:
        status = "SKIP"
        if r.get("ok") is True:
            status = "PASS"
        elif r.get("ok") is False:
            status = "FAIL"
        lines.append(f"### [{status}] {r.get('name')}")
        lines.append("")
        lines.append(r.get("detail", ""))
        lines.append("")
    return "\n".join(lines)


def render_json(results: dict) -> str:
    """Render the aggregated results as indented JSON."""
    return json.dumps(results, indent=2)


def write_report(
    results: dict, fmt: str = "markdown", out_dir: Path | None = None
) -> Path:
    """Write the report and return its path.

    Defaults to ``<data dir>/release_reports`` where the data dir is
    CANDID_DATA_DIR (or ~/.candid). Creates parent dirs as needed.
    """
    fmt = (fmt or "markdown").lower()
    suffix = ".json" if fmt == "json" else ".md"
    body = render_json(results) if fmt == "json" else render_markdown(results)

    target = (
        Path(out_dir) if out_dir is not None else _data_dir() / "release_reports"
    )
    target.mkdir(parents=True, exist_ok=True)
    stamp = _safe_stamp(results.get("timestamp"))
    path = target / f"release-{results.get('version', 'x')}-{stamp}{suffix}"
    path.write_text(body, encoding="utf-8")
    return path


def prune_reports(out_dir: Path | str, keep: int = 10) -> list[Path]:
    """Keep the ``keep`` newest release reports, delete the rest.

    "Newest" is by filename, which sorts chronologically because the
    timestamp stamp is filename-safe ISO. Returns the deleted paths.
    """
    out_dir = Path(out_dir)
    reports = sorted(
        [p for p in out_dir.glob("release-*") if p.is_file()],
        reverse=True,
    )
    doomed = reports[keep:]
    for p in doomed:
        p.unlink()
    return doomed

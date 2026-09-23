"""Crash bug-report generation with explicit opt-in sharing.

Local only: builds Markdown reports from the local crash log with PII
redacted. Nothing is ever transmitted automatically; sharing a report is a
manual paste by the user, and preparing a shareable report requires the user
to opt in first.
"""

from __future__ import annotations

import json
import platform
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from candid import config
from candid import redact


class BugReportError(Exception):
    """Raised when a bug report cannot be built or shared."""


# --- path resolution (defensive: fall back if config constants are missing) ---
def _crash_log_path() -> Path:
    return Path(
        getattr(config, "CRASH_LOG_PATH", config.DATA_DIR / "crash_log.jsonl")
    )


def _consent_path() -> Path:
    return Path(getattr(config, "CONSENT_PATH", config.CONFIG_DIR / "consent.json"))


def _data_dir() -> Path:
    return Path(config.DATA_DIR)


# --- crash-log access (defensive: crashlog.py is built by another worker) -----
def _read_crashes() -> list[dict]:
    """Read crash records newest-first; [] if the crash log is unavailable."""
    try:
        from candid import crashlog
    except Exception:
        return []
    read = getattr(crashlog, "read_crashes", None)
    if not callable(read):
        return []
    try:
        try:
            records = read(limit=1000)
        except TypeError:
            records = read()
    except Exception:
        return []
    return list(records or [])


def _group_count(crashes: list[dict]) -> int:
    """Number of distinct traceback groups."""
    try:
        from candid import crashlog
    except Exception:
        crashlog = None
    if crashlog is not None:
        group = getattr(crashlog, "group_crashes", None)
        if callable(group):
            try:
                return len(group() or [])
            except Exception:
                pass
    return len({c.get("traceback_hash") for c in crashes if c.get("traceback_hash")})


# --- consent ------------------------------------------------------------------
CONSENT_KEY = "crash_share_opt_in"


def get_consent() -> bool | None:
    """Return True (opted in), False (opted out), or None (undecided)."""
    try:
        data = json.loads(_consent_path().read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    value = data.get(CONSENT_KEY)
    return value if isinstance(value, bool) else None


def set_consent(value: bool) -> dict:
    """Persist the opt-in/opt-out choice. Returns the written payload."""
    payload = {
        CONSENT_KEY: bool(value),
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    path = _consent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def consent_status() -> str:
    """Human-readable consent state."""
    consent = get_consent()
    if consent is True:
        return "Crash report sharing is OPTED IN."
    if consent is False:
        return "Crash report sharing is OPTED OUT."
    return (
        "Crash report sharing is UNDECIDED. "
        "Run `candid bug-report --opt-in` to opt in or "
        "`candid bug-report --opt-out` to opt out."
    )


# --- redaction helpers ----------------------------------------------------------
def _redact(text: Any, audit: dict[str, int]) -> str:
    """Redact ``text`` and merge findings into the audit counter."""
    redacted, findings = redact.redact_text("" if text is None else str(text))
    for finding in findings:
        audit[finding["kind"]] = audit.get(finding["kind"], 0) + finding["count"]
    return redacted


def _format_frame(frame: dict, audit: dict[str, int]) -> str:
    file = _redact(frame.get("file", "?"), audit)
    module = _redact(frame.get("module", "?"), audit)
    func = _redact(frame.get("func", "?"), audit)
    line = frame.get("line", "?")
    return f"- `{file}:{line}` in `{func}` (`{module}`)"


def _audit_table(audit: dict[str, int]) -> str:
    if not audit:
        return "No PII patterns were detected in this report.\n"
    lines = ["| PII kind | Redactions |", "| --- | --- |"]
    for kind in redact.KINDS:
        if kind in audit:
            lines.append(f"| {kind} | {audit[kind]} |")
    return "\n".join(lines) + "\n"


# --- report building ------------------------------------------------------------
def _find_crash(crash_id: str | None) -> dict | None:
    crashes = _read_crashes()
    if crash_id is None:
        return crashes[0] if crashes else None
    for record in crashes:
        if str(record.get("id")) == str(crash_id):
            return record
    raise BugReportError(f"No crash record found with id {crash_id!r}.")


def build_report(crash_id: str | None = None, include_diagnostics: bool = True) -> str:
    """Build a Markdown bug report with all PII redacted.

    Uses the latest crash when ``crash_id`` is None. Raises BugReportError
    if a requested crash id does not exist.
    """
    audit: dict[str, int] = {}
    record = _find_crash(crash_id)

    lines = ["# candid bug report", ""]
    if record is None:
        lines.append("No crash records found in the local crash log.")
        lines.append("There is nothing to report yet.")
    else:
        command = _redact(record.get("command", "?"), audit)
        exc_type = _redact(record.get("exc_type", "?"), audit)
        exc_msg = _redact(record.get("exc_msg", ""), audit)
        tb_hash = _redact(record.get("traceback_hash", "?"), audit)

        lines.append("## Summary")
        lines.append(f"- Command: `{command}`")
        lines.append(f"- Time (UTC): `{record.get('ts', '?')}`")
        lines.append(f"- Exception: `{exc_type}`")
        lines.append(f"- Message: {exc_msg}")
        lines.append(f"- Traceback hash: `{tb_hash}`")
        lines.append("")

        lines.append("## Environment")
        lines.append(f"- candid: `{record.get('candid_version', '?')}`")
        py_version = (
            record.get("python") or record.get("python_version") or "?"
        )
        lines.append(f"- Python: `{py_version}`")
        lines.append(f"- Platform: `{redact.redact_platform(str(record.get('platform', '')))}`")
        lines.append("")

        lines.append("## Traceback (redacted)")
        frames = record.get("frames") or []
        if frames:
            lines.extend(_format_frame(f, audit) for f in frames)
        else:
            lines.append("No frames recorded.")
        lines.append("")

        lines.append("## Command line (redacted)")
        argv = redact.redact_argv(record.get("argv") or [])
        audit_argv = " ".join(argv)
        _, argv_findings = redact.redact_text(" ".join(str(a) for a in (record.get("argv") or [])))
        for finding in argv_findings:
            audit[finding["kind"]] = audit.get(finding["kind"], 0) + finding["count"]
        lines.append(f"`{audit_argv}`" if audit_argv else "No argv recorded.")
        lines.append("")

    lines.append("## Redaction audit")
    lines.append(
        "The following PII patterns were detected and replaced with "
        "readable markers ([EMAIL], [PHONE], [IP], <HOME>, [USER], "
        "[MAC], [TOKEN], [SID], [HOST])."
    )
    lines.append("")
    lines.append(_audit_table(audit))

    if include_diagnostics:
        lines.append("## Diagnostics")
        lines.append("```json")
        lines.append(json.dumps(build_diagnostics(), indent=2))
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def build_diagnostics() -> dict:
    """Build a redacted diagnostics dict (no secret values, ever)."""
    try:
        from candid import __version__ as candid_version
    except Exception:
        candid_version = "unknown"

    data_dir = _data_dir()
    file_count = 0
    total_bytes = 0
    if data_dir.is_dir():
        for path in data_dir.rglob("*"):
            if path.is_file():
                file_count += 1
                try:
                    total_bytes += path.stat().st_size
                except OSError:
                    pass

    crashes = _read_crashes()
    top_exc_types = dict(
        Counter(str(c.get("exc_type", "unknown")) for c in crashes).most_common(5)
    )

    return {
        "candid_version": str(candid_version),
        "python": platform.python_version(),
        "platform_redacted": redact.redact_platform(platform.platform()),
        "data_dir": {"files": file_count, "bytes_total": total_bytes},
        "crashes": {
            "total_records": len(crashes),
            "groups": _group_count(crashes),
            "top_exc_types": top_exc_types,
        },
        # Constant NAMES only, never values (values may embed paths or secrets).
        "config_keys_present": sorted(k for k in dir(config) if k.isupper()),
    }


def save_report(markdown: str, out_path: str | Path | None = None) -> Path:
    """Write the report to disk; default ``bug-report-<ts>.md`` under DATA_DIR."""
    if out_path is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_path = _data_dir() / f"bug-report-{stamp}.md"
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return path


def prepare_shareable(crash_id: str | None = None) -> tuple[Path, str]:
    """Prepare a shareable report; requires explicit opt-in.

    Returns ``(report_path, instructions)``. Nothing is transmitted
    automatically: sharing is a manual paste of the report by the user.
    Raises BugReportError unless the user has opted in.
    """
    if get_consent() is not True:
        raise BugReportError(
            "Crash report sharing is not opted in. "
            "Run `candid bug-report --opt-in` first to consent to preparing "
            "a shareable report."
        )
    report = build_report(crash_id=crash_id)
    path = save_report(report)
    instructions = (
        "How to share this crash report manually:\n"
        "\n"
        "1. Open the report file:\n"
        f"     {path}\n"
        "2. Copy its full contents.\n"
        "3. Open a new issue on the candid GitHub repository and paste the\n"
        "   report into the issue body.\n"
        "\n"
        "IMPORTANT: nothing is transmitted automatically. candid never sends\n"
        "crash data anywhere on its own; sharing happens only when you\n"
        "manually paste this report into an issue yourself."
    )
    return path, instructions

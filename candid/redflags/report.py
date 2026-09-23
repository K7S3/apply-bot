"""Human-readable reports for the JD red-flag detector.

Entry points:

- :func:`format_report` renders an ``analyze()`` result as text.
- :func:`check_file` reads a JD file and returns the formatted report.
- :func:`scan_directory` analyzes every ``.txt``/``.md`` file in a dir.
- :func:`summary_for_match` is the one-line hook for the match command.
"""

from __future__ import annotations

from pathlib import Path

from candid.redflags import greenflags as _greenflags  # noqa: F401 (registers detectors)
from candid.redflags.core import SEVERITIES, analyze
from candid.redflags.greenflags import green_adjustment


class RedFlagError(ValueError):
    """A JD file or directory could not be read or scanned."""


def _score_bar(score: int, width: int = 20) -> str:
    fill = max(0, min(width, round(score / 100 * width)))
    return "[" + "#" * fill + "-" * (width - fill) + "]"


def _split_flags(flags: list):
    greens = [f for f in flags if f.category == "green"]
    reds = [f for f in flags if f.category != "green"]
    return reds, greens


def format_report(analysis: dict) -> str:
    """Render an :func:`analyze` result as a human-readable report."""
    flags = analysis.get("flags", []) or []
    verdict = analysis.get("verdict", "clean")
    score = analysis.get("risk_score", 0) or 0
    reds, greens = _split_flags(flags)

    adjustment = green_adjustment(len(greens))
    shown = max(0, score + adjustment)

    lines = [f"Verdict: {verdict.upper()}"]
    if adjustment < 0:
        lines.append(
            f"Risk score: {shown}/100 {_score_bar(shown)} "
            f"(reduced from {score} by {len(greens)} green flag(s))")
    else:
        lines.append(f"Risk score: {shown}/100 {_score_bar(shown)}")
    lines.append("")

    if not reds and not greens:
        lines.append("No flags found - this posting looks clean.")
        return "\n".join(lines) + "\n"

    for severity in SEVERITIES:
        if severity == "info":
            continue
        group = [f for f in reds if f.severity == severity]
        if not group:
            continue
        lines.append(f"== {severity.upper()} ==")
        for f in group:
            lines.append(f"- {f.title}")
            lines.append(f"  {f.explanation}")
            if f.evidence:
                quoted = "; ".join(f'"{e}"' for e in f.evidence[:3])
                lines.append(f"  Evidence: {quoted}")
            if f.suggestion:
                lines.append(f"  Suggestion: {f.suggestion}")
        lines.append("")

    if greens:
        lines.append("Green flags (positive signals):")
        for f in greens:
            lines.append(f"+ {f.title}: {f.explanation}")
            if f.evidence:
                lines.append(f'  e.g. "{f.evidence[0]}"')
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def analyze_file(path) -> dict:
    """Read a JD text/markdown file and analyze it.

    Raises :class:`RedFlagError` if the file is missing or unreadable.
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise RedFlagError(f"JD file not found: {path}")
    except OSError as e:
        raise RedFlagError(f"Could not read JD file {path}: {e}")
    return analyze(text)


def check_file(path) -> str:
    """Read a JD file, analyze it, and return the formatted report.

    Raises :class:`RedFlagError` if the file is missing or unreadable.
    """
    return format_report(analyze_file(path))


def scan_directory(dirpath) -> list[dict]:
    """Analyze every ``.txt``/``.md`` file in a directory.

    Returns per-file summaries with filename, verdict, risk_score,
    flag_count, green_count, and adjusted_score.
    """
    d = Path(dirpath)
    if not d.is_dir():
        raise RedFlagError(f"Not a directory: {dirpath}")
    results: list[dict] = []
    for p in sorted(d.iterdir()):
        if not p.is_file() or p.suffix.lower() not in (".txt", ".md"):
            continue
        try:
            analysis = analyze_file(p)
        except RedFlagError as e:
            results.append({"filename": p.name, "error": str(e)})
            continue
        reds, greens = _split_flags(analysis["flags"])
        results.append({
            "filename": p.name,
            "verdict": analysis["verdict"],
            "risk_score": analysis["risk_score"],
            "flag_count": len(reds),
            "green_count": len(greens),
            "adjusted_score": max(
                0, analysis["risk_score"] + green_adjustment(len(greens))),
        })
    return results


def summary_for_match(jd_text: str) -> str:
    """One-line hook for the match command.

    e.g. ``"red flags: 2 (1 high) — caution (score 38)"``.
    Returns ``""`` if analysis fails.
    """
    try:
        analysis = analyze(jd_text or "")
    except Exception:
        return ""
    reds, _greens = _split_flags(analysis["flags"])
    verdict = analysis["verdict"]
    score = analysis["risk_score"]
    if not reds:
        return f"red flags: 0 — {verdict} (score {score})"
    worst = min(reds, key=lambda f: SEVERITIES.index(f.severity))
    n_worst = sum(1 for f in reds if f.severity == worst.severity)
    return (f"red flags: {len(reds)} ({n_worst} {worst.severity}) — "
            f"{verdict} (score {score})")

"""Rubric self-scores for PM practice sessions + score trends.

Dimensions (each scored 1-5):
    structure, user_empathy, metrics_thinking, prioritization, communication

Scores are timestamped and stored in DATA_DIR/pm_scores.json.
`trend` prints a text sparkline history per dimension plus the overall
average delta (last session vs first). `best` shows the best score per
dimension and the best overall session.

This module is wired into the CLI by the coordinator via register_pm();
it never touches candid.__main__ itself.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "PmScoreError",
    "DIMENSIONS",
    "MIN_SCORE",
    "MAX_SCORE",
    "SPARK_CHARS",
    "record_score",
    "load_scores",
    "save_scores",
    "trend",
    "render_trend",
    "best",
    "sparkline",
    "register_pm",
]


class PmScoreError(Exception):
    """Raised for PM-score usage errors."""


DIMENSIONS: list[str] = [
    "structure",
    "user_empathy",
    "metrics_thinking",
    "prioritization",
    "communication",
]

MIN_SCORE = 1
MAX_SCORE = 5

#: 8-level block sparkline for the 1..5 score range.
SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _data_dir() -> Path:
    """User data dir, overridable via CANDID_DATA_DIR (used by tests)."""
    override = os.environ.get("CANDID_DATA_DIR")
    return Path(override).expanduser() if override else Path.cwd() / "candid_data"


def _scores_path() -> Path:
    return _data_dir() / "pm_scores.json"


def _validate_scores(scores: dict[str, int]) -> dict[str, int]:
    """All five dimensions present, each an int in 1..5. Raises PmScoreError."""
    missing = [d for d in DIMENSIONS if d not in scores]
    if missing:
        raise PmScoreError(f"Missing dimensions: {', '.join(missing)}. "
                           f"Score all of: {', '.join(DIMENSIONS)}.")
    extra = [d for d in scores if d not in DIMENSIONS]
    if extra:
        raise PmScoreError(f"Unknown dimensions: {', '.join(extra)}.")
    cleaned: dict[str, int] = {}
    for dim in DIMENSIONS:
        value = scores[dim]
        if isinstance(value, bool) or not isinstance(value, int):
            raise PmScoreError(f"{dim}: score must be an integer, got {value!r}.")
        if not MIN_SCORE <= value <= MAX_SCORE:
            raise PmScoreError(
                f"{dim}: score {value} out of range ({MIN_SCORE}-{MAX_SCORE}).")
        cleaned[dim] = value
    return cleaned


def record_score(scores: dict[str, int], note: str = "",
                 session_ref: str = "") -> dict:
    """Create one timestamped score entry (validated, not yet saved)."""
    entry = {
        "scores": _validate_scores(scores),
        "note": note or "",
        "session_ref": session_ref or "",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    entry["average"] = round(sum(entry["scores"].values()) / len(DIMENSIONS), 2)
    return entry


def load_scores() -> list[dict]:
    """All recorded score entries (oldest first)."""
    path = _scores_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PmScoreError(f"Score file {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise PmScoreError(f"Score file {path} is corrupted (expected a list).")
    return data


def save_scores(entries: list[dict]) -> Path:
    """Write the score list to DATA_DIR/pm_scores.json."""
    path = _scores_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return path


def add_score(scores: dict[str, int], note: str = "",
              session_ref: str = "") -> dict:
    """Validate, append, and persist one score entry."""
    entry = record_score(scores, note=note, session_ref=session_ref)
    entries = load_scores()
    entries.append(entry)
    save_scores(entries)
    return entry


# ---------------------------------------------------------------------------
# trends
# ---------------------------------------------------------------------------

def sparkline(values: list[int]) -> str:
    """Map each 1..5 score to a block char. Empty input -> empty string."""
    out = []
    for v in values:
        idx = round((v - MIN_SCORE) / (MAX_SCORE - MIN_SCORE) * (len(SPARK_CHARS) - 1))
        out.append(SPARK_CHARS[max(0, min(len(SPARK_CHARS) - 1, idx))])
    return "".join(out)


def trend(entries: list[dict] | None = None) -> dict:
    """Per-dimension history plus overall average delta (last vs first).

    Raises PmScoreError when there is nothing to trend.
    """
    entries = load_scores() if entries is None else entries
    if not entries:
        raise PmScoreError("No scores recorded yet - run `score record` first.")
    per_dim: dict[str, list[int]] = {d: [] for d in DIMENSIONS}
    averages: list[float] = []
    for e in entries:
        scores = e.get("scores", {})
        for d in DIMENSIONS:
            per_dim[d].append(int(scores.get(d, 0)))
        averages.append(float(e.get("average",
                                    sum(scores.values()) / len(DIMENSIONS))))
    dimensions = {}
    for d in DIMENSIONS:
        hist = per_dim[d]
        dimensions[d] = {
            "history": hist,
            "spark": sparkline(hist),
            "first": hist[0],
            "last": hist[-1],
            "delta": hist[-1] - hist[0],
            "best": max(hist),
        }
    return {
        "sessions": len(entries),
        "dimensions": dimensions,
        "average_history": [round(a, 2) for a in averages],
        "average_delta": round(averages[-1] - averages[0], 2),
        "from": entries[0].get("recorded_at"),
        "to": entries[-1].get("recorded_at"),
    }


def _fmt_delta(delta: float) -> str:
    sign = "+" if delta > 0 else ""
    return f"{sign}{delta:g}"


def render_trend(t: dict) -> str:
    """Human-readable trend report: sparkline history per dimension + deltas."""
    lines = [f"PM practice scores — {t['sessions']} session(s)", ""]
    for d in DIMENSIONS:
        info = t["dimensions"][d]
        lines.append(
            f"{d:<16} {info['spark'] or '-':<10} "
            f"{info['first']} -> {info['last']} "
            f"({_fmt_delta(info['delta'])}, best {info['best']})"
        )
    avg_hist = " ".join(f"{a:.1f}" for a in t["average_history"])
    lines += [
        "",
        f"Overall average: {avg_hist}  (delta {_fmt_delta(t['average_delta'])})",
    ]
    return "\n".join(lines)


def best(entries: list[dict] | None = None) -> dict:
    """Best score per dimension and the best overall session.

    Raises PmScoreError when there is nothing recorded.
    """
    entries = load_scores() if entries is None else entries
    if not entries:
        raise PmScoreError("No scores recorded yet - run `score record` first.")
    per_dim_best = {}
    for d in DIMENSIONS:
        scored = [(int(e["scores"][d]), i) for i, e in enumerate(entries)]
        value, idx = max(scored)
        per_dim_best[d] = {"score": value, "session": idx}
    best_overall = max(enumerate(entries),
                       key=lambda pair: float(pair[1].get("average", 0)))
    return {
        "per_dimension": per_dim_best,
        "best_session": {"index": best_overall[0],
                         "average": best_overall[1].get("average"),
                         "recorded_at": best_overall[1].get("recorded_at"),
                         "note": best_overall[1].get("note", "")},
    }


def render_best(b: dict) -> str:
    """Human-readable best-scores report."""
    lines = ["Best PM practice scores", ""]
    for d in DIMENSIONS:
        info = b["per_dimension"][d]
        lines.append(f"{d:<16} {info['score']}/5  (session #{info['session']})")
    bs = b["best_session"]
    note = f" — {bs['note']}" if bs.get("note") else ""
    lines += ["", f"Best session: #{bs['index']} (avg {bs['average']}){note}"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI (register_pm is called by the coordinator; see module docstring)
# ---------------------------------------------------------------------------

def register_pm(subparsers) -> None:
    """Register the 'score' PM-scores subcommand on an argparse subparsers object.

    Actions: record (one --flag per dimension), trend, best.
    Flags: --note, --session-ref, --json.
    """
    p = subparsers.add_parser(
        "score", help="Record rubric self-scores for PM practice sessions.",
        epilog="examples:\n"
               "  python -m candid pm score record --structure 4 --communication 3\n"
               "  python -m candid pm score trend\n")
    p.add_argument("action", choices=["record", "trend", "best"], help="What to do.")
    for dim in DIMENSIONS:
        p.add_argument(f"--{dim.replace('_', '-')}", type=int, default=None,
                       help=f"{dim} score, {MIN_SCORE}-{MAX_SCORE} (record only).")
    p.add_argument("--note", default="", help="Optional note (record only).")
    p.add_argument("--session-ref", default="",
                   help="Optional link to a mock session (record only).")
    p.add_argument("--json", action="store_true",
                   help="Print machine-readable JSON instead of text.")
    p.set_defaults(func=cmd_pm_score)


def cmd_pm_score(args: argparse.Namespace) -> None:
    """Dispatch for the registered 'score' subcommand."""
    if args.action == "record":
        scores = {d: getattr(args, d) for d in DIMENSIONS}
        entry = add_score(scores, note=args.note, session_ref=args.session_ref)
        if args.json:
            print(json.dumps(entry, indent=2))
        else:
            detail = ", ".join(f"{d}={v}" for d, v in entry["scores"].items())
            print(f"Recorded: {detail} (avg {entry['average']})")
    elif args.action == "trend":
        t = trend()
        if args.json:
            print(json.dumps(t, indent=2))
        else:
            print(render_trend(t))
    elif args.action == "best":
        b = best()
        if args.json:
            print(json.dumps(b, indent=2))
        else:
            print(render_best(b))
    return None

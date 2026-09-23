"""Postdoc/doctoral fellowship database + upcoming-deadline commands.

Curated, human-verified list of well-known fellowships in
``candid/data/fellowships.json``. Every URL in that file was verified with
a live HTTP HEAD/GET request at build time (2026-09-22); entries whose
URL could not be verified were dropped. One entry was dropped for an
unverifiable URL: the Damon Runyon Fellowship (its /apply/ page 404'd
and the fellowship page timed out).

Data entry fields:
  name, org, url, eligibility, deadline_months (list of 1-12, may be
  empty), deadline_note, rolling (bool), verified_on (YYYY-MM-DD).

``deadline_months`` are TYPICAL cycle months, not the current call's exact
date. ``upcoming()`` projects the next cycle date from the typical month
and marks it approximate; the exact date for the current cycle must be
confirmed on the funder's page.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent / "data" / "fellowships.json"

_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def data_path() -> Path:
    return DATA_PATH


def load_fellowships(path: str | Path | None = None) -> list[dict]:
    """Load the curated fellowship list. Raises on invalid JSON."""
    p = Path(path) if path else DATA_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Fellowship data file {p} should contain a JSON list.")
    return data


def _clean_months(months) -> list[int]:
    out = []
    for m in months or []:
        try:
            m = int(m)
        except (TypeError, ValueError):
            continue
        if 1 <= m <= 12 and m not in out:
            out.append(m)
    return sorted(out)


def _next_cycle_date(months: list[int], today: date) -> date | None:
    """Next cycle date from typical months: day 1 of the earliest month
    with a date >= today. Approximate by construction."""
    months = _clean_months(months)
    if not months:
        return None
    for year in (today.year, today.year + 1):
        for m in months:
            d = date(year, m, 1)
            if d >= today:
                return d
    return None


def upcoming(days: int = 60, today: date | None = None,
             path: str | Path | None = None) -> list[dict]:
    """Fellowships with a (projected) deadline in the next ``days`` days.

    Each item: {"fellowship", "deadline" (date|None), "days_until" (int|None),
    "approx" (bool), "rolling" (bool)}. Rolling fellowships are always
    included (deadline None). Sorted by deadline, rolling last.
    """
    today = today or date.today()
    items: list[dict] = []
    for f in load_fellowships(path):
        rolling = bool(f.get("rolling"))
        if rolling:
            items.append({"fellowship": f, "deadline": None, "days_until": None,
                          "approx": False, "rolling": True})
            continue
        d = _next_cycle_date(f.get("deadline_months", []), today)
        if d is None:
            continue  # no month info and not rolling: cannot project
        delta = (d - today).days
        if 0 <= delta <= days:
            items.append({"fellowship": f, "deadline": d, "days_until": delta,
                          "approx": True, "rolling": False})
    dated = sorted([i for i in items if i["deadline"] is not None],
                   key=lambda i: i["days_until"])
    rolling_items = [i for i in items if i["rolling"]]
    return dated + rolling_items


def fellowship_deadlines(days: int = 30, today: date | None = None,
                         path: str | Path | None = None) -> list[dict]:
    """Nudge-shaped dicts for upcoming fellowship deadlines.

    Hook consumed by ``candid.nudges.pending_nudges``. Pure data, no
    network: never raises on data problems (returns [] instead).
    """
    try:
        items = upcoming(days=days, today=today, path=path)
    except Exception:
        return []
    nudges: list[dict] = []
    for it in items:
        f = it["fellowship"]
        if it["rolling"]:
            message = f"{f['name']} ({f['org']}): rolling applications - apply any time."
        else:
            d = it["deadline"]
            months = ", ".join(_MONTH_NAMES[m - 1] for m in _clean_months(f.get("deadline_months", [])))
            message = (
                f"{f['name']} ({f['org']}): next cycle ~{d.isoformat()} "
                f"({it['days_until']}d, approximate - typical {months} cycle). "
                f"Confirm the exact call date on the funder's page."
            )
        nudges.append({
            "kind": "fellowship_deadline",
            "app_id": None,
            "company": f.get("org", ""),
            "role": f.get("name", ""),
            "message": message,
            "action": "Check eligibility and apply",
            "command": "python -m candid fellowships upcoming",
        })
    return nudges


def render_list(fs: list[dict] | None = None) -> str:
    fs = load_fellowships() if fs is None else fs
    if not fs:
        return "No fellowships in the database."
    lines = [f"{'Fellowship':<52}{'Org':<40}Deadlines", "-" * 110]
    for f in fs:
        months = ", ".join(_MONTH_NAMES[m - 1] for m in _clean_months(f.get("deadline_months", [])))
        when = "rolling" if f.get("rolling") else (months or f.get("deadline_note", "see site"))
        lines.append(f"{f['name'][:51]:<52}{f['org'][:39]:<40}{when}")
        lines.append(f"  {f['url']}")
        lines.append(f"  Eligibility: {f.get('eligibility', '')}")
    return "\n".join(lines)


def render_upcoming(items: list[dict]) -> str:
    if not items:
        return "No fellowship deadlines in this window."
    lines = ["Upcoming fellowship deadlines:"]
    for it in items:
        f = it["fellowship"]
        if it["rolling"]:
            lines.append(f"  • {f['name']} ({f['org']}): rolling - apply any time. {f['url']}")
        else:
            lines.append(
                f"  • {f['name']} ({f['org']}): ~{it['deadline'].isoformat()} "
                f"({it['days_until']}d) APPROXIMATE - confirm on the funder page. {f['url']}"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI. The orchestrator wires this into candid.__main__'s top-level parser:
#
#     from candid import fellowships as F
#     F.add_parsers(top_level_subparsers)
#
# (worker-2 must not edit candid/__main__.py, so the hook is provided here.)
# ---------------------------------------------------------------------------

def cmd_fellowships(a):
    if a.what == "list":
        print(render_list())
    elif a.what == "upcoming":
        days = a.days if getattr(a, "days", None) else 60
        items = upcoming(days=days)
        print(f"Deadlines in the next {days} days:")
        print(render_upcoming(items))


def add_parsers(subparsers) -> None:
    """Register the ``fellowships`` command on the top-level subparsers.

    Commands: ``fellowships list`` and ``fellowships upcoming [--days N]``.
    """
    p = subparsers.add_parser("fellowships", help="Postdoc/doctoral fellowship database.")
    fs = p.add_subparsers(dest="what", required=True,
                          metavar="{list,upcoming}")
    fs.add_parser("list", help="List all curated fellowships.").set_defaults(func=cmd_fellowships)
    up = fs.add_parser("upcoming", help="Fellowships with deadlines in the next N days.")
    up.add_argument("--days", type=int, default=60,
                    help="Look-ahead window in days (default: 60)")
    up.set_defaults(func=cmd_fellowships)

"""Academic hiring-season calendar: a curated TYPICAL timeline.

Everything here is approximate and clearly labeled as such. The academic job
market does not run on exact dates: department timelines vary, fields differ,
and postdoc hiring is year-round. This module describes the usual shape of
the cycle so a candidate can sanity-check timing, not so they can rely on
specific dates.

Conventional shape (labeled typical/approximate throughout):
    faculty applications peak ~Sep-Nov
    faculty interviews ~Dec-Feb
    faculty offers ~Feb-Apr
    postdoc hiring year-round, with fall and spring bumps
    fellowship deadlines set by each program (no single season)
"""

from __future__ import annotations

import argparse
import calendar as _calendar
from datetime import date

#: The month-by-month typical timeline. Every entry is labeled approximate.
#: Keys: faculty, postdoc, fellowship.
MONTHS: dict[int, dict[str, str]] = {
    1: {
        "faculty": "Campus interviews typically continue; first offers start to go out.",
        "postdoc": "Spring hiring bump: many spring-start postdoc postings open.",
        "fellowship": "Program-dependent: check individual deadlines.",
    },
    2: {
        "faculty": "Offer season typically begins (~Feb-Apr): expect offers and counter-offers.",
        "postdoc": "Spring bump continues; fellowship decisions often land.",
        "fellowship": "Some fellowship start-date confirmations are due.",
    },
    3: {
        "faculty": "Offer season continues; negotiations and second visits are typical.",
        "postdoc": "Rolling postdoc hiring; late-spring postings appear.",
        "fellowship": "Program-dependent: check individual deadlines.",
    },
    4: {
        "faculty": "Offer season typically wraps up; declines free up late-cycle offers.",
        "postdoc": "Summer- and fall-start postdoc ads appear.",
        "fellowship": "Program-dependent: check individual deadlines.",
    },
    5: {
        "faculty": "Quiet months: committees regroup; occasional late or off-cycle hires.",
        "postdoc": "Fall-start postdoc interviews and decisions.",
        "fellowship": "Most fellowship deadlines are past; start paperwork season.",
    },
    6: {
        "faculty": "Quiet: job ads for the next cycle are not out yet; prep season begins.",
        "postdoc": "Year-round rolling hiring; summer starts settle in.",
        "fellowship": "Quiet: most programs finalize cohorts.",
    },
    7: {
        "faculty": "Prep season: next-cycle ads start to appear late in the month.",
        "postdoc": "Year-round rolling hiring; new FY budgets open some lines.",
        "fellowship": "Some programs announce next-cycle calls.",
    },
    8: {
        "faculty": "Faculty ads typically start appearing; finalize CV, research/teaching statements.",
        "postdoc": "Fall bump begins: postdoc ads for fall/winter starts.",
        "fellowship": "Fall-cycle fellowship deadlines approach: check programs.",
    },
    9: {
        "faculty": "Application peak (~Sep-Nov): deadlines cluster; submit polished packets.",
        "postdoc": "Fall hiring bump continues.",
        "fellowship": "Many postdoctoral fellowship deadlines fall here; check programs.",
    },
    10: {
        "faculty": "Application peak: most faculty deadlines land ~Oct-Nov.",
        "postdoc": "Fall bump tapers; rolling ads continue.",
        "fellowship": "Deadlines continue by program; confirm submissions.",
    },
    11: {
        "faculty": "Application window typically closes; committees start screening.",
        "postdoc": "Quiet-ish; rolling ads for spring starts appear late month.",
        "fellowship": "Late-fall deadlines by program.",
    },
    12: {
        "faculty": "Interview season typically begins (~Dec-Feb): first-round video calls.",
        "postdoc": "Holiday slowdown; spring-bump ads are drafted.",
        "fellowship": "Program-dependent: check individual deadlines.",
    },
}

DISCLAIMER = ("Typical cycle only: exact dates vary by field, department, and year.")


def _validate_month(month: int) -> None:
    if not 1 <= month <= 12:
        raise ValueError("Month must be 1-12.")


def month_name(month: int) -> str:
    _validate_month(month)
    return _calendar.month_name[month]


def month_view(month: int) -> dict:
    """Return the typical-timeline data for one month."""
    _validate_month(month)
    return {
        "month": month,
        "month_name": month_name(month),
        "typical": True,
        "faculty": MONTHS[month]["faculty"],
        "postdoc": MONTHS[month]["postdoc"],
        "fellowship": MONTHS[month]["fellowship"],
        "disclaimer": DISCLAIMER,
    }


def render_month(month: int) -> str:
    """Render a human-readable month view, always labeled typical/approximate."""
    m = month_view(month)
    return "\n".join([
        f"{m['month_name']}: academic hiring cycle (TYPICAL timeline)",
        f"  Faculty:    {m['faculty']}",
        f"  Postdocs:   {m['postdoc']}",
        f"  Fellowships:{m['fellowship']}",
        "",
        f"Note: {m['disclaimer']}",
    ])


# ---------------------------------------------------------------------------
# season status: where does "now" fall in the cycle
# ---------------------------------------------------------------------------

def _month_in(month: int, months: set[int]) -> bool:
    return month in months


def season_status(now: date | None = None) -> dict:
    """Describe where ``now`` falls in the typical academic hiring cycle.

    Returns {label, headline, detail, disclaimer}. Overlaps (e.g. February)
    list both phases instead of pretending the cycle is crisp.
    """
    now = now or date.today()
    m = now.month
    phases = []
    if _month_in(m, {9, 10, 11}):
        phases.append("faculty application peak (applications ~Sep-Nov)")
    if _month_in(m, {12, 1, 2}):
        phases.append("faculty interview season (~Dec-Feb)")
    if _month_in(m, {2, 3, 4}):
        phases.append("faculty offer season (~Feb-Apr)")
    if _month_in(m, {8, 9, 1, 2}):
        phases.append("postdoc hiring bump (fall/spring)")
    if _month_in(m, {5, 6, 7}):
        phases.append("quiet/ad-prep season")
    detail = "; ".join(phases) if phases else "typical cycle"
    return {
        "date": now.isoformat(),
        "month": m,
        "month_name": month_name(m),
        "phases": phases,
        "headline": (
            f"Right now ({now.strftime('%B %d, %Y')}) is typically: {detail}."
        ),
        "disclaimer": DISCLAIMER,
    }


def render_season_status(now: date | None = None) -> str:
    s = season_status(now)
    lines = [f"{s['month_name']}: {s['headline']}"]
    for p in s["phases"]:
        lines.append(f"  - {p}")
    lines += ["", f"Note: {s['disclaimer']}"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# reminders hook for the nudges system
# ---------------------------------------------------------------------------

def season_reminders(now: date | None = None) -> list[str]:
    """Reminder strings keyed to the typical cycle, consumable by nudges.

    Everything is framed as typical/approximate — the caller decides whether
    to show them. Returns [] only if nothing is relevant (practically never).
    """
    now = now or date.today()
    m = now.month
    out: list[str] = []
    if m in (8,):
        out.append("Faculty market typically opens next month: finalize your research "
                   "statement, teaching statement, and CV now.")
    if m in (9, 10):
        out.append("Faculty application peak is typically underway: prioritize "
                   "submitting polished packets before deadlines cluster.")
    if m in (11,):
        out.append("Faculty application window typically closes this month: confirm "
                   "letters of recommendation were submitted.")
    if m in (12,):
        out.append("Interview season typically begins: prep your job talk and "
                   "first-round screening answers.")
    if m in (1, 2):
        out.append("Offer season is typical now: line up negotiation priorities "
                   "before offers arrive.")
    if m in (8, 1):
        out.append("Postdoc hiring bump is typical: refresh your postdoc materials "
                   "and scan new ads.")
    if m in (9, 10, 11):
        out.append("Many fellowship deadlines are typical this season: check each "
                   "program's actual deadline; none are tracked here.")
    if m in (6, 7):
        out.append("Quiet season is typical: good window to draft next-cycle "
                   "statements without deadline pressure.")
    out.append("(These are typical-cycle reminders; exact timing varies by "
               "field and department.)")
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def add_parsers(subparsers) -> None:
    """Wire the ``academic`` command tree. Called by the coordinator."""
    p = subparsers.add_parser(
        "academic",
        help="Academic hiring-season calendar (typical/approximate timeline).")
    sub = p.add_subparsers(dest="what", required=True, metavar="<subcommand>")

    pc = sub.add_parser("calendar", help="Show the typical hiring timeline for a month.")
    pc.add_argument("--month", type=int, default=None,
                    help="Month number 1-12 (default: current month).")
    pc.set_defaults(_academic_cmd="calendar")

    sub.add_parser("season-status",
                   help="Describe where now falls in the typical hiring cycle.").set_defaults(
        _academic_cmd="season-status")
    p.set_defaults(func=cmd_academic)


def cmd_academic(a) -> None:
    """CLI dispatch for the ``academic`` command tree."""
    what = getattr(a, "_academic_cmd", None)
    if what == "calendar":
        month = getattr(a, "month", None)
        if month is None:
            month = date.today().month
        print(render_month(month))
    elif what == "season-status":
        print(render_season_status())
    else:
        raise ValueError(f"Unknown academic subcommand: {what}")

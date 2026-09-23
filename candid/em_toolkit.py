"""Managing-up toolkit + 30-60-90 day planner for Engineering Managers.

Everything here works from text the user supplies or from their profile —
nothing is invented. The templates organize the user's own notes; the
30-60-90 generator assembles a plan framework around the company/team the
user names and their real background from the profile (only when a profile
exists and loads).

Functions:
    weekly_update_template(name, team, week="") -> str
        Markdown template for a weekly team status update.
    exec_summary(notes, name="") -> str
        Turns free-form bullet notes into an executive summary. Notes are
        categorized by keyword (highlights, risks, asks, metrics); anything
        uncategorized is kept verbatim under "Other notes". Never adds facts.
    plan_30_60_90(company, team, context="", profile=None) -> str
        Markdown 30-60-90 day plan for a new EM role.
"""

from __future__ import annotations

import re


class EmToolkitError(Exception):
    """Raised for invalid managing-up toolkit input."""


# --- weekly update template --------------------------------------------------

def weekly_update_template(name: str, team: str, week: str = "") -> str:
    """Render a weekly team-status template for the user to fill in."""
    name = name or "Your Name"
    team = team or "Your Team"
    header = f"# Weekly update — {team}"
    if week:
        header += f" ({week})"
    return "\n".join([
        header,
        "",
        f"From: {name}",
        "",
        "## Wins this week",
        "- ",
        "",
        "## Progress",
        "- ",
        "",
        "## Risks and blockers",
        "- ",
        "",
        "## Next week",
        "- ",
        "",
        "## Asks of leadership",
        "- ",
        "",
    ])


# --- exec summary ------------------------------------------------------------
# Notes are grouped by keyword only. The generator never adds claims — every
# line of the output comes from the user's notes (or a section header).

_SUMMARY_CATEGORIES = [
    ("Highlights", [
        "shipped", "launched", "landed", "completed", "done", "won",
        "achieved", "closed", "merged", "deployed", "released",
    ]),
    ("Metrics", [
        "up ", "down ", "%", "percent", "improved", "reduced", "increased",
        "grew", "dropped", "rose", "fell", "qps", "latency", "slo",
        "sla", "uptime",
    ]),
    ("Risks", [
        "risk", "blocked", "blocker", "delay", "delayed", "at risk",
        "concern", "issue", "outage", "degraded", "slip", "missed",
    ]),
    ("Asks", [
        "need", "ask", "request", "approval", "approve", "decision",
        "headcount", "budget", "help needed", "escalat",
    ]),
]


def _split_notes(notes: str) -> list[str]:
    lines = []
    for raw in (notes or "").splitlines():
        line = raw.strip().lstrip("-*•").strip()
        if line:
            lines.append(line)
    return lines


def _categorize(line: str) -> str:
    text = f" {line.lower()} "
    for category, keywords in _SUMMARY_CATEGORIES:
        if any(kw in text for kw in keywords):
            return category
    return "Other notes"


def exec_summary(notes: str, name: str = "") -> str:
    """Build an exec summary from the user's free-form bullet notes.

    Each note line is categorized (Highlights, Metrics, Risks, Asks) by
    keyword and rendered verbatim under its section; uncategorized lines go
    under "Other notes". A one-line TL;DR echoes the count of items per
    section — never invented content.
    """
    lines = _split_notes(notes)
    if not lines:
        raise EmToolkitError(
            "exec-summary needs notes: pass --notes with your bullet points."
        )
    grouped: dict[str, list[str]] = {}
    order: list[str] = []
    for line in lines:
        cat = _categorize(line)
        if cat not in grouped:
            grouped[cat] = []
            order.append(cat)
        grouped[cat].append(line)

    counts = ", ".join(
        f"{len(grouped[c])} {c.lower()}" for c in order)
    out = [f"# Exec summary{f' — {name}' if name else ''}", "",
           f"TL;DR: {counts} this period.", ""]
    for cat in order:
        out.append(f"## {cat}")
        out.extend(f"- {l}" for l in grouped[cat])
        out.append("")
    return "\n".join(out)


# --- 30-60-90 day plan -------------------------------------------------------

def _background_line(profile: dict | None) -> str:
    """One grounded line about the user's background, or empty string."""
    if not isinstance(profile, dict):
        return ""
    name = profile.get("name") or ""
    years = profile.get("years_experience")
    mgmt = sum(
        1 for e in (profile.get("experience") or [])
        if isinstance(e, dict) and re.search(
            r"manager|managed|lead|director", e.get("title", "") or "",
            re.IGNORECASE)
    )
    bits = []
    if name:
        bits.append(name)
    if isinstance(years, (int, float)) and years > 0:
        bits.append(f"{years:g} years of experience")
    if mgmt:
        bits.append(f"management/lead titles at {mgmt} role(s)")
    if not bits:
        return ""
    return "Background (from your profile): " + ", ".join(bits) + "."


def plan_30_60_90(company: str, team: str, context: str = "",
                  profile: dict | None = None) -> str:
    """Generate a 30-60-90 day plan for a new EM role.

    A framework, not a fiction: sections are standard first-90-days moves
    (listen, learn, systems, team health, delivery, strategy). Company/team
    context the user supplies is woven in; the profile only contributes a
    background line. Raises EmToolkitError if company/team are missing.
    """
    company = (company or "").strip()
    team = (team or "").strip()
    if not company or not team:
        raise EmToolkitError(
            "plan-30-60-90 needs --company and --team.")
    ctx = (context or "").strip()

    lines = [
        f"# 30-60-90 day plan — Engineering Manager, {team} @ {company}",
        "",
    ]
    bg = _background_line(profile)
    if bg:
        lines += [bg, ""]
    if ctx:
        lines += [f"Context: {ctx}", ""]
    lines += [
        "## First 30 days — Listen and learn",
        "",
        "- 1:1 with every direct report: what is working, what is broken, "
        "what they want for their career.",
        "- 1:1s with skip-levels, peer EMs, product and design partners, and "
        "key stakeholders.",
        "- Map the team's systems: architecture, on-call health, deploy "
        "pipeline, dashboards.",
        "- Read the last 2 quarters of retros, postmortems, and planning docs.",
        "- Write down first impressions and open questions; share them with "
        "your manager for calibration.",
        "",
        "Goal: a listening doc with the team's top 5 strengths and top 5 "
        "pain points, validated with the team.",
        "",
        "## Days 31-60 — Stabilize and systematize",
        "",
        "- Pick 1-2 quick wins from the listening doc (small, visible, "
        "team-endorsed).",
        "- Establish or tighten rituals: standup, planning, retros, on-call "
        "handoffs, 1:1 cadence.",
        "- Start career conversations: growth areas, promotion readiness, "
        "flight risks.",
        "- Set hiring bar with the team: scorecards, structured interviews, "
        "who owns the loop.",
        "- Report up: first written update to your manager and stakeholders "
        "on what you found and what you are changing.",
        "",
        "Goal: team rituals running, quick wins shipped, a written team "
        "health snapshot.",
        "",
        "## Days 61-90 — Drive and own",
        "",
        "- Co-own the roadmap with product: commit to quarterly goals with "
        "the team.",
        "- Define the team's operating metrics (velocity, quality, on-call "
        "load) and a review cadence.",
        "- Make one structural bet: staffing change, process redesign, or "
        "technical investment the team needs.",
        "- Deliver a 90-day review to stakeholders: what changed, what is "
        "next, what you need from them.",
        "- Lock your own management rhythm: weekly priorities, monthly "
        "stakeholder updates, quarterly planning.",
        "",
        "Goal: an owned roadmap, measurable team-health metrics, and a "
        "clear ask of leadership for the next quarter.",
        "",
    ]
    return "\n".join(lines)

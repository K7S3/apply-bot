"""Startup interview-loop prep section (additive to ``prep.build_pack``).

``python -m candid prep --startup`` appends one extra section to the
standard prep pack, covering the rounds that are specific to startup
interviews:

  1. Founder / vision chat - why this startup, why now, equity vs cash.
  2. Technical deep-dive - startup flavor: breadth, ownership, shipping.
  3. Trial project guidance - how to scope and prepare for a take-home.
  4. Reference-call prep - lining up references before the offer stage.

Important boundary: this section ORGANIZES preparation for a take-home or
trial project. It never does the take-home work itself. If you need a
scratchpad for your own code, that is yours to write.

Usage:
    from candid import startup_prep as SP
    section = SP.startup_section(company, role, jd=jd)
    markdown = SP.append_startup_section(markdown, company, role, jd=jd)
"""

from __future__ import annotations


class StartupPrepError(Exception):
    """Raised when the startup section cannot be built."""


def _jd_hints(jd: str) -> list[str]:
    """Pick up startup signals from the JD text to personalize the section."""
    hints: list[str] = []
    low = (jd or "").lower()
    if any(w in low for w in ("0 to 1", "0-to-1", "greenfield", "build from scratch")):
        hints.append("- The JD stresses 0-to-1 work: prepare a story about building something from nothing, including the parts you deliberately left out.")
    if any(w in low for w in ("seed", "series a", "series b", "early-stage")):
        hints.append("- Early stage is explicit: expect questions about wearing many hats and thriving without a PM/mentor safety net.")
    if any(w in low for w in ("equity", "stock options", "options")):
        hints.append("- Equity is mentioned: have a point of view on risk vs upside, and read the offer/negotiation playbook before the founder chat.")
    if "remote" in low:
        hints.append("- Remote-friendly: founders will probe your async communication habits, so have two concrete examples ready.")
    return hints


def startup_section(company: str, role: str, jd: str = "") -> str:
    """Return the startup-interview-loop section as Markdown.

    Pure string builder - no file writes, no side effects.
    """
    if not (company or "").strip() or not (role or "").strip():
        raise StartupPrepError("startup_section needs both a company and a role.")
    co = (company or "the startup").strip()
    lines = [
        "## 9. Startup interview loop",
        "",
        f"_Startups interview differently from big companies: fewer rounds, more "
        f"signal per round, and the founder chat is often the real decision "
        f"round. This section is prep only - it helps you organize, not answer "
        f"for you._",
        "",
        "### A. Founder / vision chat",
        "",
        "- Have a one-sentence answer for 'why this startup' that names a "
        "specific product decision or market bet, not just the mission.",
        "- Have a one-sentence answer for 'why now': what changed in the world "
        "that makes this company possible today?",
        "- Know the funding stage, headcount, and revenue model well enough to "
        "discuss tradeoffs (growth vs profitability) like an owner.",
        "- Prepare 3 questions for the founder: one on vision, one on the "
        "hardest current problem, one on how they measure success for this role.",
        "- If equity is on the table, decide your cash-vs-equity preference "
        "before the chat, not during it.",
        "",
        "### B. Technical deep-dive (startup flavor)",
        "",
        "- Go one layer deeper than usual on the system you know best: "
        "startups hire for ownership, so 'I built it end to end' beats 'I "
        "optimized one component'.",
        "- Be ready to whiteboard tradeoffs under constraints: scale on a "
        "budget, ship speed vs correctness, build vs buy.",
        "- Breadth questions are common ('walk me through our stack'): research "
        f"{co}'s tech choices and have an opinion on one of them.",
        "- Expect at least one 'what would you build first in 30 days' prompt: "
        "answer with a plan, a metric, and what you would explicitly not do.",
        "",
        "### C. Trial project / take-home guidance",
        "",
        "**Boundary: candid organizes your preparation. It does not do the "
        "take-home work for you.** If you share a take-home here, candid will "
        "help you plan it, scope it, and review your approach, but the code, "
        "design, and writeup are yours to produce.",
        "",
        "- Timebox before you start: agree on hours with the interviewer, then "
        "plan to finish in 80% of that time so you have a review pass.",
        "- Scope ruthlessly: a clean, working core beats a half-finished "
        "ambitious version. Write down your scope decisions as you go.",
        "- Prepare a 5-minute walkthrough: problem restatement, key decisions "
        "and rejected alternatives, what you would do with one more week.",
        "- Ask ahead whether to optimize for code quality or a working demo, "
        "and what the evaluation rubric is.",
        "",
        "### D. Reference-call prep",
        "",
        "- Line up 2-3 references before the offer stage: a former manager, a "
        "peer, and ideally someone who saw you own something end to end.",
        "- Give each reference your resume bullets and the role description so "
        "their stories land on the right themes.",
        "- Warn them a founder may call (not just HR), and that the call may "
        "happen fast - 24-48 hour notice is normal at startups.",
        "",
    ]
    hints = _jd_hints(jd)
    if hints:
        lines += ["### JD-specific notes", ""]
        lines += hints
        lines += [""]
    lines += [
        "_After the loop: debrief within 24 hours while it is fresh, then run "
        "`python -m candid followup thank-you` for each interviewer._",
        "",
    ]
    return "\n".join(lines)


def append_startup_section(markdown: str, company: str, role: str,
                           jd: str = "") -> str:
    """Append the startup section to a prep-pack markdown string.

    Additive only: the original markdown is left intact, the section is
    appended before any trailing ``---`` footer.
    """
    section = startup_section(company, role, jd=jd)
    if not markdown:
        return section
    if markdown.rstrip().endswith("---"):
        body = markdown.rstrip()[: -len("---")].rstrip()
        return body + "\n\n" + section + "\n---"
    return markdown.rstrip() + "\n\n" + section

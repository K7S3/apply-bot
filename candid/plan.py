"""30-60-90 day plan generator: role-specific onboarding plans.

Builds a personalized first-90-day plan from a role-family template
(``candid/plan_templates.py``), tracks milestones, drafts success metrics,
maps stakeholders, and exports manager-ready documents.

Stored as JSON at candid_data/plans.json (git-ignored); exports go to
candid_data/plan_exports/.
"""

from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path

from candid import config as C
from candid import plan_templates as PT


class PlanError(Exception):
    """Raised for invalid plan operations."""


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------

def _load(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else C.PLANS_PATH
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PlanError(f"Plans file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise PlanError(f"Plans file {p} should contain a JSON list.")
    return data


def _save(plans: list[dict], path: str | Path | None = None) -> Path:
    p = Path(path) if path else C.PLANS_PATH
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(plans, indent=2), encoding="utf-8")
    return p


def _next_id(plans: list[dict]) -> int:
    return max((pl.get("id", 0) for pl in plans), default=0) + 1


# ---------------------------------------------------------------------------
# plan construction
# ---------------------------------------------------------------------------

def _validate_start(start: str | None) -> str:
    if not start:
        return date.today().isoformat()
    try:
        y, m, d = (int(x) for x in start.split("-"))
        return date(y, m, d).isoformat()
    except (ValueError, TypeError):
        raise PlanError(
            f"Invalid --start-date {start!r}. Use YYYY-MM-DD.") from None


def _profile_skills(profile: dict | None) -> list[str]:
    """Flatten a candid profile dict into lowercase skill keywords."""
    if not profile:
        return []
    skills: list[str] = []
    for key in ("skills", "technologies", "tools", "languages"):
        val = profile.get(key)
        if isinstance(val, list):
            skills.extend(str(s) for s in val)
        elif isinstance(val, str):
            skills.extend(val.split(","))
    out: list[str] = []
    for s in skills:
        s = s.strip().lower()
        if len(s) > 2:
            out.append(s)
            for part in s.replace("/", " ").replace("-", " ").split():
                if len(part) > 2 and part not in out:
                    out.append(part)
    return out


def _personalize_learning(learning: list[dict],
                          profile: dict | None) -> list[dict]:
    """Downgrade learning topics the candidate's profile already covers."""
    skills = _profile_skills(profile)
    if not skills:
        return learning
    for item in learning:
        topic = item["topic"].lower()
        if any(skill and skill in topic for skill in skills):
            item["priority"] = "low"
            item["why"] += " (Covered by your background: deprioritized.)"
    return learning


def build_plan(company: str, role: str, *, level: str = "mid",
               start_date: str | None = None, name: str = "",
               profile: dict | None = None,
               focus_areas: list[str] | None = None,
               family: str | None = None) -> dict:
    """Assemble a plan dict (not yet saved)."""
    if not company or not role:
        raise PlanError("Both company and role are required to build a plan.")
    fam = family or PT.detect_family(role)
    if fam not in PT.ROLE_TEMPLATES:
        raise PlanError(
            f"Unknown role family {family!r}. Choose from: "
            + ", ".join(sorted(PT.ROLE_TEMPLATES)))
    tier = PT.detect_tier(level)
    tmpl = PT.get_template(fam)
    modifier = PT.LEVEL_MODIFIERS[tier]

    start = _validate_start(start_date)
    gid, lid, mid_ = 0, 0, 0

    phases = []
    for pdef, tphase in zip(PT.PHASE_DEFS, tmpl["phases"]):
        goals = []
        for g in tphase["goals"]:
            gid += 1
            goals.append({"id": f"g{gid}", "text": g["text"],
                          "week": g["week"], "kind": g["kind"],
                          "done": False, "done_on": None})
        for g in modifier["add_goals"].get(pdef["key"], []):
            gid += 1
            goals.append({"id": f"g{gid}", "text": g["text"],
                          "week": g["week"], "kind": g["kind"],
                          "done": False, "done_on": None,
                          "level_added": True})
        phases.append({"key": pdef["key"], "name": pdef["title"],
                       "days": pdef["days"], "theme": pdef["theme"],
                       "goals": goals})

    # caller-supplied focus areas become extra delivery goals in days 31-60
    if focus_areas:
        p60 = next(p for p in phases if p["key"] == "p60")
        for area in focus_areas:
            area = area.strip()
            if not area:
                continue
            gid += 1
            p60["goals"].append(
                {"id": f"g{gid}", "text": f"Make progress on focus area: {area}",
                 "week": 6, "kind": "delivery", "done": False,
                 "done_on": None, "custom": True})

    learning = _personalize_learning(tmpl["learning"], profile)
    for item in learning:
        lid += 1
        item["id"] = f"l{lid}"
        item["done"] = False

    stakeholders = list(tmpl["stakeholders"]) + modifier["add_stakeholders"]

    metrics = []
    for m in tmpl["metrics"]:
        mid_ += 1
        metrics.append({"id": f"m{mid_}", "phase": m["phase"],
                        "metric": m["metric"],
                        "how_measured": m["how_measured"]})

    return {
        "id": 0,  # assigned on create()
        "company": company.strip(),
        "role": role.strip(),
        "role_family": fam,
        "role_label": tmpl["label"],
        "level": level.strip() or "mid",
        "level_tier": tier,
        "level_note": modifier["note"],
        "name": (name or "").strip(),
        "start_date": start,
        "created": date.today().isoformat(),
        "phases": phases,
        "learning": learning,
        "stakeholders": stakeholders,
        "metrics": metrics,
        "notes": "",
    }


def create(company: str, role: str, *,
           level: str = "mid", start_date: str | None = None,
           name: str = "", profile: dict | None = None,
           focus_areas: list[str] | None = None,
           family: str | None = None,
           path: str | Path | None = None) -> dict:
    """Build a plan and persist it. Returns the saved plan."""
    plan = build_plan(company, role, level=level, start_date=start_date,
                      name=name, profile=profile,
                      focus_areas=focus_areas, family=family)
    plans = _load(path)
    plan["id"] = _next_id(plans)
    plans.append(plan)
    _save(plans, path)
    return plan


def list_plans(path: str | Path | None = None) -> list[dict]:
    """All plans, newest first."""
    return sorted(_load(path), key=lambda p: p.get("id", 0), reverse=True)


def get_plan(plan_id: int, path: str | Path | None = None) -> dict:
    """Fetch one plan by id, or raise PlanError."""
    for plan in _load(path):
        if plan.get("id") == plan_id:
            return plan
    raise PlanError(
        f"No 90-day plan with id {plan_id}. Use `plan list` to see ids.")


def remove(plan_id: int, path: str | Path | None = None) -> None:
    """Delete a plan."""
    plans = _load(path)
    kept = [p for p in plans if p.get("id") != plan_id]
    if len(kept) == len(plans):
        raise PlanError(f"No 90-day plan with id {plan_id}.")
    _save(kept, path)


# ---------------------------------------------------------------------------
# progress tracking
# ---------------------------------------------------------------------------

def _iter_goals(plan: dict):
    for phase in plan["phases"]:
        for goal in phase["goals"]:
            yield phase, goal


def check(plan_id: int, goal_id: str,
          path: str | Path | None = None) -> dict:
    """Mark a milestone done. Returns the updated plan."""
    plans = _load(path)
    plan = next((p for p in plans if p.get("id") == plan_id), None)
    if plan is None:
        raise PlanError(f"No 90-day plan with id {plan_id}.")
    for _, goal in _iter_goals(plan):
        if goal["id"] == goal_id.lower():
            goal["done"] = True
            goal["done_on"] = date.today().isoformat()
            _save(plans, path)
            return plan
    raise PlanError(
        f"No goal {goal_id!r} in plan #{plan_id}. Use `plan show {plan_id}` "
        "to see goal ids.")


def uncheck(plan_id: int, goal_id: str,
            path: str | Path | None = None) -> dict:
    """Reopen a milestone. Returns the updated plan."""
    plans = _load(path)
    plan = next((p for p in plans if p.get("id") == plan_id), None)
    if plan is None:
        raise PlanError(f"No 90-day plan with id {plan_id}.")
    for _, goal in _iter_goals(plan):
        if goal["id"] == goal_id.lower():
            goal["done"] = False
            goal["done_on"] = None
            _save(plans, path)
            return plan
    raise PlanError(f"No goal {goal_id!r} in plan #{plan_id}.")


def check_learning(plan_id: int, learning_id: str,
                   path: str | Path | None = None) -> dict:
    """Mark a learning objective complete. Returns the updated plan."""
    plans = _load(path)
    plan = next((p for p in plans if p.get("id") == plan_id), None)
    if plan is None:
        raise PlanError(f"No 90-day plan with id {plan_id}.")
    for item in plan["learning"]:
        if item["id"] == learning_id.lower():
            item["done"] = True
            _save(plans, path)
            return plan
    raise PlanError(f"No learning item {learning_id!r} in plan #{plan_id}.")


def progress(plan_id: int, path: str | Path | None = None) -> dict:
    """Completion stats overall and per phase."""
    plan = get_plan(plan_id, path)
    goals = [g for _, g in _iter_goals(plan)]
    total = len(goals)
    done = sum(1 for g in goals if g["done"])
    by_phase = {}
    for phase in plan["phases"]:
        pt, pd = len(phase["goals"]), sum(1 for g in phase["goals"] if g["done"])
        by_phase[phase["key"]] = {
            "name": phase["name"], "total": pt, "done": pd,
            "pct": round(100 * pd / pt) if pt else 0,
        }
    learn = plan["learning"]
    return {
        "plan_id": plan_id,
        "total": total,
        "done": done,
        "pct": round(100 * done / total) if total else 0,
        "by_phase": by_phase,
        "learning_total": len(learn),
        "learning_done": sum(1 for l in learn if l["done"]),
    }


def render_progress(p: dict) -> str:
    """Human-readable progress summary."""
    lines = [f"Plan #{p['plan_id']}: {p['done']}/{p['total']} milestones "
             f"done ({p['pct']}%)",
             f"Learning objectives: {p['learning_done']}/{p['learning_total']} done"]
    for key, b in p["by_phase"].items():
        bar = "#" * (b["pct"] // 10) + "-" * (10 - b["pct"] // 10)
        lines.append(f"  [{bar}] {b['name']}: {b['done']}/{b['total']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# weekly check-in
# ---------------------------------------------------------------------------

def week_view(plan_id: int, week: int,
              path: str | Path | None = None) -> dict:
    """Goals due in a given week (1-12) plus reflection prompts."""
    if not 1 <= week <= 12:
        raise PlanError(f"Week must be 1-12, got {week}.")
    plan = get_plan(plan_id, path)
    phase = next(p for p in plan["phases"]
                 if PT.WEEK_RANGES[p["key"]][0] <= week
                 <= PT.WEEK_RANGES[p["key"]][1])
    goals = [g for g in phase["goals"] if g["week"] == week]
    upcoming = [g for g in phase["goals"]
                if g["week"] == week + 1 and not g["done"]]
    return {
        "plan_id": plan_id,
        "week": week,
        "phase": phase["name"],
        "phase_theme": phase["theme"],
        "goals": goals,
        "upcoming": upcoming,
        "prompts": PT.REFLECTION_PROMPTS,
    }


def render_week(w: dict) -> str:
    """Human-readable weekly focus sheet."""
    lines = [f"Week {w['week']} — {w['phase']}",
             f"Theme: {w['phase_theme']}", ""]
    if w["goals"]:
        lines.append("This week's milestones:")
        for g in w["goals"]:
            box = "[x]" if g["done"] else "[ ]"
            lines.append(f"  {box} {g['id']}: {g['text']} ({g['kind']})")
    else:
        lines.append("No milestones scheduled this week: use it to catch up "
                     "or go deeper on learning goals.")
    if w["upcoming"]:
        lines.append("")
        lines.append("Coming next week:")
        for g in w["upcoming"]:
            lines.append(f"  [ ] {g['id']}: {g['text']}")
    lines.append("")
    lines.append("Weekly reflection (5 minutes):")
    for i, prompt in enumerate(w["prompts"], 1):
        lines.append(f"  {i}. {prompt}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# rendered views
# ---------------------------------------------------------------------------

def summarize(plan: dict) -> str:
    """One-screen overview of a plan."""
    p = progress(plan["id"])
    who = f" for {plan['name']}" if plan.get("name") else ""
    lines = [
        f"90-day plan #{plan['id']}{who}: {plan['role']} @ {plan['company']}",
        f"Template: {plan['role_label']} | Level: {plan['level']} "
        f"({plan['level_tier']}) | Start: {plan['start_date']}",
        f"Progress: {p['done']}/{p['total']} milestones ({p['pct']}%)",
        "",
    ]
    for phase in plan["phases"]:
        lines.append(f"{phase['name']} ({phase['days']})")
        for g in phase["goals"]:
            box = "[x]" if g["done"] else "[ ]"
            lines.append(f"  {box} {g['id']} (wk{g['week']}): {g['text']}")
    return "\n".join(lines)


def render_list(plans: list[dict], path: str | Path | None = None) -> str:
    """Compact table of plans."""
    if not plans:
        return ("No 90-day plans yet. Create one with:\n"
                "  python -m candid plan new --company Acme --role \"Backend Engineer\"")
    rows = []
    for p in plans:
        pr = progress(p["id"], path)
        rows.append(f"#{p['id']}: {p['role']} @ {p['company']} "
                    f"[{p['level_tier']}, start {p['start_date']}] "
                    f"{pr['done']}/{pr['total']} done")
    return "\n".join(rows)


def render_stakeholders(plan: dict) -> str:
    """Stakeholder map with meeting cadence and first-meeting questions."""
    lines = [f"Stakeholder map — {plan['role']} @ {plan['company']}", ""]
    for s in plan["stakeholders"]:
        lines.append(f"- {s['role']} (cadence: {s['cadence']})")
        for q in s["first_meeting"]:
            lines.append(f"    * {q}")
        if s.get("notes"):
            lines.append(f"    ({s['notes']})")
    return "\n".join(lines)


def render_learning(plan: dict) -> str:
    """Learning objectives with resources and completion state."""
    lines = [f"Learning goals — {plan['role']} @ {plan['company']}", ""]
    for item in plan["learning"]:
        box = "[x]" if item["done"] else "[ ]"
        lines.append(f"{box} {item['id']}: {item['topic']} "
                     f"(priority: {item['priority']})")
        lines.append(f"     Why: {item['why']}")
        for r in item["resources"]:
            lines.append(f"     - {r}")
    return "\n".join(lines)


def render_metrics(plan: dict) -> str:
    """Draft success metrics grouped by phase."""
    lines = [f"Success metrics draft — {plan['role']} @ {plan['company']}",
             "Review these with your manager in week 1 and adjust.", ""]
    for phase in ("30", "60", "90"):
        ms = [m for m in plan["metrics"] if m["phase"] == phase]
        if not ms:
            continue
        lines.append(f"By day {phase}:")
        for m in ms:
            lines.append(f"  - {m['metric']}")
            lines.append(f"    Measured by: {m['how_measured']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 1:1 agendas
# ---------------------------------------------------------------------------

AGENDA_KINDS = ("first", "weekly", "monthly")


def agenda(plan: dict, kind: str = "first") -> str:
    """Draft a 1:1 agenda. Kinds: first, weekly, monthly."""
    if kind not in AGENDA_KINDS:
        raise PlanError(f"Unknown agenda kind {kind!r}. "
                        f"Choose from: {', '.join(AGENDA_KINDS)}")
    name = plan.get("name") or "Your Name"
    role, company = plan["role"], plan["company"]
    manager = next((s for s in plan["stakeholders"]
                    if "manager" in s["role"].lower()), None)
    mgr_questions = (manager["first_meeting"] if manager
                     else ["What does success look like at 30/60/90 days?"])

    if kind == "first":
        lines = [
            f"First 1:1 agenda — {name}, {role} @ {company}",
            "",
            "1. Intros (10 min): background, what excited you about the role",
            "2. Align on expectations (15 min):",
        ]
        lines += [f"   - {q}" for q in mgr_questions]
        lines += [
            "3. Working style (10 min): feedback preferences, update format, "
            "how to raise blockers",
            "4. Immediate next steps (5 min): onboarding checklist, first "
            "small win, intro meetings to schedule",
            "",
            "Bring: your draft 30-60-90 plan (`python -m candid plan export "
            f"{plan['id']}`) and three questions about the team.",
        ]
    elif kind == "weekly":
        lines = [
            f"Weekly 1:1 agenda — {name}, {role} @ {company}",
            "",
            "1. Wins since last time (5 min)",
            "2. 30-60-90 progress check (10 min): milestones done, "
            "milestones at risk",
            "3. Blockers / help needed (10 min)",
            "4. Feedback exchange (10 min): one thing going well, one thing "
            "to adjust",
            "5. Priorities for next week (5 min)",
            "",
            "Tip: update milestones first with "
            f"`python -m candid plan check {plan['id']} <goal-id>`.",
        ]
    else:
        lines = [
            f"Monthly / skip-level agenda — {name}, {role} @ {company}",
            "",
            "1. What you have learned about the team and product (10 min)",
            "2. Your impact so far, mapped to team goals (10 min)",
            "3. What the org needs that nobody owns (10 min)",
            "4. Career growth: skills you want to build next quarter (10 min)",
            "",
            "Bring: one observation about the org and one concrete suggestion.",
        ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 90-day self-review draft
# ---------------------------------------------------------------------------

def review_draft(plan: dict) -> str:
    """Draft a 90-day self-review from completed (and open) milestones."""
    name = plan.get("name") or "Your Name"
    done_by_kind: dict[str, list[str]] = {}
    open_items: list[str] = []
    for _, g in _iter_goals(plan):
        if g["done"]:
            done_by_kind.setdefault(g["kind"], []).append(g["text"])
        else:
            open_items.append(g["text"])
    done_learning = [l["topic"] for l in plan["learning"] if l["done"]]

    lines = [
        f"90-day self-review draft — {name}, {plan['role']} @ {plan['company']}",
        f"Review period: {plan['start_date']} to day 90",
        "",
        "## Wins",
    ]
    wins = done_by_kind.get("delivery", [])
    if wins:
        lines += [f"- {w}" for w in wins]
    else:
        lines.append("- (No completed delivery milestones yet: finish a few "
                     "with `plan check` before your review.)")
    lines += ["", "## Learning and ramp-up"]
    learned = done_by_kind.get("learning", []) + [
        f"Completed learning objective: {t}" for t in done_learning]
    if learned:
        lines += [f"- {x}" for x in learned]
    else:
        lines.append("- (Nothing marked done yet.)")
    lines += ["", "## Relationships built"]
    rels = done_by_kind.get("relationship", [])
    if rels:
        lines += [f"- {r}" for r in rels]
    else:
        lines.append("- (Nothing marked done yet.)")
    lines += ["", "## Growth areas / still open"]
    if open_items:
        lines += [f"- {o}" for o in open_items[:8]]
        if len(open_items) > 8:
            lines.append(f"- ... and {len(open_items) - 8} more open milestones")
    else:
        lines.append("- All milestones complete: propose stretch goals for the next 90 days.")
    lines += [
        "",
        "## Next 90 days (propose to your manager)",
        "- Deepen ownership: pick one area to be the recognized expert in",
        "- Measurable impact: attach a number to your main initiative",
        "- Multiply: mentor, document, or automate something for the team",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# full-plan export
# ---------------------------------------------------------------------------

def render_markdown(plan: dict) -> str:
    """Full plan as manager-shareable Markdown."""
    who = f" for {plan['name']}" if plan.get("name") else ""
    lines = [
        f"# 30-60-90 Day Plan{who}: {plan['role']} @ {plan['company']}",
        "",
        f"- Template: {plan['role_label']}",
        f"- Level: {plan['level']} ({plan['level_tier']})",
        f"- Start date: {plan['start_date']} | Created: {plan['created']}",
        "",
        f"> {plan['level_note']}",
        "",
        "## Phases",
    ]
    for phase in plan["phases"]:
        lines += ["", f"### {phase['name']}", "", f"*{phase['theme']}*", ""]
        for g in phase["goals"]:
            box = "[x]" if g["done"] else "[ ]"
            tag = " *(level-added)*" if g.get("level_added") else ""
            tag = " *(custom)*" if g.get("custom") else tag
            lines.append(f"- {box} **{g['id']}** (week {g['week']}, "
                         f"{g['kind']}){tag}: {g['text']}")
    lines += ["", "## Learning goals", ""]
    for item in plan["learning"]:
        box = "[x]" if item["done"] else "[ ]"
        lines.append(f"- {box} **{item['id']}** [{item['priority']}] "
                     f"{item['topic']}: {item['why']}")
    lines += ["", "## Stakeholder map", ""]
    for s in plan["stakeholders"]:
        lines.append(f"- **{s['role']}** — {s['cadence']}")
        for q in s["first_meeting"]:
            lines.append(f"  - {q}")
    lines += ["", "## Success metrics (draft: align with manager in week 1)", ""]
    for m in plan["metrics"]:
        lines.append(f"- By day {m['phase']}: {m['metric']} "
                     f"*(measured by: {m['how_measured']})*")
    if plan.get("notes"):
        lines += ["", "## Notes", "", plan["notes"]]
    lines += ["", "---",
              "*Generated by candid's 30-60-90 day plan generator. "
              "Review with your manager in week 1.*"]
    return "\n".join(lines)


def _render_html(plan: dict) -> str:
    """Simple self-contained HTML export of the plan."""
    md = render_markdown(plan)
    # light markdown-to-html: headers, bold, lists, blockquotes
    out: list[str] = []
    in_list = False
    for raw in md.splitlines():
        line = raw.strip()
        if line.startswith("### "):
            if in_list:
                out.append("</ul>"); in_list = False
            out.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("## "):
            if in_list:
                out.append("</ul>"); in_list = False
            out.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("# "):
            if in_list:
                out.append("</ul>"); in_list = False
            out.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("- ") or line.startswith("* "):
            if not in_list:
                out.append("<ul>"); in_list = True
            body = html.escape(line[2:])
            body = body.replace("&lt;strong&gt;", "<strong>")
            out.append(f"<li>{body}</li>")
        elif line.startswith("> "):
            if in_list:
                out.append("</ul>"); in_list = False
            out.append(f"<blockquote>{html.escape(line[2:])}</blockquote>")
        elif line == "---":
            if in_list:
                out.append("</ul>"); in_list = False
            out.append("<hr>")
        elif line == "":
            if in_list:
                out.append("</ul>"); in_list = False
        else:
            if in_list:
                out.append("</ul>"); in_list = False
            # inline **bold**
            esc = html.escape(line)
            while "**" in esc:
                esc = esc.replace("**", "<strong>", 1).replace("**", "</strong>", 1)
            out.append(f"<p>{esc}</p>")
    if in_list:
        out.append("</ul>")
    body = "\n".join(out)
    title = html.escape(f"30-60-90 Day Plan: {plan['role']} @ {plan['company']}")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 820px; margin: 2rem auto;
       padding: 0 1rem; line-height: 1.55; color: #1a1a1a; }}
h1 {{ border-bottom: 2px solid #333; padding-bottom: .4rem; }}
h2 {{ color: #444; margin-top: 2rem; }}
blockquote {{ border-left: 4px solid #888; margin-left: 0; padding-left: 1rem;
              color: #555; font-style: italic; }}
li {{ margin: .3rem 0; }}
</style></head><body>
{body}
</body></html>
"""


def export(plan_id: int, format: str = "md",
           path: str | Path | None = None) -> Path:
    """Export a plan to Markdown or HTML. Returns the written path."""
    if format not in ("md", "html"):
        raise PlanError(f"Unknown export format {format!r}. Use md or html.")
    plan = get_plan(plan_id, path)
    C.ensure_data_dirs()
    C.PLAN_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = C.PLAN_EXPORTS_DIR / f"plan-{plan_id}.{format}"
    content = render_markdown(plan) if format == "md" else _render_html(plan)
    dest.write_text(content, encoding="utf-8")
    return dest

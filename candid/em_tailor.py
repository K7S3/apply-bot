"""EM resume reframe: surface management-scope signals for EM applications.

Reads the stored profile and extracts only scope signals that are actually
present in it (team size, org size, hiring, mentoring, cross-team impact,
delivery/process ownership), then reframes the resume around them for
Engineering Manager applications.

Hard rule (shared with tailor.py): NEVER invents metrics, scope numbers, or
experience. A signal that is not in the profile is flagged as a gap
("team size not stated") - never filled in, never guessed.

Usage:
    python -m candid em reframe
    python -m candid em reframe --json
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# scope-signal extraction
# ---------------------------------------------------------------------------
# Each entry: (kind, compiled regex, value_group).
# value_group is the regex group holding the headcount, or None for a
# qualitative signal (presence only, no number claimed).
_SCOPE_PATTERNS: list[tuple[str, "re.Pattern[str]", int | None]] = [
    ("team_size", re.compile(
        r"team of\s+(\d+)\s*(?:\+)?", re.I), 1),
    ("team_size", re.compile(
        r"(\d+)\s*[-–]\s*(?:person|member)[-–\s]*team", re.I), 1),
    ("team_size", re.compile(
        r"(?:led|managed|managing|leading|oversaw|supervised?)\s+"
        r"(?:a\s+)?(?:team of\s+)?(\d+)\s*(?:\+)?\s*"
        r"(?:engineers?|developers?|people|reports?|members?|staff|employees|scientists|analysts)",
        re.I), 1),
    ("team_size", re.compile(r"(\d+)\s+direct reports?", re.I), 1),
    ("org_size", re.compile(
        r"\borg(?:aniz|anis)ation\s+of\s+(\d+)", re.I), 1),
    ("org_size", re.compile(r"(\d+)\s*[-–]?\s*person\s+org(?:aniz|anis)ation?", re.I), 1),
    ("hiring", re.compile(r"grew\s+(?:the\s+)?team\s+from\s+(\d+)\s+to\s+(\d+)", re.I), 2),
    ("hiring", re.compile(r"hir(?:ed|ing)\s+(\d+)", re.I), 1),
    ("hiring", re.compile(r"interview(?:ed|ing)?\s+(\d+)\s+candidates?", re.I), 1),
    ("hiring", re.compile(
        r"\b(recruit(?:ed|ing|er)?|hiring manager|hiring bar|hiring plan|headcount)\b",
        re.I), None),
    ("mentoring", re.compile(r"mentor(?:ed|ing|s)?\s+(\d+)", re.I), 1),
    ("mentoring", re.compile(r"\b(coached|onboarded)\b", re.I), None),
    ("cross_team", re.compile(r"(\d+)\s+(?:product\s+|engineering\s+)?teams?", re.I), 1),
    ("cross_team", re.compile(
        r"\b(cross[- ]functional|partner(?:ed|ing|s)? with|stakeholders?|"
        r"alignment|tech leads?)\b", re.I), None),
    ("delivery", re.compile(
        r"\b(roadmap|okrs?|sprint planning|prioritiz\w+|performance reviews?|"
        r"1:1s?|promotion(?:s| packet| case)?|capacity planning|headcount|"
        r"retrospective|attrition|retention)\b", re.I), None),
]


def _snippet(text: str, m: "re.Match[str]", width: int = 110) -> str:
    start = max(0, m.start() - 20)
    end = min(len(text), m.end() + 20)
    # expand to word boundaries so quotes don't start/end mid-word
    if start > 0:
        ws = text.find(" ", start, m.start())
        start = ws + 1 if ws != -1 else m.start()
    if end < len(text):
        we = text.find(" ", end)
        end = we if we != -1 else len(text)
    s = re.sub(r"\s+", " ", text[start:end]).strip()
    if start > 0:
        s = "..." + s
    if end < len(text):
        s = s + "..."
    return s[:width]


def extract_scope_signals(profile: dict) -> list[dict]:
    """Pull management-scope signals from profile text.

    Scans headline, summary, and each experience entry (title + bullets).
    Every signal carries its exact source quote - nothing is inferred.
    Returns a list of {"kind", "value" (int|None), "text", "role"}.
    """
    chunks: list[tuple[str, str]] = []
    headline = profile.get("headline") or ""
    summary = profile.get("summary") or ""
    if headline or summary:
        chunks.append(("profile header", f"{headline} {summary}"))
    for e in profile.get("experience", []) or []:
        label = e.get("company") or e.get("title") or "role"
        text = " ".join(b for b in [e.get("title") or ""]
                        + list(e.get("bullets") or []) if b)
        if text.strip():
            chunks.append((label, text))

    signals: list[dict] = []
    for role, text in chunks:
        # one signal per (kind, value) per text chunk - "led a team of 8"
        # matches two team-size patterns but is a single fact
        chunk_seen: set[tuple[str, int | None]] = set()
        for kind, rx, group in _SCOPE_PATTERNS:
            for m in rx.finditer(text):
                value = int(m.group(group)) if group else None
                key = (kind, value)
                if key in chunk_seen:
                    continue
                chunk_seen.add(key)
                signals.append({
                    "kind": kind, "value": value,
                    "text": _snippet(text, m), "role": role,
                })
    return signals


def scope_facts(signals: list[dict]) -> dict:
    """Aggregate the extracted signals into plain facts (no inference)."""
    def vals(kind: str) -> list[int]:
        return sorted({s["value"] for s in signals
                       if s["kind"] == kind and s["value"] is not None})

    team = vals("team_size")
    return {
        "team_sizes": team,
        "max_team_size": max(team) if team else None,
        "org_sizes": vals("org_size"),
        "hiring": vals("hiring"),
        "mentoring": vals("mentoring"),
        "cross_team_sizes": vals("cross_team"),
        "has_cross_team_signal": any(s["kind"] == "cross_team" for s in signals),
        "has_delivery_signal": any(s["kind"] == "delivery" for s in signals),
        "n_signals": len(signals),
    }


# ---------------------------------------------------------------------------
# gap flags (missing scope info, stated honestly)
# ---------------------------------------------------------------------------

def missing_scope_flags(profile: dict, signals: list[dict]) -> list[str]:
    """Honest list of scope info the profile does NOT state.

    Never invents the missing numbers - each flag names the gap and what to
    add (if true).
    """
    facts = scope_facts(signals)
    gaps: list[str] = []
    if not facts["team_sizes"]:
        gaps.append("Team size: not stated anywhere in the profile - add "
                    "'team of N' (or 'N direct reports') to each role where "
                    "you led people.")
    if not facts["hiring"]:
        gaps.append("Hiring: no hiring or recruiting signal found - add "
                    "'hired N' / 'interviewed N candidates' / 'grew team from "
                    "N to M' where true.")
    if not facts["mentoring"]:
        gaps.append("Mentoring: no mentoring or coaching signal found - add "
                    "'mentored N engineers' where true.")
    if not facts["has_cross_team_signal"]:
        gaps.append("Cross-team impact: not evident - name the partner teams "
                    "and the alignment or delivery you drove across them.")
    if not facts["has_delivery_signal"]:
        gaps.append("Delivery ownership: no roadmap / planning / prioritization "
                    "signal found - EM readers look for who set direction, "
                    "not just who shipped.")
    titles = " ".join((e.get("title") or "")
                      for e in profile.get("experience", []) or []).lower()
    if not re.search(r"\b(manager|director|lead|head of|vp|chief)\b", titles):
        gaps.append("Track signal: your titles read as an individual-"
                    "contributor track. This reframe highlights "
                    "leadership-adjacent scope (mentoring, tech-lead work, "
                    "cross-team delivery) rather than claiming management "
                    "experience you do not state.")
    return gaps


# ---------------------------------------------------------------------------
# EM-relevance scoring for bullet promotion
# ---------------------------------------------------------------------------

_EM_KEYWORDS = [
    "led", "lead", "managed", "manager", "hired", "hire", "hiring",
    "recruit", "interviewed", "mentor", "coach", "onboard",
    "roadmap", "prioritiz", "stakeholder", "cross-functional",
    "cross-team", "alignment", "strategy", "vision", "okr",
    "sprint", "agile", "delivery", "performance review", "1:1",
    "promotion", "headcount", "org", "team", "executive",
    "capacity", "incident", "on-call", "retrospective", "culture",
    "retention", "attrition", "tech lead", "grew the team",
]


def em_bullet_score(bullet: str) -> int:
    """Leadership-relevance score for one bullet (relative ranking only)."""
    low = bullet.lower()
    score = sum(1 for k in _EM_KEYWORDS if k in low)
    if re.search(r"\d", bullet):
        score += 2  # numbers read as scope evidence
    return score


def _promote_bullets(bullets: list[str], n: int = 3) -> list[str]:
    scored = sorted(((em_bullet_score(b), i, b)
                     for i, b in enumerate(bullets)), reverse=True)
    return [b for _, _, b in scored[:n]]


def _role_gaps(role_signals: list[dict]) -> list[str]:
    kinds = {s["kind"] for s in role_signals}
    gaps = []
    if "team_size" not in kinds:
        gaps.append("team size not stated for this role")
    if "hiring" not in kinds:
        gaps.append("hiring not evidenced for this role")
    return gaps


# ---------------------------------------------------------------------------
# the reframe
# ---------------------------------------------------------------------------

def build_reframe(profile: dict) -> dict:
    """Build the EM reframe. Everything is drawn from the profile.

    Returns a JSON-serializable dict with scope signals (each with its
    source quote), per-role reframes, gap flags, and a summary draft.
    """
    signals = extract_scope_signals(profile)
    facts = scope_facts(signals)
    gaps = missing_scope_flags(profile, signals)

    roles = []
    for e in profile.get("experience", []) or []:
        label = e.get("company") or e.get("title") or "role"
        role_signals = [s for s in signals if s["role"] == label]
        bullets = list(e.get("bullets", []) or [])
        roles.append({
            "title": e.get("title", ""),
            "company": e.get("company", ""),
            "dates": e.get("dates", ""),
            "scope": role_signals,
            "promoted_bullets": _promote_bullets(bullets),
            "gaps": _role_gaps(role_signals),
        })

    name = profile.get("name") or "Candidate"
    headline = profile.get("headline") or ""
    years = profile.get("years_experience", 0)
    bits = [f"{name}: {headline} ({years} yrs) reframed for EM roles."]
    if facts["max_team_size"] is not None:
        bits.append(f"Scope on record: led teams of up to "
                    f"{facts['max_team_size']}.")
    if facts["hiring"]:
        bits.append("Hiring stated: " +
                    ", ".join(str(v) for v in facts["hiring"]) +
                    " (see source quotes).")
    if facts["mentoring"]:
        bits.append("Mentoring stated: " +
                    ", ".join(str(v) for v in facts["mentoring"]) +
                    " engineers.")
    if facts["has_cross_team_signal"]:
        bits.append("Cross-team delivery signal present.")
    if facts["has_delivery_signal"]:
        bits.append("Delivery/planning ownership signal present.")
    if not signals:
        bits.append("No management-scope signals (team size, hiring, "
                    "mentoring, cross-team impact) were found in the "
                    "profile - the gaps below list exactly what is missing. "
                    "Nothing here is inferred.")
    elif gaps:
        bits.append(f"{len(gaps)} scope gap(s) flagged below - fill them in "
                    "from your real history, do not invent numbers.")
    summary = " ".join(bits)

    return {
        "name": name,
        "scope_signals": signals,
        "scope_facts": facts,
        "gaps": gaps,
        "roles": roles,
        "summary": summary,
    }


def _fmt_signal(s: dict) -> str:
    val = f": {s['value']}" if s["value"] is not None else ""
    return f"  - {s['kind']}{val} -- \"{s['text']}\" [{s['role']}]"


def render_reframe(result: dict) -> str:
    """Render the reframe as human-readable text."""
    facts = result["scope_facts"]
    lines = [
        f"EM REFRAME - {result['name']}",
        "",
        f"SCOPE SIGNALS FOUND ({facts['n_signals']})",
    ]
    if result["scope_signals"]:
        lines += [_fmt_signal(s) for s in result["scope_signals"]]
    else:
        lines.append("  (none - every scope dimension below is a gap)")
    lines += ["", f"WHAT IS MISSING ({len(result['gaps'])} gaps)"]
    if result["gaps"]:
        lines += [f"  - {g}" for g in result["gaps"]]
    else:
        lines.append("  (none - strong scope coverage)")
    lines += ["", "ROLE-BY-ROLE REFRAME"]
    for r in result["roles"]:
        header = " - ".join(b for b in [r["title"], r["company"]] if b)
        if r["dates"]:
            header += f" | {r['dates']}"
        lines.append("")
        lines.append(header or "(untitled role)")
        scope_bits = []
        if r["scope"]:
            for s in r["scope"]:
                v = f" {s['value']}" if s["value"] is not None else ""
                scope_bits.append(f"{s['kind']}{v}")
        lines.append("  Scope on record: " +
                     (", ".join(scope_bits) if scope_bits else "none stated"))
        lines.append("  Promoted for EM readers:")
        for b in r["promoted_bullets"]:
            lines.append(f"    - {b}")
        if r["gaps"]:
            lines.append("  Gaps: " + "; ".join(r["gaps"]))
    lines += ["", "EM SUMMARY DRAFT", result["summary"], ""]
    return "\n".join(lines)

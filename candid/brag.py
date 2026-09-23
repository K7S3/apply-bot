"""Performance-review brag sheet from the wins ledger.

Turns logged wins into Markdown grouped by competency, with quantified
impacts inline and peer quotes blockquoted. Also reports competency
coverage and competency gaps against a job description.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from candid import config as C
from candid import match as M
from candid.wins import list_wins, load_wins, COMPETENCIES

# competency -> skill keywords used to find that competency in a JD.
# Keywords are matched with config.skill_regex (word-boundary aware), the
# same matching primitive match.py's skill extraction uses.
COMPETENCY_SKILLS: dict[str, list[str]] = {
    "leadership": ["leadership", "team lead", "strategy", "roadmap"],
    "ownership": ["ownership", "initiative", "drove", "led the effort",
                  "end-to-end"],
    "communication": ["communication", "presentation", "documentation"],
    "system-design": ["system design", "architecture", "distributed systems",
                      "scalability"],
    "coding": ["coding", "programming", "code review", "software engineering"],
    "debugging": ["debugging", "root cause", "troubleshoot"],
    "data-analysis": ["data analysis", "analytics", "sql", "metrics",
                      "etl", "airflow", "pipeline", "pipelines"],
    "experimentation": ["experimentation", "experiment", "a/b test",
                        "causal inference"],
    "ml-modeling": ["machine learning", "pytorch", "tensorflow", "scikit-learn",
                    "modeling", "deep learning", "llm", "ml"],
    "product-sense": ["product sense", "product judgment", "prioritization",
                      "user empathy"],
    "stakeholder-management": ["stakeholder", "cross-functional", "partnership",
                               "alignment"],
    "mentoring": ["mentorship", "mentor", "coaching", "onboarding"],
    "project-management": ["project management", "planning", "estimation",
                           "delivery", "deadline"],
    "incident-response": ["incident", "on-call", "outage", "reliability",
                          "slo"],
    "technical-writing": ["technical writing", "design doc", "rfc",
                          "documentation"],
    "collaboration": ["collaboration", "teamwork", "partnership"],
    "strategic-thinking": ["strategy", "strategic", "long-term"],
    "customer-focus": ["customer", "user impact", "customer obsession"],
}


def _wins(wins: list[dict] | None) -> list[dict]:
    return list_wins(wins) if wins is None else list(wins)


def _fmt_impact(impact: dict) -> str:
    metric = impact.get("metric", "impact")
    before, after = impact.get("before"), impact.get("after")
    unit = f" {impact['unit']}" if impact.get("unit") else ""
    if before is not None and after is not None:
        return f"{metric}: {before} -> {after}{unit}"
    if after is not None:
        return f"{metric}: {after}{unit}"
    return metric


def _win_block(win: Win) -> str:
    """Markdown for a single win: title, description, impacts, STAR, quotes."""
    lines = [f"### {win.get("title") or "Untitled win"}"]
    meta = " · ".join(p for p in (win.get("date"), win.get("role")) if p)
    if meta:
        lines.append(f"*{meta}*")
    lines.append("")
    if win.get("description"):
        lines.append(win["description"])
        lines.append("")
    if win.get("impacts"):
        lines.append("**Impact:** " + "; ".join(
            _fmt_impact(i) for i in win["impacts"]))
        lines.append("")
    star = win.get("star") or {}
    star_parts = []
    for key in ("situation", "task", "action", "result"):
        if star.get(key):
            star_parts.append(f"**{key.title()}:** {star[key]}")
    if star_parts:
        lines.extend(star_parts)
        lines.append("")
    for q in (win.get("quotes") or ()):
        text = q.get("text", "").strip()
        if not text:
            continue
        author = q.get("author", "")
        source = q.get("source", "")
        attr = " - " + ", ".join(p for p in (author, source) if p) if (
            author or source) else ""
        lines.append(f"> {text}{attr}")
    if win.get("quotes"):
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def brag_sheet(wins: list[dict] | None = None, *, since: str | None = None,
               until: str | None = None, title: str = "Brag sheet") -> str:
    """Render wins as Markdown grouped by competency.

    Date range shown in the header; each win appears under every competency
    it is tagged with. Quantified impacts are inline; peer quotes are
    blockquoted with attribution.
    """
    all_wins = _wins(wins)
    kept = [w for w in all_wins
            if (not since or (w.get("date") or "") >= since)
            and (not until or (w.get("date") or "") <= until)]
    kept.sort(key=lambda w: (w.get("date") or "", w.get("title") or ""))

    if since or until:
        period = f"{since or 'start'} to {until or date.today().isoformat()}"
    else:
        period = "all time"

    lines = [f"# {title}", "", f"_Performance highlights: {period}_", ""]
    total = len(kept)
    lines.append(f"{total} win{'s' if total != 1 else ''} logged.")
    lines.append("")

    for comp in COMPETENCIES:
        comp_wins = [w for w in kept if comp in (w.get("competencies") or ())]
        label = comp.replace("-", " ").title()
        lines.append(f"## {label} ({len(comp_wins)})")
        lines.append("")
        if not comp_wins:
            lines.append("_No wins logged yet._")
            lines.append("")
            continue
        for w in comp_wins:
            lines.append(_win_block(w))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def export_brag_sheet(path: str | Path, **kwargs) -> Path:
    """Write the brag sheet Markdown to path. Returns the path."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(brag_sheet(**kwargs))
    return out


def competency_coverage(wins: list[dict] | None = None) -> dict[str, int]:
    """Competency -> number of wins tagged with it. Seeded competencies
    with no wins are included at 0."""
    counts = {c: 0 for c in COMPETENCIES}
    for w in _wins(wins):
        for c in (w.get("competencies") or ()):
            counts[c] = counts.get(c, 0) + 1
    return counts


def _competencies_in_jd(jd_text: str) -> dict[str, list[str]]:
    """Competency -> the subset of its skill keywords found in the JD.

    Reuses match.py's extraction (lexicon scan, quoted phrases, tech
    tokens) so JD skill coverage mirrors candid match scoring, then maps
    COMPETENCY_SKILLS keywords to canonical extracted skills. Keywords
    with no lexicon hit are matched directly against the JD text with
    config.skill_regex word boundaries.
    """
    jd = jd_text or ""
    try:
        extracted = M._extract_jd(jd)["items"]
    except Exception:
        extracted = {}
    canon: set[str] = set(extracted)
    alias_hit: dict[str, str] = {}
    for name, info in extracted.items():
        for a in info.get("aliases") or [name]:
            alias_hit.setdefault(a.lower(), name)

    found: dict[str, list[str]] = {}
    for comp, keywords in COMPETENCY_SKILLS.items():
        hits: list[str] = []
        for kw in keywords:
            lowered = kw.lower()
            if lowered in canon or lowered in alias_hit:
                hits.append(kw)
            elif C.skill_regex(kw).search(jd.lower()):
                hits.append(kw)
        if hits:
            found[comp] = hits
    return found


def competency_gap(jd_text: str, wins: list[dict] | None = None) -> dict:
    """Compare JD-requested competencies against wins logged.

    A competency is "covered" if one of its skill keywords appears in the
    JD AND the user has at least one win tagged with it; "missing" if the
    skill appears in the JD but no win is tagged with it.
    """
    tagged = {c for w in _wins(wins) for c in (w.get("competencies") or ())}
    in_jd = _competencies_in_jd(jd_text)
    covered = sorted(c for c in in_jd if c in tagged)
    missing = sorted(c for c in in_jd if c not in tagged)
    denom = len(covered) + len(missing)
    coverage_pct = round(100.0 * len(covered) / denom, 1) if denom else 0.0
    return {"covered": covered, "missing": missing,
            "coverage_pct": coverage_pct}

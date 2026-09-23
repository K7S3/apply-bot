"""Promotion path planner: readiness checklists, an evidence bank, gap
analysis, timeline estimates, and promo-packet outline building.

Level data comes from candid.leveling (candid/data/leveling.json). Your
own wins are stored as "evidence" in candid_data/promo_evidence.json
(git-ignored); generated packet outlines go to candid_data/promo_packets/.

Public API:
    add_evidence / list_evidence / remove_evidence   the evidence bank
    coverage(profile, criteria, evidence)            keyword coverage per criterion
    checklist(profile, company, current, target)     readiness checklist + verdict
    gaps(profile, company, target)                   uncovered criteria + suggestions
    timeline(profile, company, target, ...)          months-to-ready estimate
    rubric_rows(company, current, target)            side-by-side scope rows
    build_packet(profile, company, target, ...)      markdown outline (writes file)
    render_*()                                       text renderers for the CLI

Matching is keyword-based and deterministic: a promo criterion is
"covered" when an evidence item matches it (>= 1 shared keyword) and
"partially covered" when a resume bullet matches it (>= 2 shared
keywords). The CLI hook is `python -m candid promo <subcommand>`.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from candid import config as C
from candid import leveling as L

PACKET_VERSION = 1


class PromoError(Exception):
    """Expected promotion-planner failure (bad evidence, missing profile)."""


STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "at", "for", "with",
    "on", "by", "from", "as", "is", "are", "was", "were", "be", "been",
    "your", "you", "their", "they", "them", "its", "it", "this", "that",
    "these", "those", "not", "but", "so", "such", "than", "too", "very",
    "own", "over", "under", "up", "out", "about", "into", "through",
    "more", "most", "other", "some", "any", "each", "both", "who", "whom",
    "what", "which", "when", "how", "why", "can", "will", "would", "should",
    "has", "have", "had", "do", "does", "did", "i", "me", "my", "we", "our",
    "he", "she", "his", "her", "across", "within", "per",
}


def criterion_keywords(criterion: str) -> list[str]:
    """Significant lowercase words from a criterion, order-preserved, deduped."""
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9+\-]*", criterion.lower())
    out, seen = [], set()
    for w in words:
        w = w.strip("+-")
        if len(w) < 3 or w in STOPWORDS or w in seen:
            continue
        seen.add(w)
        out.append(w)
    return out


def criterion_tag(criterion: str) -> str:
    """Short copy-paste tag for --criterion (first 4 keywords)."""
    return "-".join(criterion_keywords(criterion)[:4]) or "general"


def _hits(text: str, keywords: list[str]) -> list[str]:
    low = f" {text.lower()} "
    return [k for k in keywords if k.lower() in low]


# ---------------------------------------------------------------------------
# evidence bank
# ---------------------------------------------------------------------------

def _load_evidence(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else C.PROMO_EVIDENCE_PATH
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PromoError(f"Evidence file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise PromoError(f"Evidence file {p} should contain a JSON list.")
    return data


def _save_evidence(items: list[dict], path: str | Path | None = None) -> Path:
    p = Path(path) if path else C.PROMO_EVIDENCE_PATH
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items, indent=2), encoding="utf-8")
    return p


def add_evidence(text: str, *, company: str = "", level: str = "",
                 criterion: str = "", date_str: str = "",
                 path: str | Path | None = None) -> dict:
    """Store one evidence item (a win, launch, or scope story)."""
    text = (text or "").strip()
    if not text:
        raise PromoError("Evidence text is required.")
    items = _load_evidence(path)
    entry = {
        "id": max((i.get("id", 0) for i in items), default=0) + 1,
        "date": date_str or date.today().isoformat(),
        "company": company.strip(),
        "level": level.strip(),
        "criterion": criterion.strip(),
        "text": text,
    }
    items.append(entry)
    _save_evidence(items, path)
    return entry


def list_evidence(company: str = "", path: str | Path | None = None) -> list[dict]:
    items = _load_evidence(path)
    if company:
        want = company.strip().lower()
        items = [i for i in items if (i.get("company") or "").lower() == want]
    return items


def remove_evidence(item_id: int, path: str | Path | None = None) -> dict:
    items = _load_evidence(path)
    for i, entry in enumerate(items):
        if entry.get("id") == item_id:
            removed = items.pop(i)
            _save_evidence(items, path)
            return removed
    raise PromoError(f"No evidence item with id {item_id}.")


# ---------------------------------------------------------------------------
# coverage
# ---------------------------------------------------------------------------

def profile_bullets(profile: dict | None) -> list[str]:
    """All resume bullets from a profile, newest experience first."""
    if not profile:
        return []
    bullets = []
    for exp in profile.get("experience", []) or []:
        for b in exp.get("bullets", []) or []:
            if b and b.strip():
                bullets.append(b.strip())
    return bullets


def coverage(profile: dict | None, criteria: list[str],
             evidence: list[dict] | None = None) -> list[dict]:
    """Per-criterion coverage: evidence hit -> 1.0, bullet hit -> 0.6, else 0.

    evidence_hits: items sharing >= 1 keyword with the criterion (or tagged
    with a tag whose keywords overlap the criterion).
    bullet_hits: profile bullets sharing >= 2 keywords with the criterion.
    """
    evidence = evidence or []
    bullets = profile_bullets(profile)
    out = []
    for crit in criteria:
        kw = criterion_keywords(crit)
        ev_hits = []
        for ev in evidence:
            # Evidence is often tagged with the hyphen-joined tag produced by
            # criterion_tag() (the CLI prints tags in gap suggestions), so
            # expand hyphens back into words before keyword matching.
            tag_kw = criterion_keywords((ev.get("criterion") or "").replace("-", " "))
            shared = set(tag_kw) & set(kw)
            if shared or _hits(ev.get("text", ""), kw):
                ev_hits.append(ev)
        b_hits = [b for b in bullets if len(_hits(b, kw)) >= 2]
        score = 1.0 if ev_hits else (0.6 if b_hits else 0.0)
        out.append({
            "criterion": crit,
            "tag": criterion_tag(crit),
            "keywords": kw,
            "score": score,
            "evidence_hits": ev_hits,
            "bullet_hits": b_hits,
        })
    return out


def _typical_low_years(level: dict) -> float | None:
    raw = str(level.get("typical_years", "") or "")
    m = re.match(r"\s*(\d+(?:\.\d+)?)", raw)
    return float(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# checklist / gaps / timeline / rubric
# ---------------------------------------------------------------------------

def checklist(profile: dict | None, company: str, current: str,
              target: str, evidence: list[dict] | None = None) -> dict:
    """Readiness checklist for a promotion: current -> target.

    Items are done / partial / todo. The verdict is one of:
    "ready" (all done), "close" (no todos), "building" (todos remain).
    """
    cur = L.normalize_level(company, current)
    tgt = L.normalize_level(company, target)
    co = L.get_guide(company)
    ev = evidence if evidence is not None else list_evidence()
    cov = coverage(profile, tgt.get("promo_criteria", []), ev)
    items = []

    years = (profile or {}).get("years_experience")
    low = _typical_low_years(tgt)
    if years is None or low is None:
        items.append({"item": "Experience vs typical bar "
                              f"({tgt['code']}: ~{tgt.get('typical_years', '?')} yrs)",
                      "status": "partial",
                      "detail": "Years of experience unknown; onboard a resume so "
                                "candid can compare."})
    elif years >= low:
        items.append({"item": f"Experience: {years:g} yrs vs ~{low:g}+ typical",
                      "status": "done", "detail": "Meets the typical experience bar."})
    elif years >= low - 2:
        items.append({"item": f"Experience: {years:g} yrs vs ~{low:g}+ typical",
                      "status": "partial",
                      "detail": "Close; tenure alone rarely decides, but plan for it."})
    else:
        items.append({"item": f"Experience: {years:g} yrs vs ~{low:g}+ typical",
                      "status": "todo",
                      "detail": "Below the typical bar; expect a longer runway."})

    for c in cov:
        status = "done" if c["score"] >= 1.0 else ("partial" if c["score"] > 0 else "todo")
        detail = (f"{len(c['evidence_hits'])} evidence item(s)" if c["evidence_hits"]
                  else (f"{len(c['bullet_hits'])} resume bullet(s) mention this"
                        if c["bullet_hits"] else "Nothing recorded yet"))
        items.append({"item": f"Criterion: {c['criterion']}", "status": status,
                      "detail": detail, "tag": c["tag"]})

    statuses = [i["status"] for i in items]
    verdict = ("ready" if all(s == "done" for s in statuses)
               else "close" if "todo" not in statuses else "building")
    return {
        "company": co.get("name"), "current": cur["code"], "target": tgt["code"],
        "items": items, "verdict": verdict,
    }


def gaps(profile: dict | None, company: str, target: str,
         evidence: list[dict] | None = None) -> dict:
    """Uncovered / partially covered promo criteria with next actions."""
    tgt = L.normalize_level(company, target)
    co = L.get_guide(company)
    ev = evidence if evidence is not None else list_evidence()
    cov = coverage(profile, tgt.get("promo_criteria", []), ev)
    out = []
    for c in cov:
        if c["score"] >= 1.0:
            continue
        suggestion = (
            f"No solid evidence for: '{c['criterion']}'. "
            "Capture a win: what shipped, what was the scope, who felt the impact, "
            "what would have happened without you? Then run:\n"
            f"  python -m candid promo evidence add --company {L.normalize_company(company)} "
            f"--criterion \"{c['tag']}\" --text \"...\"")
        if c["bullet_hits"]:
            suggestion = (
                f"Partially covered by resume bullets, but no banked evidence for: "
                f"'{c['criterion']}'. Turn the strongest bullet into a scoped win:\n"
                f"  python -m candid promo evidence add --company {L.normalize_company(company)} "
                f"--criterion \"{c['tag']}\" --text \"...\"")
        out.append({"criterion": c["criterion"], "tag": c["tag"],
                    "score": c["score"], "suggestion": suggestion})
    return {"company": co.get("name"), "target": tgt["code"], "gaps": out,
            "covered": sum(1 for c in cov if c["score"] >= 1.0),
            "total": len(cov)}


def timeline(profile: dict | None, company: str, target: str,
             current: str = "", months_at_level: int | None = None,
             evidence: list[dict] | None = None) -> dict:
    """Deterministic months-to-ready estimate.

    Base = the typical months for the current level (or the target's typical
    experience lower bound when the current level is unknown). Coverage of the
    target's promo criteria moves the estimate: >= 80% covered shortens it,
    < 40% lengthens it. This is a planning heuristic, not a promise.
    """
    tgt = L.normalize_level(company, target)
    co = L.get_guide(company)
    cur = L.normalize_level(company, current) if current else None
    ev = evidence if evidence is not None else list_evidence()
    cov = coverage(profile, tgt.get("promo_criteria", []), ev)
    covered_frac = (sum(c["score"] for c in cov) / len(cov)) if cov else 0.0

    base = (cur or {}).get("typical_months_to_next")
    notes = []
    if base is None:
        low = _typical_low_years(tgt)
        base = int(low * 12) if low else 24
        notes.append("Current level unknown; using the target's typical experience "
                     "as the base.")
    else:
        notes.append(f"Base: ~{base} months typical in {cur['code']} before promotion.")
    if months_at_level is not None:
        notes.append(f"You reported {months_at_level} months at this level.")
        if months_at_level >= base:
            notes.append("Tenure requirement likely met; the case now rests on "
                         "scope evidence.")

    adjust = 0
    if covered_frac >= 0.8:
        adjust = -6
        notes.append(f"Strong coverage ({covered_frac:.0%}): evidence may pull "
                     "the timeline in.")
    elif covered_frac < 0.4:
        adjust = 6
        notes.append(f"Thin coverage ({covered_frac:.0%}): expect to spend time "
                     "building scope evidence.")
    est = max(1, base + adjust)
    low_m, high_m = max(1, est - 3), est + 6
    focus = [c["criterion"] for c in cov if c["score"] < 1.0][:3]
    return {
        "company": co.get("name"), "target": tgt["code"],
        "low_months": low_m, "high_months": high_m,
        "coverage": round(covered_frac, 2), "focus": focus, "notes": notes,
    }


def rubric_rows(company: str, current: str, target: str) -> dict:
    """Side-by-side scope rows for two levels."""
    cur = L.normalize_level(company, current)
    tgt = L.normalize_level(company, target)
    co = get_guide_name(company)
    return {"company": co, "current": cur, "target": tgt}


def get_guide_name(company: str) -> str:
    return L.get_guide(company).get("name", company)


# ---------------------------------------------------------------------------
# packet builder
# ---------------------------------------------------------------------------

def _default_packet_path(company: str, target: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-")
    return C.PROMO_PACKETS_DIR / f"{slug}_{target.lower()}_{date.today().isoformat()}.md"


def build_packet(profile: dict | None, company: str, target: str,
                 current: str = "", evidence: list[dict] | None = None,
                 out: str | Path | None = None) -> tuple[str, Path]:
    """Build a promo-packet outline as markdown and write it to a file.

    Returns (markdown, path). Evidence is mapped onto the target level's
    promo criteria; gaps become the growth-areas section. Never invents
    accomplishments: sections the data cannot fill stay as templates.
    """
    tgt = L.normalize_level(company, target)
    co = L.get_guide(company)
    ev = evidence if evidence is not None else list_evidence()
    cov = coverage(profile, tgt.get("promo_criteria", []), ev)
    prof = profile or {}
    name = prof.get("name") or "Your Name"
    cur_label = f" (currently {current})" if current else ""
    lines = [
        f"# Promotion packet outline: {target} @ {co.get('name')}{cur_label}",
        "",
        f"Prepared {date.today().isoformat()} for {name}. "
        "Fill the bracketed prompts; this outline organizes your case, it does not write it.",
        "",
        "## 1. Snapshot",
        "",
        f"- Current level: {current or '[fill in]'}",
        f"- Target level: {tgt['code']} - {tgt.get('title', '')}",
        f"- Typical experience at target: ~{tgt.get('typical_years', '?')} years",
        f"- Evidence items banked: {len(ev)}",
        "",
        "## 2. Executive summary",
        "",
        "[2-3 sentences: who you are, the scope you operate at today, and why "
        "the next level is the right frame for your impact.]",
        "",
        "## 3. Scope at the target level",
        "",
        "What reviewers will compare you against:",
        "",
    ]
    for b in tgt.get("scope", []):
        lines.append(f"- {b}")
    lines += ["", "## 4. Accomplishments mapped to promotion criteria", "",
              "| Criterion | Evidence | Status |",
              "|---|---|---|"]
    for c in cov:
        ev_text = "; ".join(e["text"][:80] for e in c["evidence_hits"][:2]) or "-"
        status = ("covered" if c["score"] >= 1.0
                  else "partial (resume only)" if c["score"] > 0 else "gap")
        crit_short = c["criterion"][:60]
        lines.append(f"| {crit_short} | {ev_text} | {status} |")
    lines += ["", "## 5. Key wins", ""]
    if ev:
        for e in ev:
            lines.append(f"- ({e.get('date', '')}) {e['text']}")
    else:
        lines.append("[No evidence banked yet. Run `python -m candid promo evidence add "
                     "--text \"...\"` for each major win.]")
        for b in profile_bullets(prof)[:5]:
            lines.append(f"- (from resume) {b}")
    lines += ["", "## 6. Growth areas", ""]
    gap_items = [c for c in cov if c["score"] < 1.0]
    if gap_items:
        for c in gap_items:
            lines.append(f"- {c['criterion']}")
    else:
        lines.append("- None outstanding against the listed criteria.")
    lines += ["",
              "## 7. Timeline",
              "",
              f"[See `python -m candid promo timeline --company "
              f"{L.normalize_company(company)} --target {tgt['code']}` for the estimate.]",
              "",
              "## 8. Endorsers to line up",
              "",
              "- [ ] Manager: aligned on the packet and the timeline",
              "- [ ] Skip-level: aware of your scope and impact",
              "- [ ] 2-3 peer endorsers who saw the work up close",
              "- [ ] 1-2 cross-functional partners (PM, partner teams)",
              "",
              "## 9. Appendix",
              "",
              "- Leveling reference: `python -m candid leveling scope --company "
              f"{L.normalize_company(company)} --level {tgt['code']}`",
              "- Readiness check: `python -m candid promo checklist --company "
              f"{L.normalize_company(company)}"
              + (f" --current {current}" if current else "") + f" --target {tgt['code']}`",
              "",
              "_Reference approximation: verify scope expectations against official "
              "leveling docs and your manager._",
              ""]
    markdown = "\n".join(lines)
    path = Path(out) if out else _default_packet_path(L.normalize_company(company),
                                                      tgt["code"])
    C.ensure_data_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return markdown, path


# ---------------------------------------------------------------------------
# renderers
# ---------------------------------------------------------------------------

_MARK = {"done": "[x]", "partial": "[~]", "todo": "[ ]"}


def render_checklist(result: dict) -> str:
    lines = [f"Promotion readiness: {result['current']} -> {result['target']} "
             f"@ {result['company']}", ""]
    for it in result["items"]:
        lines.append(f"{_MARK.get(it['status'], '[?]')} {it['item']}")
        lines.append(f"     {it['detail']}")
    verdicts = {
        "ready": "Verdict: READY - the evidence supports drafting a packet.",
        "close": "Verdict: CLOSE - no hard gaps; shore up the partial items.",
        "building": "Verdict: BUILDING - focus on the [ ] items before a packet.",
    }
    lines += ["", verdicts.get(result["verdict"], result["verdict"])]
    if result["verdict"] != "ready":
        lines.append("Next: python -m candid promo gaps "
                     f"--company {result['company']} --target {result['target']}")
    return "\n".join(lines)


def render_gaps(result: dict) -> str:
    lines = [f"Gaps vs {result['target']} @ {result['company']} "
             f"({result['covered']}/{result['total']} criteria covered)", ""]
    if not result["gaps"]:
        return "\n".join(lines + ["No gaps: every criterion has banked evidence."])
    for g in result["gaps"]:
        lines.append(f"- {g['criterion']}")
        lines.append(f"  {g['suggestion']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def render_timeline(result: dict) -> str:
    lines = [f"Timeline to {result['target']} @ {result['company']}: "
             f"~{result['low_months']}-{result['high_months']} months",
             f"Promo-criteria coverage: {result['coverage']:.0%}", ""]
    for n in result["notes"]:
        lines.append(f"- {n}")
    if result["focus"]:
        lines.append("")
        lines.append("Focus areas (weakest coverage first):")
        for f in result["focus"]:
            lines.append(f"  - {f}")
    lines.append("")
    lines.append("Heuristic only, not a promise. Scope evidence moves it most.")
    return "\n".join(lines)


def render_rubric(result: dict) -> str:
    cur, tgt = result["current"], result["target"]
    lines = [f"{result['company']}: {cur['code']} vs {tgt['code']}", "",
             f"== {cur['code']} ({cur.get('title', '')}) =="]
    for b in cur.get("scope", []):
        lines.append(f"  - {b}")
    lines += ["", f"== {tgt['code']} ({tgt.get('title', '')}) =="]
    for b in tgt.get("scope", []):
        lines.append(f"  - {b}")
    lines += ["", f"Promotion criteria to reach {tgt['code']}:"]
    for b in tgt.get("promo_criteria", []):
        lines.append(f"  - {b}")
    return "\n".join(lines)


def render_evidence_list(items: list[dict]) -> str:
    if not items:
        return ("No evidence banked yet.\n"
                "Add your first win:\n"
                "  python -m candid promo evidence add --text \"...\" "
                "--criterion \"impact\"")
    lines = [f"{len(items)} evidence item(s):", ""]
    for e in items:
        tag = f" [{e['criterion']}]" if e.get("criterion") else ""
        co = f" @ {e['company']}" if e.get("company") else ""
        lines.append(f"#{e['id']}{tag}{co} ({e.get('date', '')})")
        lines.append(f"  {e['text']}")
    return "\n".join(lines)

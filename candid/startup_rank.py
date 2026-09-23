"""Rank startup-registry companies for a target role.

combined score = match-keyword fit x stage preference x hiring signal

- match-keyword fit: share of the role's keywords found in the startup's
  registry text (name, notes, sector/keywords/description fields)
- stage preference: boost when the startup's stage is in your preferred
  stages (``startups set-stages`` writes them under ``preferred_stages``
  in candid_data/startups.json); all stages equal when none are set
- hiring signal: trend/velocity factor from startup_signals, computed from
  candid's own curated job runs; companies with no curated data score 1.0

The registry (candid_data/startups.json) is managed by startup_lists and is
read defensively: a missing or unreadable file yields no rows, not an
error. No network, no scraping.
"""

from __future__ import annotations

import re

from candid import startup_signals as SIG


class StartupRankError(Exception):
    """Raised for ranking failures (e.g. empty role)."""


#: Weights: how much each factor multiplies the score.
PREFERRED_STAGE_FACTOR = 1.25
NON_PREFERRED_STAGE_FACTOR = 0.75
_TREND_FACTOR = {"growing": 1.2, "flat": 1.0, "shrinking": 0.75}

#: Generic title words that carry no match signal.
_STOPWORDS = {
    "engineer", "engineering", "developer", "senior", "sr", "jr", "junior",
    "lead", "staff", "principal", "manager", "scientist", "analyst",
    "the", "a", "an", "and", "of", "for", "in", "on", "remote", "hybrid",
    "onsite", "entry", "mid", "level", "ii", "iii",
}

#: Registry text fields searched for role keywords.
_TEXT_FIELDS = ("name", "sector", "industry", "tags", "keywords",
                "description", "about", "focus", "domain", "notes",
                "remote_policy")


def _norm_stage(label: object) -> str | None:
    """Canonical stage label, or None when missing/unknown.

    Uses startup_lists' vocabulary (pre-seed, seed, series-a, series-b,
    series-c-plus, public) so rank agrees with the registry manager.
    """
    from candid import startup_lists as L
    if not str(label or "").strip():
        return None
    try:
        return L.normalize_stage(str(label))
    except Exception:
        return None


def _terms(text: str) -> set[str]:
    """Keyword tokens from text, minus stopwords."""
    return {t for t in re.findall(r"[a-z0-9+]+", text.lower())
            if t not in _STOPWORDS and len(t) > 1}


def _startup_text(rec: dict) -> str:
    """All registry text that describes what the startup does."""
    parts = []
    for key in _TEXT_FIELDS:
        val = rec.get(key)
        if isinstance(val, (list, tuple)):
            parts.append(" ".join(str(v) for v in val))
        elif val:
            parts.append(str(val))
    return " ".join(parts)


def load_registry() -> tuple[list[dict], list[str]]:
    """Load (startup records, preferred stages) via the registry manager.

    Defensive: a missing or unreadable startups.json yields ([], []),
    never an exception.
    """
    from candid import startup_lists as L
    try:
        records = L.list_startups()
        prefs = L.preferred_stages()
    except Exception:
        return [], []
    clean = [r for r in records if isinstance(r, dict)]
    return clean, [p for p in prefs if _norm_stage(p)]


def _stage_factor(stage: str | None, preferred: list[str]) -> float:
    if not preferred:
        return 1.0  # no preference set: all stages equal
    if not stage:
        return 1.0
    return (PREFERRED_STAGE_FACTOR if stage in preferred
            else NON_PREFERRED_STAGE_FACTOR)


def _signal_factor(sig: dict | None) -> float:
    """Trend base x velocity kicker. No curated data: 1.0 (neutral)."""
    if not sig:
        return 1.0
    base = _TREND_FACTOR.get(sig.get("trend"), 1.0)
    velocity = min(float(sig.get("postings_per_30d", 0.0) or 0.0), 5.0)
    return base * (1.0 + velocity / 10.0)


def _why(fit: float, hits: list[str], stage: str | None,
         preferred: list[str], sig: dict | None) -> str:
    bits = []
    if hits:
        bits.append(f"fit {fit:.2f} on {', '.join(hits[:4])}")
    else:
        bits.append("no keyword overlap with the role")
    if stage:
        if preferred and stage in preferred:
            bits.append(f"stage {stage} (preferred)")
        else:
            bits.append(f"stage {stage}")
    if sig:
        bits.append(f"hiring {sig['trend']}, {int(sig['postings_per_30d'])} "
                    f"posting(s) in the last {SIG.WINDOW_DAYS}d")
    else:
        bits.append("no curated hiring data yet")
    return "; ".join(bits)


def rank_startups(role: str, *, startups: list[dict] | None = None,
                  preferred_stages: list[str] | None = None,
                  signals: dict[str, dict] | None = None,
                  limit: int | None = None) -> list[dict]:
    """Rank startups for ``role``; best score first.

    Pure function: all inputs are injectable (registry + prefs + signals are
    loaded from disk only when not supplied). Raises StartupRankError when
    ``role`` is blank or has no usable keywords. Each row carries: name,
    stage, score, fit, matched_terms, stage_factor, signal_factor, trend,
    and a one-line ``why``.
    """
    if not str(role or "").strip():
        raise StartupRankError("A role is required to rank startups "
                               "(e.g. --role \"ML Engineer\").")
    if startups is None or preferred_stages is None:
        reg_startups, reg_prefs = load_registry()
        startups = reg_startups if startups is None else startups
        preferred_stages = reg_prefs if preferred_stages is None else preferred_stages
    if signals is None:
        signals = SIG.signals_by_company()

    role_terms = _terms(role)
    if not role_terms:
        raise StartupRankError(f"Role {role!r} has no usable keywords.")

    rows = []
    for rec in startups or []:
        if not isinstance(rec, dict):
            continue
        name = str(rec.get("name") or rec.get("company") or "").strip()
        if not name:
            continue
        hits = sorted(role_terms & _terms(_startup_text(rec)))
        fit = len(hits) / len(role_terms)
        stage = _norm_stage(rec.get("stage"))
        sf = _stage_factor(stage, preferred_stages)
        sig = signals.get(name.lower())
        hf = _signal_factor(sig)
        score = fit * sf * hf
        rows.append({
            "name": name,
            "stage": stage or "",
            "score": round(score, 3),
            "fit": round(fit, 3),
            "matched_terms": hits,
            "stage_factor": sf,
            "signal_factor": round(hf, 3),
            "trend": sig["trend"] if sig else "no data",
            "why": _why(fit, hits, stage, preferred_stages, sig),
        })

    rows.sort(key=lambda r: (-r["score"], r["name"].lower()))
    return rows[:limit] if limit else rows


def render_rank(rows: list[dict], role: str) -> str:
    """Human-readable ranking table with one-line reasons."""
    if not rows:
        return ("No startup registry found at candid_data/startups.json.\n"
                "Add startups first, then rank again "
                "(see `python -m candid startups --help`).")
    lines = [f"Ranked {len(rows)} startups for {role!r}:"]
    for i, r in enumerate(rows, 1):
        stage = f" ({r['stage']})" if r["stage"] else ""
        lines.append(f"{i}. {r['name']}{stage} - score {r['score']:.3f}")
        lines.append(f"   why: {r['why']}")
    return "\n".join(lines)

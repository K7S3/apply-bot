"""Switcher-friendly company signals.

Scans job descriptions (or any job-related text) for language that suggests
a company is open to career switchers: explicit mentions of career changes,
non-traditional backgrounds, apprenticeships, returnships, bootcamp grads,
and "equivalent experience" phrasing. The result is a per-company score plus
a ranking helper, so a switcher can prioritize where to apply.

Deterministic, offline, keyword-based. No network, no APIs.
"""

from __future__ import annotations

import re


class SwitchSignalsError(Exception):
    """Raised when company signal scoring gets invalid input."""


#: Signal name -> (weight, regex pattern). Weights reflect how strongly the
#: phrasing signals switcher-friendliness.
SIGNAL_PATTERNS: dict[str, tuple[int, str]] = {
    "explicit_career_change": (3, r"career[\s-]?chang(?:e|ers?)"),
    "non_traditional_background": (3, r"non[\s-]?traditional\s+backgrounds?"),
    "explicit_career_switcher": (3, r"career\s+switchers?"),
    "apprenticeship": (3, r"apprenticeships?"),
    "returnship": (3, r"returnships?"),
    "bootcamp_grad": (2, r"boot\s?camp\s+grad(?:s|uates?)?"),
    "diverse_backgrounds": (2, r"diverse\s+backgrounds?"),
    "no_degree_required": (2, r"no\s+degree\s+required"),
    "equivalent_experience": (2, r"equivalent\s+(?:work\s+)?experience"),
    "career_transition": (1, r"career\s+transitions?"),
    "welcome_all_backgrounds": (1, r"all\s+backgrounds?\s+(?:are\s+)?welcome"),
}

_COMPILED: dict[str, tuple[int, re.Pattern]] = {
    name: (weight, re.compile(pattern, re.IGNORECASE))
    for name, (weight, pattern) in SIGNAL_PATTERNS.items()
}

#: Score at or above this marks a company as switcher-friendly.
FRIENDLY_THRESHOLD = 3

#: Score contributed by a single signal is capped so one repeated phrase
#: cannot dominate; multiple distinct signals still stack.
_PER_SIGNAL_CAP = 6


def score_company_signals(job_texts: list[str]) -> dict:
    """Score one company's job texts for switcher-friendly signals.

    Args:
        job_texts: list of job description strings (or snippets) from a
            single company.

    Returns:
        {"score": int, "signals_found": {signal: hits}, "friendly": bool}.
        "hits" is the number of job texts containing that signal at least
        once. Score is the sum of weight * hits per signal, with a per-signal
        cap. friendly is True when score >= FRIENDLY_THRESHOLD.
    """
    if not isinstance(job_texts, list):
        raise SwitchSignalsError("job_texts must be a list of strings.")
    for text in job_texts:
        if not isinstance(text, str):
            raise SwitchSignalsError("job_texts must be a list of strings.")

    signals_found: dict[str, int] = {}
    score = 0
    for name, (weight, pattern) in _COMPILED.items():
        hits = sum(1 for text in job_texts if pattern.search(text))
        if hits:
            signals_found[name] = hits
            score += min(weight * hits, _PER_SIGNAL_CAP)

    return {
        "score": score,
        "signals_found": signals_found,
        "friendly": score >= FRIENDLY_THRESHOLD,
    }


def rank_companies(texts_by_company: dict[str, list[str]]) -> list[dict]:
    """Rank companies by switcher-friendliness.

    Args:
        texts_by_company: mapping of company name -> list of job texts.

    Returns:
        List of {"company", "score", "signals_found", "friendly"} dicts,
        sorted by score descending, then company name ascending for
        determinism.
    """
    if not isinstance(texts_by_company, dict):
        raise SwitchSignalsError("texts_by_company must be a dict.")
    ranked = []
    for company, texts in texts_by_company.items():
        result = score_company_signals(texts)
        ranked.append(
            {
                "company": company,
                "score": result["score"],
                "signals_found": result["signals_found"],
                "friendly": result["friendly"],
            }
        )
    ranked.sort(key=lambda r: (-r["score"], r["company"].lower()))
    return ranked

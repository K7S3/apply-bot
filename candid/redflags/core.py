"""Core engine for the JD red-flag detector.

Detectors are plain callables ``detect(text: str) -> list[Flag]`` registered
via :func:`register` (or by appending to :data:`DETECTORS`). Every detector
must work offline with no network calls and no paid APIs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Severity levels, worst first.
SEVERITIES = ("critical", "high", "medium", "low", "info")

_SEVERITY_RANK = {name: rank for rank, name in enumerate(SEVERITIES)}

#: Risk-score weights per severity.
_SEVERITY_WEIGHT = {
    "critical": 25,
    "high": 15,
    "medium": 8,
    "low": 3,
    "info": 0,
}


@dataclass
class Flag:
    """One warning sign found in a job posting."""

    flag_id: str
    """Stable machine-readable id, e.g. ``req.years_mismatch``."""

    title: str
    """Short human-readable title."""

    severity: str
    """One of :data:`SEVERITIES`."""

    category: str
    """Detector category, e.g. ``requirements`` or ``compensation``."""

    explanation: str
    """Why this is a warning sign, in plain language (2-4 sentences)."""

    evidence: list[str] = field(default_factory=list)
    """Quoted snippets from the posting that triggered the flag."""

    suggestion: str = ""
    """What the candidate can do about it (question to ask, check to run)."""

    def __post_init__(self) -> None:
        if self.severity not in _SEVERITY_RANK:
            raise ValueError(f"unknown severity: {self.severity!r}")

    def to_dict(self) -> dict:
        return {
            "id": self.flag_id,
            "title": self.title,
            "severity": self.severity,
            "category": self.category,
            "explanation": self.explanation,
            "evidence": list(self.evidence),
            "suggestion": self.suggestion,
        }


#: All registered detectors, in registration order.
DETECTORS: list = []


def register(fn):
    """Decorator registering a ``detect(text) -> list[Flag]`` detector."""
    DETECTORS.append(fn)
    return fn


def analyze(text: str) -> dict:
    """Run every registered detector over ``text``.

    Returns a dict with ``flags`` (worst severity first), ``risk_score``
    (0-100), and ``verdict`` (``clean`` / ``caution`` / ``risky``).
    """
    text = text or ""
    flags: list[Flag] = []
    for detector in DETECTORS:
        try:
            found = detector(text) or []
        except Exception:
            # A broken detector must never kill the whole analysis.
            continue
        flags.extend(found)
    flags.sort(key=lambda f: (_SEVERITY_RANK[f.severity], f.flag_id))
    score = risk_score(flags)
    if score >= 60:
        verdict = "risky"
    elif score >= 25:
        verdict = "caution"
    else:
        verdict = "clean"
    return {
        "flags": flags,
        "flags_json": [f.to_dict() for f in flags],
        "risk_score": score,
        "verdict": verdict,
    }


def risk_score(flags: list[Flag]) -> int:
    """Aggregate 0-100 risk score from a list of flags."""
    total = sum(_SEVERITY_WEIGHT.get(f.severity, 0) for f in flags)
    return min(100, total)

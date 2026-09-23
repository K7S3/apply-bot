"""Bullet metric helper: find resume bullets that deserve a number, and help the
user supply real ones without ever inventing them.

Core guarantee: every number that ends up in a rewritten bullet must come
from the user. suggest_phrasings() returns [] rather than fabricate, and
audit_no_invention() documents which metric claims are backed by user input.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone

from candid import config

# --- opportunity types --------------------------------------------------------
# Each type carries a human label, the follow-up questions used to pull real
# numbers out of the user, and the units those answers usually come in.
OPP_TYPES: dict[str, dict[str, object]] = {
    "performance": {
        "label": "Performance",
        "questions": [
            "What was the latency or response time before the change?",
            "What was it after the change?",
            "How did you measure it (p50, p99, average)?",
        ],
        "units": ["ms", "seconds", "%", "x"],
    },
    "scale": {
        "label": "Scale",
        "questions": [
            "How many users, requests, or transactions did it handle before?",
            "How many after?",
            "Over what time window (per second, per day)?",
        ],
        "units": ["users", "requests/sec", "transactions", "x"],
    },
    "cost": {
        "label": "Cost",
        "questions": [
            "How much did it cost before?",
            "How much after, or how much did you save?",
            "Was that monthly or annual spend?",
        ],
        "units": ["$", "USD", "%"],
    },
    "time": {
        "label": "Time saved",
        "questions": [
            "How long did the process take before?",
            "How long after?",
            "How often did it run (per day, per week)?",
        ],
        "units": ["hours", "days", "minutes", "%"],
    },
    "revenue": {
        "label": "Revenue",
        "questions": [
            "How much revenue was influenced or generated?",
            "Over what period?",
            "Was it new revenue, upsell, or prevented churn?",
        ],
        "units": ["$", "USD", "%"],
    },
    "quality": {
        "label": "Quality / reliability",
        "questions": [
            "What was the error rate, uptime, or defect count before?",
            "What was it after?",
            "Over what time window did you measure?",
        ],
        "units": ["%", "count", "x"],
    },
    "team": {
        "label": "Team / leadership",
        "questions": [
            "How many people did you lead, mentor, or hire?",
            "What was their role level?",
            "Over what time period?",
        ],
        "units": ["people", "engineers", "%"],
    },
    "adoption": {
        "label": "Adoption",
        "questions": [
            "How many users or customers adopted it?",
            "What was the usage before vs after launch?",
            "What does 'adopted' mean here (signup, active use, migration)?",
        ],
        "units": ["users", "customers", "%"],
    },
}

# Keywords used to classify a bullet into an opportunity type. Ties break by
# OPP_TYPES insertion order.
_TYPE_KEYWORDS: dict[str, list[str]] = {
    "performance": [
        "latency", "p99", "p95", "throughput", "response time", "slow", "fast",
        "speed", "performance", "bottleneck", "lag", "efficient", "efficiency",
    ],
    "scale": [
        "scale", "scaled", "scaling", "users", "traffic", "requests", "volume",
        "growth", "grew", "load", "capacity", "qps", "rps", "millions",
        "billions",
    ],
    "cost": [
        "cost", "costs", "budget", "spend", "spending", "expense", "expenses",
        "saved", "savings", "cheaper", "waste",
    ],
    "time": [
        "time", "faster", "accelerated", "accelerate", "manual", "hours",
        "days", "weeks", "deployment time", "build time", "cycle time",
        "downtime", "on-call",
    ],
    "revenue": [
        "revenue", "sales", "conversion", "churn", "retention", "upsell",
        "deal", "deals", "mrr", "arr",
    ],
    "quality": [
        "quality", "bug", "bugs", "error", "errors", "defect", "defects",
        "uptime", "reliability", "reliable", "test coverage", "outage",
        "incidents", "incident", "accuracy",
    ],
    "team": [
        "team", "mentored", "mentor", "engineers", "onboarded", "hired",
        "hiring", "led", "lead", "reports", "interns", "standup", "culture",
    ],
    "adoption": [
        "adoption", "adopted", "usage", "customers", "launched", "launch",
        "rolled out", "rollout", "migration", "migrated", "signups",
        "activation",
    ],
}

# --- cue detection ------------------------------------------------------------
# A bullet already carrying a metric is never flagged. Everything else is
# scanned for vague quantifiers, impact verbs with no number, and scope
# words that lack a scale.
_VAGUE_QUANTIFIERS = [
    "significantly", "dramatically", "substantially", "greatly",
    "considerably", "many", "various", "multiple", "numerous", "several",
    "vast", "huge", "lots of", "a lot",
]
_IMPACT_VERBS = [
    "improved", "reduced", "increased", "optimized", "scaled", "cut",
    "accelerated", "boosted", "grew", "saved", "decreased", "lowered",
    "raised", "enhanced", "streamlined", "automated", "revamped",
    "overhauled", "doubled", "tripled", "launched", "drove",
]
_SCOPE_WORDS = [
    "team", "users", "customers", "revenue", "traffic", "latency",
    "pipeline", "budget", "costs", "performance", "uptime", "errors",
    "data", "system", "systems", "service", "services", "deployment",
]

# A digit near %, $, x, or a unit word counts as an existing metric.
_METRIC_RE = re.compile(
    r"(?i)"
    r"(\$\s?\d"                       # $5, $ 5
    r"|\d[\d,\.]*(?:\s*(?:"           # 50 followed by a unit
    r"%|percent\b|percentage\b|pct\b|x\b|\$|ms\b|secs?\b|seconds?\b|mins?\b|minutes?\b|hrs?\b|hours?\b"
    r"|days?\b|weeks?\b|months?\b|years?\b|users?\b|customers?\b|clients?\b"
    r"|engineers?\b|people\b|million\b|billion\b|thousand\b|k\b"
    r"|requests?\b|queries?\b|transactions?\b|rps\b|qps\b|rpm\b"
    r"|records?\b|rows?\b|pipelines?\b|servers?\b|nodes?\b|dollars?\b|usd\b"
    r")))"
)


def _has_metric(bullet: str) -> bool:
    """True when the bullet already contains a digit-based metric claim."""
    return bool(_METRIC_RE.search(bullet or ""))


def _detect_cues(bullet: str) -> list[str]:
    """Return the opportunity cues found in the bullet, in a fixed order."""
    cues: list[str] = []
    for word in _VAGUE_QUANTIFIERS + _IMPACT_VERBS + _SCOPE_WORDS:
        if re.search(r"\b" + re.escape(word) + r"\b", bullet, re.IGNORECASE):
            cues.append(word)
    return cues


def _classify_opp_type(bullet: str) -> str:
    """Pick the best opportunity type for a bullet. Deterministic."""
    lowered = bullet.lower()
    scores: dict[str, int] = {}
    for opp_type, keywords in _TYPE_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in lowered)
        scores[opp_type] = hits
    best = max(scores.values())
    if best == 0:
        return "performance"
    for opp_type in OPP_TYPES:  # insertion order breaks ties
        if scores[opp_type] == best:
            return opp_type
    return "performance"


# --- scanning -----------------------------------------------------------------
def scan_bullets(profile: dict) -> list[dict]:
    """Find bullets that could carry a metric but currently do not.

    Bullets that already contain a digit-based metric are skipped, as are
    bullets with no detectable opportunity cue.
    """
    results: list[dict] = []
    for role_idx, exp in enumerate(profile.get("experience", [])):
        role = exp.get("title", "")
        company = exp.get("company", "")
        for bullet_idx, bullet in enumerate(exp.get("bullets", [])):
            if _has_metric(bullet):
                continue
            cues = _detect_cues(bullet)
            if not cues:
                continue
            opp_type = _classify_opp_type(bullet)
            results.append(
                {
                    "role_idx": role_idx,
                    "bullet_idx": bullet_idx,
                    "role": role,
                    "company": company,
                    "bullet": bullet,
                    "cues": cues,
                    "opp_type": opp_type,
                    "questions": list(OPP_TYPES[opp_type]["questions"]),
                }
            )
    return results


def metric_coverage(profile: dict) -> dict:
    """Fraction of bullets that already carry metrics, overall and per role."""
    total = 0
    with_metrics = 0
    per_role: list[dict] = []
    for exp in profile.get("experience", []):
        bullets = exp.get("bullets", [])
        role_total = len(bullets)
        role_with = sum(1 for b in bullets if _has_metric(b))
        total += role_total
        with_metrics += role_with
        per_role.append(
            {
                "role": exp.get("title", ""),
                "company": exp.get("company", ""),
                "total": role_total,
                "with_metrics": role_with,
                "pct": (role_with / role_total * 100.0) if role_total else 0.0,
            }
        )
    return {
        "total": total,
        "with_metrics": with_metrics,
        "pct": (with_metrics / total * 100.0) if total else 0.0,
        "per_role": per_role,
    }


# --- validation ---------------------------------------------------------------
_PERCENT_UNITS = {"%", "percent", "pct", "percentage"}
_TIME_UNITS = {
    "ms", "millisecond", "milliseconds", "s", "sec", "second", "seconds",
    "min", "minute", "minutes", "hr", "hour", "hours", "day", "days",
}
_RATIO_UNITS = {"x", "times", "ratio", "multiple", "fold"}


def validate_metric(opp_type: str, number: float, unit: str) -> list[str]:
    """Sanity-check a user-supplied metric. Returns warnings, [] when sane."""
    warnings: list[str] = []
    u = (unit or "").strip().lower()
    if u in _PERCENT_UNITS and abs(number) > 10000:
        warnings.append(
            f"absurd percent value {number}: improvements above 10000% "
            "are almost always a typo"
        )
    if opp_type in ("performance", "time") and u in _TIME_UNITS and number < 0:
        warnings.append(
            f"negative time value {number}{unit}: latency and durations "
            "cannot be negative"
        )
    if u in _RATIO_UNITS and number == 0:
        warnings.append(
            f"zero ratio {number}{unit}: a 0x improvement means no change "
            "at all, and ratios divide by the before value"
        )
    return warnings


# --- phrasing -----------------------------------------------------------------
# Templates only ever use keys present in `answers`; required keys are
# checked up front, so a missing number yields [] instead of a guess.
_TEMPLATES: dict[str, list[tuple[frozenset, str]]] = {
    "performance": [
        (frozenset({"before", "after", "unit", "pct"}),
         "Cut p99 latency from {before}{unit} to {after}{unit} ({pct}% reduction)"),
        (frozenset({"before", "after", "unit", "pct"}),
         "Reduced latency by {pct}%, from {before}{unit} to {after}{unit}"),
        (frozenset({"before", "after", "unit", "pct"}),
         "Improved response time from {before}{unit} to {after}{unit}, a {pct}% improvement"),
    ],
    "scale": [
        (frozenset({"before", "after", "unit"}),
         "Scaled throughput from {before} to {after} {unit}"),
        (frozenset({"before", "after", "unit"}),
         "Grew {unit} from {before} to {after}"),
        (frozenset({"before", "after", "unit"}),
         "Increased capacity to {after} {unit} (up from {before})"),
    ],
    "cost": [
        (frozenset({"value", "unit"}),
         "Saved {value}{unit} in annual costs"),
        (frozenset({"value", "unit"}),
         "Cut costs by {value}{unit}"),
        (frozenset({"value", "unit"}),
         "Reduced spend by {value}{unit}"),
    ],
    "time": [
        (frozenset({"before", "after", "unit"}),
         "Cut cycle time from {before} to {after} {unit}"),
        (frozenset({"before", "after", "unit"}),
         "Reduced manual effort from {before}{unit} to {after}{unit}"),
        (frozenset({"before", "after", "unit"}),
         "Shortened turnaround from {before} {unit} to {after} {unit}"),
    ],
    "revenue": [
        (frozenset({"value", "unit"}),
         "Drove {value}{unit} in new revenue"),
        (frozenset({"value", "unit"}),
         "Generated {value}{unit} in incremental revenue"),
        (frozenset({"value", "unit"}),
         "Added {value}{unit} to the pipeline"),
    ],
    "quality": [
        (frozenset({"before", "after", "unit"}),
         "Cut error rate from {before} to {after} {unit}"),
        (frozenset({"before", "after", "unit"}),
         "Improved reliability from {before} to {after} {unit}"),
        (frozenset({"before", "after", "unit"}),
         "Reduced defects from {before} to {after} {unit}"),
    ],
    "team": [
        (frozenset({"value", "unit"}),
         "Led a team of {value} {unit}"),
        (frozenset({"value", "unit"}),
         "Mentored {value} {unit}"),
        (frozenset({"value", "unit"}),
         "Grew the team to {value} {unit}"),
    ],
    "adoption": [
        (frozenset({"value", "unit"}),
         "Drove adoption to {value} {unit}"),
        (frozenset({"value", "unit"}),
         "Onboarded {value} {unit}"),
        (frozenset({"value", "unit"}),
         "Grew active usage to {value} {unit}"),
    ],
}


def suggest_phrasings(bullet: str, opp_type: str, answers: dict) -> list[str]:
    """Build 2-3 deterministic bullet variants from user-supplied answers.

    Only numbers present in `answers` are used. If a required number is
    missing, returns [] rather than invent one.
    """
    templates = _TEMPLATES.get(opp_type, [])
    supplied = {k: v for k, v in (answers or {}).items() if v is not None}
    safe = {k: str(v) for k, v in supplied.items()}
    out: list[str] = []
    for required, template in templates:
        if not required.issubset(supplied):
            continue
        out.append(template.format(**safe))
    return out


# --- metrics bank (user-supplied answers on disk) ------------------------------
def bank_key(role_idx: int, bullet_idx: int) -> str:
    """Canonical bank key for a bullet."""
    return f"{role_idx}:{bullet_idx}"


def load_bank() -> dict:
    """Load the metrics bank. Missing or corrupt file yields {}."""
    path = config.METRICS_BANK_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_bank(bank: dict) -> None:
    """Persist the metrics bank as JSON."""
    path = config.METRICS_BANK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bank, indent=2, sort_keys=True))


# Statuses proving the numbers came from the user (never invented).
_USER_BACKED_STATUSES = {"supplied", "accepted", "applied"}


def record_answer(
    bank: dict,
    role_idx: int,
    bullet_idx: int,
    bullet: str,
    answers: dict,
    status: str = "supplied",
) -> dict:
    """Record the user's answer for a bullet in the bank (in memory)."""
    bank[bank_key(role_idx, bullet_idx)] = {
        "role_idx": role_idx,
        "bullet_idx": bullet_idx,
        "bullet": bullet,
        "answers": answers or {},
        "status": status,
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    return bank


# --- rewrite / debt / audit ----------------------------------------------------
def apply_rewrite(
    profile: dict, role_idx: int, bullet_idx: int, new_bullet: str
) -> dict:
    """Return a NEW profile with the bullet replaced. Pure, no disk writes."""
    new_profile = copy.deepcopy(profile)
    new_profile["experience"][role_idx]["bullets"][bullet_idx] = new_bullet
    return new_profile


def metric_debt(profile: dict, bank: dict) -> list[dict]:
    """Scan results with no bank entry, or an entry that is not resolved.

    A bullet leaves the debt list once the user supplies numbers ("supplied")
    or explicitly declines ("declined"). "skipped" stays in debt.
    """
    debt: list[dict] = []
    for item in scan_bullets(profile):
        key = bank_key(item["role_idx"], item["bullet_idx"])
        entry = bank.get(key)
        if entry and entry.get("status") in ("supplied", "declined"):
            continue
        debt.append(item)
    return debt


def audit_no_invention(profile: dict, bank: dict) -> dict:
    """Check that every metric claim in the profile is backed by the user.

    For each bullet containing a digit-based metric, a bank entry with
    a user-backed status ("supplied", "accepted", or "applied") must exist.
    Violations name the offending bullets.
    """
    violations: list[str] = []
    for role_idx, exp in enumerate(profile.get("experience", [])):
        role = exp.get("title", "")
        company = exp.get("company", "")
        for bullet_idx, bullet in enumerate(exp.get("bullets", [])):
            if not _has_metric(bullet):
                continue
            entry = bank.get(bank_key(role_idx, bullet_idx))
            if not (entry and entry.get("status") in _USER_BACKED_STATUSES):
                violations.append(f"{role} at {company}: {bullet}")
    return {"ok": not violations, "violations": violations}


def export_story_metrics(bank: dict) -> list[dict]:
    """Export user-backed metrics for the story bank. JSON-serializable."""
    out: list[dict] = []
    for entry in bank.values():
        if not isinstance(entry, dict) or entry.get("status") not in _USER_BACKED_STATUSES:
            continue
        answers = entry.get("answers", {})
        if not isinstance(answers, dict):
            answers = {}
        flat = {str(k): (v if isinstance(v, (str, int, float, bool)) or v is None else str(v))
                for k, v in answers.items()}
        summary = "; ".join(f"{k}: {v}" for k, v in sorted(flat.items()) if v is not None)
        out.append(
            {
                "bullet": entry.get("bullet", ""),
                "metric_summary": summary,
                "answers": flat,
            }
        )
    json.dumps(out)  # prove serializability
    return out

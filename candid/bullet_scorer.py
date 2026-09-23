"""Bullet impact scorer for resume bullets.

Pure functions (no I/O except an optional file read in score_resume).
Every bullet is scored 0-100 on five dimensions:

  action_verb   (25)  starts with a strong action verb
  result        (30)  states an outcome / impact, ideally quantified
  scope         (20)  states scale: who/what/how much was touched
  specificity   (15)  concrete nouns: named tools, teams, systems, numbers
  length        (10)  8-35 words; too terse or too rambling loses points

GOLDEN RULE: groundedness is non-negotiable. The scorer and the rewriter
must NEVER invent experience, metrics, percentages, tools, or
achievements. A reword may only rearrange words and facts already present
in the bullet (plus the user's own verified skill names). When a fact is
missing, the module emits a *question for the user* instead of a claim.
"""

from __future__ import annotations

import re
from pathlib import Path


class BulletScorerError(Exception):
    """Raised when a bullet or resume cannot be scored."""


# ---------------------------------------------------------------------------
# lexicons
# ---------------------------------------------------------------------------

#: weak lead-in phrase -> stronger, meaning-preserving alternatives.
#: Alternatives only change the verb framing; they add no new facts.
WEAK_VERBS: dict[str, list[str]] = {
    "responsible for": ["owned", "led", "drove"],
    "tasked with": ["owned", "drove", "led"],
    "in charge of": ["owned", "led"],
    "helped with": ["supported", "contributed to"],
    "helped to": ["supported", "contributed to"],
    "assisted with": ["supported", "contributed to"],
    "assisted in": ["supported", "contributed to"],
    "worked on": ["developed", "built", "delivered"],
    "worked with": ["partnered with", "collaborated with"],
    "involved in": ["contributed to", "drove"],
    "participated in": ["contributed to"],
    "was part of": ["contributed to"],
    "duties included": ["owned", "delivered"],
    "my role was": ["owned", "led"],
}

#: first words that signal a strong bullet (lowercased, stemmed loosely)
STRONG_VERBS = {
    "built", "developed", "designed", "architected", "led", "launched",
    "shipped", "delivered", "drove", "owned", "created", "established",
    "founded", "pioneered", "spearheaded", "scaled", "grew", "improved",
    "increased", "decreased", "reduced", "cut", "saved", "boosted",
    "accelerated", "optimized", "automated", "streamlined", "migrated",
    "modernized", "negotiated", "mentored", "partnered", "secured",
    "transformed", "revamped", "overhauled", "championed", "instituted",
    "implemented", "deployed", "engineered", "crafted", "forged",
}

#: neutral but acceptable openers
NEUTRAL_VERBS = {
    "used", "made", "did", "got", "worked", "helped", "handled",
    "managed", "ran", "supported", "maintained", "performed", "conducted",
    "analyzed", "tested", "wrote", "presented", "provided", "served",
}

#: words that signal an outcome happened
RESULT_WORDS = {
    "increased", "decreased", "reduced", "improved", "grew", "growth",
    "saved", "cut", "boosted", "lifted", "accelerated", "achieved",
    "resulting", "resulted", "leading", "drove", "yielding", "delivering",
    "enabling", "preventing", "eliminating", "raising", "lowering",
    "improvement", "reduction", "savings", "uplift", "uptime",
}

#: nouns that signal scale when paired with a number
SCALE_NOUNS = {
    "users", "user", "customers", "customer", "clients", "requests",
    "queries", "events", "engineers", "members", "teams", "team",
    "services", "endpoints", "repos", "datasets", "models", "transactions",
    "orders", "visitors", "subscribers", "employees", "markets",
    "countries", "regions", "products", "features", "tickets",
}

#: vague scale words (partial credit only)
VAGUE_SCALE = {
    "large", "multiple", "various", "several", "numerous", "many",
    "cross-functional", "enterprise", "global", "org-wide", "company-wide",
}

_METRIC_RE = re.compile(r"\d[\d,.]*\s*%|\$\s?\d[\d,.]*[kmb]?|\b\d+\s*[x×]\b", re.I)
_NUMBER_RE = re.compile(r"\d[\d,]*(\.\d+)?")
_CAPITALIZED_RE = re.compile(r"\b[A-Z][A-Za-z0-9+.#]*\b")
_TECH_RE = re.compile(
    r"\b(python|sql|java|c\+\+|javascript|typescript|react|aws|gcp|azure|"
    r"docker|kubernetes|spark|kafka|airflow|tensorflow|pytorch|scikit-learn|"
    r"pandas|numpy|dbt|tableau|excel|graphql|rest|grpc|redis|postgres|"
    r"mysql|bigquery|snowflake|ml|ai|llm|nlp|etl|ci/cd|terraform)\b", re.I)
_BULLET_MARK = re.compile(r"^\s*[•·▪◦\-\*\+–—>]\s+")

# weights sum to 100
WEIGHTS = {"action_verb": 25, "result": 30, "scope": 20,
           "specificity": 15, "length": 10}

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "by", "at", "from", "as", "is", "was", "were", "are", "be", "been",
    "that", "this", "it", "its", "into", "over", "under", "through",
    "across", "per", "via", "using", "used", "use", "within", "between",
}


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------

def _first_word(bullet: str) -> str:
    m = re.match(r"[A-Za-z']+", bullet.strip())
    return m.group(0).lower() if m else ""


def _find_weak_phrase(bullet: str) -> str | None:
    low = bullet.strip().lower()
    # strip a leading "i " pronoun first
    low = re.sub(r"^i\s+", "", low)
    for phrase in WEAK_VERBS:
        if low.startswith(phrase + " ") or low == phrase:
            return phrase
    return None


def _score_action_verb(bullet: str) -> tuple[int, list[dict]]:
    """Score the opening verb; flag weak lead-ins with alternatives."""
    flags: list[dict] = []
    weak = _find_weak_phrase(bullet)
    if weak:
        flags.append({
            "type": "weak_verb",
            "detail": f"Opens with the weak phrase '{weak}'.",
            "alternatives": WEAK_VERBS[weak],
        })
        return 5, flags
    first = _first_word(bullet)
    if first in STRONG_VERBS:
        return WEIGHTS["action_verb"], flags
    if first in NEUTRAL_VERBS:
        flags.append({
            "type": "weak_verb",
            "detail": f"Opens with the neutral verb '{first}'.",
            "alternatives": ["led", "built", "drove", "delivered"],
        })
        return 12, flags
    return 8, flags


def _has_metric(bullet: str) -> bool:
    return bool(_METRIC_RE.search(bullet))


def _score_result(bullet: str) -> tuple[int, list[dict]]:
    flags: list[dict] = []
    low = bullet.lower()
    metric = _has_metric(bullet)
    outcome = any(w in low for w in RESULT_WORDS)
    if metric and outcome:
        return WEIGHTS["result"], flags
    if metric:
        return 20, flags  # number present but no clear outcome stated
    if outcome:
        flags.append({
            "type": "missing_metric",
            "detail": "States an outcome but gives no number.",
            "question": ("Can you quantify this outcome — e.g. by how much, "
                         "what %, or what dollar amount?"),
        })
        return 18, flags
    flags.append({
        "type": "missing_result",
        "detail": "No outcome or impact is stated.",
        "question": ("What changed because of this work? (time saved, "
                     "revenue, users affected, errors reduced — your words)"),
    })
    return 0, flags


def _score_scope(bullet: str) -> tuple[int, list[dict]]:
    flags: list[dict] = []
    low = bullet.lower()
    words = set(re.findall(r"[a-z]+(?:-[a-z]+)?", low))
    has_numbered_scale = bool(_NUMBER_RE.search(bullet)) and bool(
        words & SCALE_NOUNS)
    has_explicit_scale = bool(re.search(
        r"\bacross\b|\borg-wide\b|\bcompany-wide\b|\bglobal\b", low))
    if has_numbered_scale or has_explicit_scale:
        return WEIGHTS["scope"], flags
    if words & VAGUE_SCALE:
        flags.append({
            "type": "vague_scope",
            "detail": "Scale is hinted at but vague.",
            "question": ("How big was the scope — how many people, users, "
                         "requests, or team members?"),
        })
        return 10, flags
    flags.append({
        "type": "missing_scope",
        "detail": "No scale or scope is stated.",
        "question": ("Consider adding scale/scope: who or what did this "
                     "touch — users, requests per day, team size?"),
    })
    return 0, flags


def _concrete_tokens(bullet: str, profile_skills: list[str] | None = None
                     ) -> set[str]:
    """Concrete tokens: numbers, capitalized terms, tech terms, skill names."""
    found: set[str] = set(_NUMBER_RE.findall(bullet))
    found |= set(_METRIC_RE.findall(bullet))
    # capitalized words after the first word (proper nouns / product names)
    words = _CAPITALIZED_RE.findall(bullet)
    first = _first_word(bullet)
    found |= {w for w in words if w.lower() != first}
    found |= set(_TECH_RE.findall(bullet))
    if profile_skills:
        low = bullet.lower()
        for skill in profile_skills:
            if skill and skill.lower() in low:
                found.add(skill)
    return {t for t in found if t}


def _score_specificity(bullet: str,
                       profile_skills: list[str] | None = None
                       ) -> tuple[int, list[dict]]:
    flags: list[dict] = []
    tokens = _concrete_tokens(bullet, profile_skills)
    # 5+ concrete tokens earns full marks
    score = min(WEIGHTS["specificity"],
                round(WEIGHTS["specificity"] * len(tokens) / 5))
    if len(tokens) < 2:
        flags.append({
            "type": "vague",
            "detail": "Few concrete details (tools, systems, names, numbers).",
            "question": ("Which specific tools, systems, or teams were "
                         "involved here?"),
        })
    return score, flags


def _word_count(bullet: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", bullet))


def _score_length(bullet: str) -> tuple[int, list[dict]]:
    flags: list[dict] = []
    n = _word_count(bullet)
    if 8 <= n <= 35:
        return WEIGHTS["length"], flags
    if n < 4:
        flags.append({"type": "too_short",
                      "detail": f"Only {n} words — too terse to be useful.",
                      "question": "What did you actually do, and what was the result?"})
        return 2, flags
    if n < 8:
        return 6, flags
    flags.append({"type": "too_long",
                  "detail": f"{n} words — likely rambling; split or trim.",
                  "question": None})
    return 5, flags


def _fix_priority(flag: dict) -> int:
    order = {"missing_result": 0, "missing_metric": 1, "missing_scope": 2,
             "weak_verb": 3, "vague_scope": 4, "vague": 5,
             "too_short": 6, "too_long": 7}
    return order.get(flag.get("type", ""), 99)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def score_bullet(bullet: str,
                 profile_skills: list[str] | None = None) -> dict:
    """Score one resume bullet 0-100 with a per-dimension breakdown.

    Returns {score, breakdown, flags, word_count}. Deterministic: the same
    input always yields the same output.
    """
    bullet = (bullet or "").strip()
    if not bullet:
        raise BulletScorerError("Cannot score an empty bullet.")
    breakdown: dict[str, int] = {}
    flags: list[dict] = []
    scorers = (
        ("action_verb", lambda: _score_action_verb(bullet)),
        ("result", lambda: _score_result(bullet)),
        ("scope", lambda: _score_scope(bullet)),
        ("specificity", lambda: _score_specificity(bullet, profile_skills)),
        ("length", lambda: _score_length(bullet)),
    )
    for name, fn in scorers:
        pts, f = fn()
        breakdown[name] = pts
        flags.extend(f)
    flags.sort(key=_fix_priority)
    return {
        "bullet": bullet,
        "score": sum(breakdown.values()),
        "breakdown": breakdown,
        "flags": flags,
        "word_count": _word_count(bullet),
    }


def extract_bullets(markdown: str) -> list[str]:
    """Pull bullet texts out of a resume markdown string."""
    bullets: list[str] = []
    for raw in (markdown or "").splitlines():
        if _BULLET_MARK.match(raw):
            text = _BULLET_MARK.sub("", raw).strip()
            if text and len(text.split()) >= 2:
                bullets.append(text)
    return bullets


def score_resume(markdown: str,
                 profile_skills: list[str] | None = None) -> dict:
    """Score every bullet in a resume markdown.

    Returns {bullets: [score_bullet results], overall, fixes, bullet_count}.
    ``fixes`` lists bullets scoring below 70, lowest first, each with its
    top-priority flag and the question to ask the user.
    """
    bullets = extract_bullets(markdown)
    if not bullets:
        raise BulletScorerError("No bullets found in the provided markdown.")
    scored = [score_bullet(b, profile_skills) for b in bullets]
    overall = round(sum(s["score"] for s in scored) / len(scored))
    fixes = []
    for s in sorted((s for s in scored if s["score"] < 70),
                    key=lambda s: s["score"]):
        top = s["flags"][0] if s["flags"] else None
        fixes.append({
            "bullet": s["bullet"],
            "score": s["score"],
            "top_issue": top["type"] if top else "low_score",
            "detail": (top or {}).get("detail", ""),
            "question": (top or {}).get("question"),
        })
    return {
        "bullets": scored,
        "overall": overall,
        "fixes": fixes,
        "bullet_count": len(scored),
    }


def score_file(path: str | Path) -> dict:
    """Score a resume markdown/text file. Optional I/O convenience."""
    p = Path(path)
    if not p.exists():
        raise BulletScorerError(f"File not found: {p}")
    return score_resume(p.read_text(encoding="utf-8", errors="replace"))


# ---------------------------------------------------------------------------
# grounded rewording
# ---------------------------------------------------------------------------

def _allowed_vocabulary(bullet: str,
                        profile_skills: list[str] | None = None) -> set[str]:
    """Words the rewriter may use: bullet words + user skill names + glue."""
    vocab = {w.lower() for w in re.findall(r"[A-Za-z0-9'+.#]+", bullet)}
    for skills in (profile_skills or []):
        for w in re.findall(r"[A-Za-z0-9'+.#]+", skills):
            vocab.add(w.lower())
    # common glue words + every alternative verb we might substitute
    vocab |= _STOPWORDS | {"my", "our", "their"}
    for alts in WEAK_VERBS.values():
        for alt in alts:
            vocab |= set(alt.split())
    vocab |= STRONG_VERBS | NEUTRAL_VERBS
    return vocab


def suggest_reword(bullet: str,
                   profile_skills: list[str] | None = None) -> dict:
    """Suggest a stronger rewording using ONLY facts already in the bullet.

    The rewrite may swap a weak lead-in verb for a stronger one and tidy
    phrasing, but it must never add metrics, tools, or claims that are not
    present. Anything needing a new fact becomes a question for the user.

    Returns {original, reworded, changed, questions, notes}.
    """
    bullet = (bullet or "").strip()
    if not bullet:
        raise BulletScorerError("Cannot reword an empty bullet.")
    questions: list[str] = []
    notes: list[str] = []
    text = bullet

    # 1. strip a leading "I"/"my" pronoun (resumes don't use them)
    m = re.match(r"^(I|My)\s+", text)
    if m:
        text = text[m.end():]
        notes.append("Dropped the leading pronoun (resumes omit 'I').")

    # 2. swap a weak lead-in for a stronger verb phrase (no new facts:
    #    the rest of the sentence is untouched)
    weak = _find_weak_phrase(text)
    changed = False
    if weak:
        rest = re.sub(r"^i\s+", "",
                      text.strip(), flags=re.I)[len(weak):].strip()
        # pick the alternative whose tail already fits the sentence shape
        alt = WEAK_VERBS[weak][0]
        if rest.lower().startswith(("to ", "for ", "of ")):
            # "responsible for to maintain" never happens; guard anyway
            rest = rest
        text = f"{alt} {rest}".strip()
        # fix doubled verb-ish artifacts like "owned maintaining" -> keep;
        # meaning is preserved, grammar stays the user's to polish
        changed = True
        notes.append(f"Replaced weak lead-in '{weak}' with '{alt}'.")

    # 3. capitalize the first letter
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
        changed = True

    # 4. missing facts become questions, never invented claims
    scored = score_bullet(bullet, profile_skills)
    for flag in scored["flags"]:
        q = flag.get("question")
        if q and q not in questions:
            questions.append(q)
    if changed:
        notes.append(
            "No new facts were added — only the verb framing changed.")
    else:
        notes.append(
            "No safe reword found; the bullet's wording already carries "
            "its own facts. Answer the questions above to strengthen it.")

    return {
        "original": bullet,
        "reworded": text,
        "changed": changed,
        "questions": questions,
        "notes": notes,
    }

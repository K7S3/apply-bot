"""Outreach draft scoring + hiring-manager research checklist (W3).

Two pieces:

1. score_draft(text, dossier=None, channel="email") -> dict
   Scores a cold-outreach draft (email or LinkedIn) on personalization and
   hygiene. Returns {"score": 0-100, "grade": "strong"/"ok"/"weak",
   "findings": [{"check", "passed", "detail"}, ...]}.

2. Research checklist for a hiring manager, persisted per dossier to
   DATA_DIR/"hm_research.json":
     research_checklist(dossier_ref=None) -> [items with status]
     checklist_update(ref, key, status, note="") -> updated item
     checklist_status(ref) -> {"done", "total", "items"}

Dossiers are plain dicts:
    {"id", "name", "title", "company", "team", "notes",
     "sources": [{"label", "url"}], "interests": [str]}
Where a dossier *reference* (id string) is accepted, the lookup goes through
``candid.hm`` imported lazily inside the function. If that module is
unavailable or the ref is unknown, the functions fall back to a bare
checklist without persistence instead of raising.

Stdlib only, no network calls. Sample data in tests is fictional.
"""

from __future__ import annotations

import json
import re

from candid import config as C

# ---------------------------------------------------------------------------
# spammy / hype language
# ---------------------------------------------------------------------------

SPAMMY_PHRASES = [
    "synergy",
    "synergies",
    "rockstar",
    "rock star",
    "game-changer",
    "game changer",
    "pick your brain",
    "to whom it may concern",
    "dear sir",
    "dear madam",
    "ninja",
    "guru",
    "thought leader",
    "crush it",
    "circle back",
    "touch base",
    "low-hanging fruit",
    "move the needle",
    "disrupt",
    "revolutionize",
    "once-in-a-lifetime",
    "guaranteed",
    "act now",
    "limited time",
]

# Praise that reads as copy-paste unless a concrete specific follows it.
GENERIC_FLATTERY = [
    "amazing work",
    "incredible work",
    "impressive",
    "incredible",
    "big fan",
    "huge fan",
    "love what you're doing",
    "love what you are doing",
    "so inspiring",
    "inspiring work",
]

# Low-friction asks that count as a clear CTA (a plain "?" also counts).
CTA_PHRASES = [
    "15-min",
    "15 min",
    "15-minute",
    "15 minute",
    "quick call",
    "quick chat",
    "brief call",
    "brief chat",
    "coffee chat",
    "open to a chat",
    "worth a conversation",
    "would you be open",
    "happy to chat",
    "time to connect",
    "grab time",
    "pick a time",
    "on your calendar",
]

_PLACEHOLDER_RES = [
    re.compile(r"\[[^\]\n]{1,40}\]"),          # [Name], [Company]
    re.compile(r"\bTODO\b"),                   # TODO
    re.compile(r"\bXXX\b"),                    # XXX
    re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}"),  # {name}
    re.compile(r"\{\{.+?\}\}"),                # {{name}}
]

_STOPWORDS = {
    "of", "the", "and", "for", "at", "in", "on", "to", "a", "an",
    "with", "by", "from", "as", "is", "are", "or", "it", "its",
}

# check id -> weight; weights sum to 100.
_CHECK_WEIGHTS = [
    ("names_manager", 15),
    ("dossier_specifics", 20),
    ("length", 15),
    ("clear_cta", 20),
    ("no_spammy_phrases", 10),
    ("no_generic_flattery", 10),
    ("no_placeholders", 10),
]


# ---------------------------------------------------------------------------
# dossier helpers
# ---------------------------------------------------------------------------

def _lookup_dossier(ref):
    """Resolve a dossier id via candid.hm (imported lazily).

    Returns the dossier dict, or None when the hm module is unavailable,
    has no suitable accessor, or the ref is unknown. Never raises.
    """
    if not ref or isinstance(ref, dict):
        return ref if isinstance(ref, dict) else None
    try:
        from candid import hm  # local import: hm is another worker's module
    except ImportError:
        return None
    for accessor in ("get_dossier", "find_dossier", "load_dossier", "dossier"):
        fn = getattr(hm, accessor, None)
        if not callable(fn):
            continue
        try:
            dossier = fn(ref)
        except Exception:
            continue
        if isinstance(dossier, dict) and dossier:
            return dossier
    return None


def _resolve_dossier(dossier):
    """Accept a dossier dict or an id string; anything else -> None."""
    if isinstance(dossier, dict):
        return dossier
    if isinstance(dossier, str):
        return _lookup_dossier(dossier)
    return None


def _dossier_keywords(dossier):
    """Map lowercase keyword -> source label for dossier-specific matching."""
    keywords: dict[str, str] = {}

    def add(value, label, min_len=3):
        for tok in re.findall(r"[A-Za-z][A-Za-z0-9&+#.\-]*", value or ""):
            low = tok.lower()
            if low in _STOPWORDS:
                continue
            if len(tok) < min_len and not (len(tok) == 2 and tok.isupper()):
                continue
            keywords.setdefault(low, label)

    name = dossier.get("name") or ""
    for part in name.split():
        keywords.setdefault(part.lower(), "name")
    add(dossier.get("title"), "title")
    company = dossier.get("company") or ""
    if company.strip():
        keywords.setdefault(company.strip().lower(), "company")
    add(company, "company")
    team = dossier.get("team") or ""
    if team.strip():
        keywords.setdefault(team.strip().lower(), "team")
    add(team, "team")
    for interest in dossier.get("interests") or []:
        if interest and interest.strip():
            keywords.setdefault(interest.strip().lower(), "interest")
        add(interest, "interest")
    add(dossier.get("notes"), "notes", min_len=4)
    return keywords


def _keyword_hits(text, keywords):
    hits = []
    for kw, label in keywords.items():
        if re.search(
            r"(?<![A-Za-z0-9])" + re.escape(kw) + r"(?![A-Za-z0-9])",
            text,
            re.IGNORECASE,
        ):
            hits.append((kw, label))
    return hits


# ---------------------------------------------------------------------------
# individual checks: each returns (passed: bool, detail: str)
# ---------------------------------------------------------------------------

def _check_names_manager(text, dossier, channel):
    if not dossier or not (dossier.get("name") or "").strip():
        return True, "no dossier provided - name check skipped"
    name = dossier["name"].strip()
    parts = name.split()
    hits = [
        p for p in (parts[0], parts[-1] if len(parts) > 1 else "")
        if p and re.search(r"\b" + re.escape(p) + r"\b", text, re.IGNORECASE)
    ]
    if hits:
        return True, "addresses the manager by name (%s)" % ", ".join(hits)
    return False, "never addresses %s by name" % name


def _check_dossier_specifics(text, dossier, channel):
    if not dossier:
        return True, "no dossier provided - specifics check skipped"
    keywords = _dossier_keywords(dossier)
    hits = _keyword_hits(text, keywords)
    if hits:
        shown = ", ".join(sorted({kw for kw, _ in hits})[:5])
        return True, "references dossier specifics: %s" % shown
    return (
        False,
        "no dossier specifics found - mention their title, company, team, "
        "interests, or something from your notes",
    )


def _check_length(text, dossier, channel):
    ch = (channel or "email").lower()
    if ch == "linkedin":
        n = len(text)
        if n <= 300:
            return True, "%d chars - within the 300-char LinkedIn limit" % n
        return False, "%d chars - over the 300-char LinkedIn limit" % n
    words = len(text.split())
    if 80 <= words <= 400:
        return True, "%d words - within the 80-400 word email range" % words
    if words < 80:
        return False, "%d words - under the 80-word email minimum" % words
    return False, "%d words - over the 400-word email maximum" % words


def _check_cta(text, dossier, channel):
    low = text.lower()
    hits = [p for p in CTA_PHRASES if p in low]
    if "?" in text or hits:
        bits = []
        if hits:
            bits.append("low-friction ask (%s)" % ", ".join(hits[:2]))
        if "?" in text:
            bits.append("asks a question")
        return True, "; ".join(bits)
    return (
        False,
        "no clear call to action - end with a question or a 15-min ask",
    )


def _check_no_spammy(text, dossier, channel):
    low = text.lower()
    phrase_hits = sorted({p for p in SPAMMY_PHRASES if p in low})
    caps = sorted(set(re.findall(r"\b[A-Z]{4,}\b", text)))
    excl = text.count("!")
    problems = []
    if phrase_hits:
        problems.append("spammy phrase(s): %s" % ", ".join(phrase_hits))
    if len(caps) >= 2:
        problems.append("ALL-CAPS words: %s" % ", ".join(caps[:5]))
    if excl >= 3:
        problems.append("%d exclamation marks" % excl)
    if problems:
        return False, "; ".join(problems)
    return True, "no spammy phrases, ALL-CAPS shouting, or !!! punctuation"


def _has_specific_after(phrase_end_text, keywords):
    """Does the text following a flattery phrase name anything concrete?"""
    if re.search(r'"[^"]+"', phrase_end_text):
        return True
    if re.search(r"\d", phrase_end_text):
        return True
    return bool(_keyword_hits(phrase_end_text, keywords))


def _check_no_generic_flattery(text, dossier, channel):
    low = text.lower()
    keywords = _dossier_keywords(dossier) if dossier else {}
    for phrase in GENERIC_FLATTERY:
        i = low.find(phrase)
        if i == -1:
            continue
        following = text[i + len(phrase): i + len(phrase) + 200]
        if _has_specific_after(following, keywords):
            continue
        return (
            False,
            "generic flattery ('%s') with no specific follow-up - "
            "name the post, talk, or work you mean" % phrase,
        )
    return True, "no generic flattery (or all praise names something specific)"


def _check_no_placeholders(text, dossier, channel):
    found = []
    for rx in _PLACEHOLDER_RES:
        found.extend(rx.findall(text))
    found = sorted(set(found))[:5]
    if found:
        return False, "unresolved placeholder(s): %s" % ", ".join(found)
    return True, "no unresolved placeholders"


_CHECKS = {
    "names_manager": _check_names_manager,
    "dossier_specifics": _check_dossier_specifics,
    "length": _check_length,
    "clear_cta": _check_cta,
    "no_spammy_phrases": _check_no_spammy,
    "no_generic_flattery": _check_no_generic_flattery,
    "no_placeholders": _check_no_placeholders,
}


# ---------------------------------------------------------------------------
# public scoring API
# ---------------------------------------------------------------------------

def score_draft(text, dossier=None, channel="email"):
    """Score an outreach draft.

    Returns {"score": 0-100, "grade": "strong"/"ok"/"weak",
             "findings": [{"check", "passed", "detail"}]}.
    ``dossier`` may be a dossier dict or an id string (resolved via
    candid.hm when available). ``channel`` is "email" or "linkedin".
    """
    text = text or ""
    dossier = _resolve_dossier(dossier)
    findings = []
    score = 0
    for check_id, weight in _CHECK_WEIGHTS:
        passed, detail = _CHECKS[check_id](text, dossier, channel)
        if passed:
            score += weight
        findings.append({"check": check_id, "passed": passed, "detail": detail})
    score = max(0, min(100, score))
    grade = "strong" if score >= 80 else ("ok" if score >= 50 else "weak")
    return {"score": score, "grade": grade, "findings": findings}


def suggest_fixes(text, dossier=None, channel="email"):
    """One-line fix suggestions, one per failed check. Empty when all pass."""
    dossier = _resolve_dossier(dossier)
    result = score_draft(text, dossier=dossier, channel=channel)
    name = (dossier or {}).get("name") or ""
    first = name.split()[0] if name.split() else "the manager"
    fixes = []
    for finding in result["findings"]:
        if finding["passed"]:
            continue
        check = finding["check"]
        if check == "names_manager":
            fixes.append(
                "Open with the manager's name, e.g. 'Hi %s,' instead of a generic greeting."
                % first
            )
        elif check == "dossier_specifics":
            bits = []
            if dossier:
                if dossier.get("title"):
                    bits.append("their role (%s)" % dossier["title"])
                if dossier.get("company"):
                    bits.append(dossier["company"])
                if dossier.get("team"):
                    bits.append("the %s team" % dossier["team"])
            fixes.append(
                "Reference something specific: %s."
                % (", ".join(bits) if bits else
                   "their title, company, team, or a note from your research")
            )
        elif check == "length":
            fixes.append("Fix the length: %s." % finding["detail"])
        elif check == "clear_cta":
            fixes.append(
                "End with a low-friction ask, e.g. 'Open to a 15-min chat next week?'"
            )
        elif check == "no_spammy_phrases":
            fixes.append("Cut the hype: %s." % finding["detail"])
        elif check == "no_generic_flattery":
            fixes.append(
                "Swap generic praise for a concrete reference - a post, talk, "
                "or paper of theirs."
            )
        elif check == "no_placeholders":
            fixes.append("Fill in or delete the placeholders: %s." % finding["detail"])
    return fixes


# ---------------------------------------------------------------------------
# research checklist
# ---------------------------------------------------------------------------

RESEARCH_ITEMS = [
    {
        "key": "recent_posts",
        "label": "Recent posts & talks",
        "hint": "Skim their last 3-5 LinkedIn posts and any talks or panels.",
    },
    {
        "key": "team_page",
        "label": "Team page & open roles",
        "hint": "Find the team page and the roles currently open on that team.",
    },
    {
        "key": "publications",
        "label": "Publications / patents",
        "hint": "Papers, patents, or engineering blog posts with their name on them.",
    },
    {
        "key": "company_news",
        "label": "Company news & funding",
        "hint": "Recent funding rounds, launches, or press about the company.",
    },
    {
        "key": "mutual_connections",
        "label": "Mutual connections",
        "hint": "Shared contacts who could make a warm intro.",
    },
    {
        "key": "hiring_criteria",
        "label": "Manager's stated hiring criteria",
        "hint": "What they say they look for - posts, interviews, or JD wording.",
    },
]

_RESEARCH_STATUSES = ("todo", "done", "skipped")


def _research_path():
    return C.DATA_DIR / "hm_research.json"


def _load_research():
    p = _research_path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_research(data):
    p = _research_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def research_checklist(dossier_ref=None):
    """Return checklist items, each with key/label/hint/status/note.

    With no ref (or when candid.hm is unavailable / the ref is unknown),
    returns a bare checklist: everything "todo", nothing persisted.
    When the dossier resolves, persisted per-dossier progress is merged in
    and hints are personalized with the manager's first name.
    """
    items = [
        {"key": it["key"], "label": it["label"], "hint": it["hint"],
         "status": "todo", "note": ""}
        for it in RESEARCH_ITEMS
    ]
    dossier = _lookup_dossier(dossier_ref) if dossier_ref else None
    if not dossier:
        return items
    saved = _load_research().get(str(dossier_ref), {}).get("items", {})
    name = (dossier.get("name") or "").split()
    first = name[0] if name else ""
    for item in items:
        s = saved.get(item["key"])
        if isinstance(s, dict):
            if s.get("status") in _RESEARCH_STATUSES:
                item["status"] = s["status"]
            item["note"] = s.get("note", "") or ""
        if first and item["key"] in ("recent_posts", "mutual_connections",
                                     "hiring_criteria"):
            item["hint"] = "For %s: %s" % (first, item["hint"])
    return items


def checklist_update(ref, key, status, note=""):
    """Persist one checklist item's progress; returns the updated item."""
    valid_keys = {it["key"] for it in RESEARCH_ITEMS}
    if key not in valid_keys:
        raise ValueError("unknown research key: %r (valid: %s)"
                         % (key, sorted(valid_keys)))
    if status not in _RESEARCH_STATUSES:
        raise ValueError("status must be one of %s, got %r"
                         % (_RESEARCH_STATUSES, status))
    data = _load_research()
    ref = str(ref)
    entry = data.setdefault(ref, {"items": {}})
    entry["items"][key] = {"status": status, "note": note or ""}
    _save_research(data)
    template = next(it for it in RESEARCH_ITEMS if it["key"] == key)
    return {
        "key": key,
        "label": template["label"],
        "hint": template["hint"],
        "status": status,
        "note": note or "",
    }


def checklist_status(ref):
    """Summary of research progress: {"done", "total", "items"}."""
    items = [
        {"key": it["key"], "label": it["label"], "hint": it["hint"],
         "status": "todo", "note": ""}
        for it in RESEARCH_ITEMS
    ]
    saved = _load_research().get(str(ref), {}).get("items", {}) if ref else {}
    done = 0
    for item in items:
        s = saved.get(item["key"])
        if isinstance(s, dict):
            if s.get("status") in _RESEARCH_STATUSES:
                item["status"] = s["status"]
            item["note"] = s.get("note", "") or ""
        if item["status"] == "done":
            done += 1
    return {"done": done, "total": len(items), "items": items}

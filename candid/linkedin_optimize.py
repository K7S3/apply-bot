"""LinkedIn profile optimizer: headlines, about section, experience
bullets, and keyword gaps — all grounded in the onboarded profile.

GOLDEN RULE (non-negotiable): never invent titles, companies, metrics,
skills, or achievements. Every suggestion must trace back to the profile
data (name, headline, summary, skills, experience, education, seniority,
domains). Anything we cannot verify becomes a *question*, never a claim.

Functions take the profile dict produced by ``candid.profile`` (see
``candid_data/profile.json``) and return plain data / markdown strings —
no network, no API calls, stdlib only.
"""

from __future__ import annotations

import copy
import re


class LinkedInOptimizeError(Exception):
    """Raised when a profile is missing the data an optimizer step needs."""


HEADLINE_MAX = 220  # LinkedIn's headline character limit

# ---------------------------------------------------------------------------
# keyword lexicon: seniority-appropriate industry keywords, per domain tag
# (domain tags are the keys of profile._DOMAIN_SIGNALS)
# ---------------------------------------------------------------------------

DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "data science": [
        "machine learning", "statistics", "python", "sql",
        "experimentation", "a/b testing", "causal inference",
        "data visualization", "deep learning",
    ],
    "software engineering": [
        "system design", "testing", "ci/cd", "code review",
        "distributed systems", "apis",
    ],
    "ml platform / mlops": [
        "docker", "kubernetes", "airflow", "ci/cd",
        "model deployment", "monitoring",
    ],
    "ads / monetization": [
        "ranking", "recommendations", "experimentation", "a/b testing",
    ],
    "finance": [
        "financial modeling", "risk management", "sql",
    ],
    "product": [
        "roadmap", "a/b testing", "metrics", "stakeholder management",
    ],
    "research": [
        "deep learning", "pytorch", "publications", "statistics",
    ],
    "data engineering": [
        "spark", "dbt", "airflow", "sql", "data modeling", "etl",
    ],
    "consulting": [
        "stakeholder management", "storytelling", "sql",
    ],
}

# keywords recruiters commonly search at a given seniority level
SENIORITY_KEYWORDS: dict[str, list[str]] = {
    "entry": ["internship", "projects", "coursework"],
    "junior": ["code review", "testing", "documentation"],
    "mid": ["mentorship", "system design", "cross-functional"],
    "senior": ["mentorship", "technical leadership", "system design",
               "architecture"],
    "lead": ["technical leadership", "roadmap", "hiring", "architecture"],
    "staff": ["technical strategy", "architecture", "org-level impact"],
    "principal": ["technical strategy", "org-level impact"],
    "director+": ["org design", "hiring", "strategy"],
    "vp+": ["org design", "strategy"],
}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _profile_text(profile: dict) -> str:
    """Everything the profile says, lowercased — the grounded vocabulary."""
    parts = [
        profile.get("name", ""), profile.get("headline", ""),
        profile.get("location", ""), profile.get("summary", ""),
        " ".join(profile.get("skills", [])),
        " ".join(profile.get("domains", [])),
        profile.get("seniority", ""),
    ]
    for e in profile.get("experience", []):
        parts += [e.get("title", ""), e.get("company", ""),
                  e.get("dates", ""), " ".join(e.get("bullets", []))]
    for ed in profile.get("education", []):
        parts += [ed.get("school", ""), ed.get("degree", "")]
    return " ".join(p for p in parts if p)


def _require_experience(profile: dict, what: str) -> list[dict]:
    exp = profile.get("experience") or []
    if not exp:
        raise LinkedInOptimizeError(
            f"Cannot {what}: the profile has no experience entries. "
            "Run onboarding with a resume or LinkedIn export first."
        )
    return exp


def _recent(profile: dict) -> dict:
    return _require_experience(profile, "optimize")[0]


def _title_case_skills(skills: list[str], n: int) -> list[str]:
    display = {"mlops": "MLOps", "sql": "SQL", "ci/cd": "CI/CD",
               "a/b testing": "A/B testing", "dbt": "dbt", "etl": "ETL",
               "apis": "APIs"}
    out = []
    for s in skills[:n]:
        low = s.lower()
        if low in display:
            out.append(display[low])
        elif s.upper() == s or len(s) <= 3:
            out.append(s.upper() if s.isalpha() else s)
        else:
            out.append(s.title())
    return out


def _fit(headline: str) -> str:
    """Trim a headline to LinkedIn's limit without inventing anything."""
    if len(headline) <= HEADLINE_MAX:
        return headline
    return headline[:HEADLINE_MAX - 1].rstrip() + "…"


def _has_skill(profile: dict, keyword: str) -> bool:
    """Is this keyword already covered by the profile's skills?"""
    kw = keyword.lower()
    for skill in profile.get("skills", []):
        s = skill.lower()
        if kw == s or kw in s or s in kw:
            return True
    return False


# ---------------------------------------------------------------------------
# headlines
# ---------------------------------------------------------------------------

def _headline_variants(profile: dict) -> list[str]:
    """Candidate headlines, most factual first. All derive from profile data."""
    exp = _recent(profile)
    title = exp.get("title", "").strip()
    company = exp.get("company", "").strip()
    skills = _title_case_skills(profile.get("skills", []), 4)
    domains = [d.title() for d in profile.get("domains", [])]
    seniority = (profile.get("seniority") or "").rstrip("+")
    seniority_cap = seniority[:1].upper() + seniority[1:] if seniority else ""

    variants: list[str] = []
    if title and skills:
        variants.append(f"{title} | {' · '.join(skills[:3])}")
    if title and company and domains:
        variants.append(f"{title} at {company} | {' · '.join(domains)}")
    if seniority_cap and domains and skills:
        variants.append(
            f"{seniority_cap} {domains[0]} professional | "
            f"{' · '.join(skills[:2])}"
        )
    if title and company and skills:
        variants.append(f"{title} | {company} | {' · '.join(skills[:2])}")
    if domains and skills:
        variants.append(f"{' · '.join(domains)} | {' · '.join(skills[:3])}")
    if title:
        variants.append(title)
    # dedupe, drop empties
    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        v = _fit(v.strip(" |·-"))
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def suggest_headline(profile: dict, n: int = 3) -> list[str]:
    """Return ``n`` headline options, each within LinkedIn's 220-char limit.

    Headlines combine the profile's actual most-recent title, company,
    skills, seniority, and domain tags. No titles or companies are invented.
    """
    if n < 1:
        raise LinkedInOptimizeError("n must be >= 1.")
    variants = _headline_variants(profile)
    if not variants:
        raise LinkedInOptimizeError(
            "Cannot suggest a headline: the profile has no usable "
            "title, skills, or domains."
        )
    # cycle through distinct variants until we have n
    out = list(variants)
    i = 0
    while len(out) < n and variants:
        out.append(variants[i % len(variants)])
        i += 1
    return out[:n]


# ---------------------------------------------------------------------------
# about section
# ---------------------------------------------------------------------------

def _first_bullets(exp: dict, k: int = 2) -> list[str]:
    return [b for b in exp.get("bullets", []) if b][:k]


def _prose(bullets: list[str]) -> str:
    """Turn resume bullets into sentence(s) continuing an 'I ...' lead.

    Only casing is adjusted (first bullet lowercased to follow "I",
    later bullets sentence-cased); no facts are added or reworded.
    """
    sents = []
    for i, bullet in enumerate(bullets):
        s = bullet.strip().rstrip(".")
        if not s:
            continue
        if i == 0:
            s = s[0].lower() + s[1:]
        else:
            s = s[0].upper() + s[1:]
        sents.append(s + ".")
    return " ".join(sents)


def suggest_about(profile: dict, open_to_work: bool = False) -> str:
    """Draft a first-person about section: 2-3 short paragraphs.

    Paragraph 1: who you are (name, seniority, current title/company).
    Paragraph 2: experience arc from the most recent role's real bullets.
    Paragraph 3: skills + education.
    An open-to-work closing line is added ONLY when ``open_to_work=True``.
    """
    exp = _require_experience(profile, "draft an about section")
    recent = exp[0]
    name = profile.get("name", "").strip()
    title = recent.get("title", "").strip()
    company = recent.get("company", "").strip()
    years = profile.get("years_experience") or 0
    seniority = (profile.get("seniority") or "").rstrip("+")
    domains = [d for d in profile.get("domains", [])]
    skills = _title_case_skills(profile.get("skills", []), 6)

    who = f"I'm {name}" if name else "I'm"
    role_bits = [b for b in (title, f"at {company}" if company else "") if b]
    p1 = f"{who}, {' '.join(role_bits)}.".replace("  ", " ")
    if years:
        yrs = f"{round(years)}"
        dom = f" in {', '.join(domains)}" if domains else ""
        p1 += f" I bring about {yrs} years of experience{dom}."
    elif seniority:
        p1 += f" I work as a {seniority}-level professional."
    if not years and not seniority and not role_bits:
        p1 = f"{who}."

    p2 = ""
    bullets = _first_bullets(recent, 2)
    if bullets:
        lead = f"At {company}, I " if company else "Recently, I "
        p2 = lead + _prose(bullets)
    elif len(exp) > 1:
        prev = exp[1]
        pt, pc = prev.get("title", ""), prev.get("company", "")
        p2 = f"Previously, I worked as {pt}".rstrip()
        p2 += f" at {pc}." if pc else "."

    p3_bits = []
    if skills:
        p3_bits.append(f"My toolkit includes {', '.join(skills)}.")
    edu = profile.get("education") or []
    if edu:
        deg = edu[0].get("degree", "").strip()
        sch = edu[0].get("school", "").strip()
        cred = " — ".join(b for b in (deg, sch) if b)
        if cred:
            p3_bits.append(f"Background: {cred}.")
    p3 = " ".join(p3_bits)

    paras = [p for p in (p1.strip(), p2.strip(), p3.strip()) if p]
    if open_to_work:
        target = domains[0] if domains else "new"
        paras.append(
            f"Open to work: I'm exploring {target} roles — "
            "happy to connect if something looks like a fit."
        )
    return "\n\n".join(paras)


# ---------------------------------------------------------------------------
# about-section polisher (voice-preserving rewrite)
# ---------------------------------------------------------------------------

_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_FIRST_PERSON = re.compile(r"\b(i|i'm|i've|i'll|i'd|my|me|mine|myself)\b", re.I)
_THIRD_PERSON = re.compile(r"\b(he|she|his|her|him|hers|they|their|them)\b", re.I)
_CONTRACTIONS = re.compile(
    r"\b(can't|don't|doesn't|won't|it's|i'm|i've|i'll|i'd|we're|they're|"
    r"that's|there's|isn't|aren't|wasn't|weren't|haven't|hasn't|didn't|"
    r"couldn't|wouldn't|shouldn't)\b", re.I)
_FORMAL_MARKERS = re.compile(
    r"\b(utilize|utilizing|furthermore|moreover|henceforth|synergy|"
    r"leverage synergies|paradigm|ideate)\b", re.I)
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # symbols & pictographs
    "\u2600-\u27BF"          # misc symbols, dingbats
    "\u2B00-\u2BFF"
    "\uFE0F"
    "]")

_FILLER_FIXES = [
    (re.compile(r"\bin order to\b", re.I), "to"),
    (re.compile(r"\bdue to the fact that\b", re.I), "because"),
    (re.compile(r"\bin the event that\b", re.I), "if"),
    (re.compile(r"\ba large number of\b", re.I), "many"),
    (re.compile(r"\butilize\b", re.I), "use"),
    (re.compile(r"\butilizing\b", re.I), "using"),
]


def _voice_markers(text: str, name: str = "") -> dict:
    sents = [s for s in _SENT_SPLIT.split(text.strip()) if s.strip()]
    words = re.findall(r"[A-Za-z0-9']+", text)
    avg_len = round(len(words) / len(sents), 1) if sents else 0.0
    fp = len(_FIRST_PERSON.findall(text))
    tp = len(_THIRD_PERSON.findall(text))
    name_hits = (len(re.findall(re.escape(name), text, re.I))
                 if name and len(name) > 2 else 0)
    if fp > tp and fp > name_hits:
        person: str = "first"
    elif name_hits >= fp and name_hits > 0:
        person = "third"
    elif tp >= fp and tp > 0:
        person = "third"
    else:
        person = "first" if fp else "unclear"
    return {
        "sentences": len(sents),
        "avg_sentence_len_words": avg_len,
        "person": person,
        "first_person_markers": fp,
        "third_person_markers": tp + name_hits,
        "has_contractions": bool(_CONTRACTIONS.search(text)),
        "formal_markers": sorted(set(_FORMAL_MARKERS.findall(text)),
                                 key=str.lower),
        "has_emoji": bool(_EMOJI_RE.search(text)),
        "emoji_chars": sorted(set(_EMOJI_RE.findall(text))),
    }


def _voice_notes(markers: dict) -> list[str]:
    notes = []
    notes.append(
        f"Voice: {markers['person']}-person "
        f"({markers['first_person_markers']} first-person vs "
        f"{markers['third_person_markers']} third-person markers)."
    )
    notes.append(
        f"Average sentence length: {markers['avg_sentence_len_words']} words "
        f"across {markers['sentences']} sentences — kept as-is."
    )
    notes.append("Contractions present — informal register preserved."
                 if markers["has_contractions"]
                 else "No contractions — neutral/formal register preserved.")
    if markers["formal_markers"]:
        notes.append("Formal markers kept: "
                     + ", ".join(markers["formal_markers"]) + ".")
    if markers["has_emoji"]:
        notes.append("Emoji preserved: "
                     + " ".join(markers["emoji_chars"]) + ".")
    return notes


def _fix_i_capitalization(text: str) -> tuple[str, int]:
    count = 0

    def _rep(m: re.Match) -> str:
        nonlocal count
        count += 1
        suffix = m.group(2) or ""
        return m.group(1) + "I" + suffix

    new = re.sub(r"(^|[\s(“'\-–—])i('m|'ve|'ll|'d|'re)?\b", _rep, text)
    return new, count


def _fix_sentence_caps(text: str) -> tuple[str, int]:
    count = 0

    def _rep(m: re.Match) -> str:
        nonlocal count
        count += 1
        return m.group(1) + m.group(2).upper()

    new = re.sub(r"([.!?…]\s+)([a-z])", _rep, text)
    if new and new[0].islower():
        new = new[0].upper() + new[1:]
        count += 1
    return new, count


def polish_about(current_text: str, profile: dict) -> dict:
    """Rewrite an existing about section while PRESERVING the user's voice.

    Voice analysis measures: average sentence length, first vs third person,
    formality markers (contractions vs formal words), and emoji use — and the
    rewrite keeps all of them. Only safe, deterministic edits are made:
    whitespace/punctuation cleanup, ``i`` capitalization, sentence-start
    capitalization, and filler-phrase tightening. Profile skills missing from
    the text are injected naturally in a final sentence (only skills already
    in the profile — nothing invented).

    Returns ``{"polished": str, "voice_notes": [...], "changes": [...]}``.
    """
    if not (current_text or "").strip():
        raise LinkedInOptimizeError(
            "Nothing to polish: the current about text is empty.")
    markers = _voice_markers(current_text, profile.get("name", ""))
    notes = _voice_notes(markers)

    text = current_text
    changes: list[str] = []

    new = re.sub(r"[ \t]+", " ", text).strip()
    if new != text:
        changes.append("Normalized whitespace.")
    text = new

    new = re.sub(r"\s+([,.;:!?…])", r"\1", text)
    if new != text:
        changes.append("Removed spaces before punctuation.")
    text = new

    new = re.sub(r"!{2,}", "!", re.sub(r"\?{2,}", "?", text))
    if new != text:
        changes.append("Collapsed repeated punctuation.")
    text = new

    text, n = _fix_i_capitalization(text)
    if n:
        changes.append(f"Capitalized {n} standalone 'i' → 'I'.")

    text, n = _fix_sentence_caps(text)
    if n:
        changes.append(f"Capitalized {n} sentence start(s).")

    filler_hits = 0
    for pat, repl in _FILLER_FIXES:
        text, k = pat.subn(repl, text)
        filler_hits += k
    if filler_hits:
        changes.append(
            f"Tightened {filler_hits} filler phrase(s) "
            "(e.g. 'in order to' → 'to', 'utilize' → 'use').")

    # keyword injection: profile skills absent from the text, in matching voice
    missing = [s for s in profile.get("skills", [])
               if not re.search(r"\b" + re.escape(s) + r"\b",
                                text, re.I)]
    injected = _title_case_skills(missing, 4)
    if injected:
        if markers["person"] == "third":
            name = (profile.get("name") or "They").strip()
            first = name.split()[0] if name else "They"
            sentence = f"{first} works with {', '.join(injected)}."
        elif markers["person"] == "first":
            sentence = f"I work with {', '.join(injected)}."
        else:
            sentence = f"Key skills: {', '.join(injected)}."
        sep = "" if text.rstrip().endswith((".", "!", "?", "…")) else "."
        text = text.rstrip() + sep + " " + sentence
        changes.append(
            "Added a closing line with profile skills missing from the "
            f"text ({', '.join(injected)}) — no new claims, all from the profile."
        )

    if not changes:
        changes.append("No edits needed — text was already clean.")

    return {"polished": text, "voice_notes": notes, "changes": changes}


# ---------------------------------------------------------------------------
# experience
# ---------------------------------------------------------------------------

_CLAIM_RE_TMPL = (
    r"(?:as\s+a(?:n)?|i'?m\s+a(?:n)?|i\s+am\s+a(?:n)?|worked\s+as\s+a(?:n)?|"
    r"work\s+as\s+a(?:n)?)\s+([^.,;|@]{{3,60}}?)\s+at\s+{company}"
)


def _title_claims_in_about(about_text: str, company: str) -> list[str]:
    """Titles the about text claims for a given company ('X at Company')."""
    if not about_text or not company:
        return []
    pat = re.compile(_CLAIM_RE_TMPL.format(company=re.escape(company)), re.I)
    return [m.group(1).strip(" |–—-") for m in pat.finditer(about_text)]


def _distill_bullets(bullets: list[str], k: int = 4) -> list[str]:
    """Pick 3-5 bullets worth putting on LinkedIn, verbatim (trimmed).

    Bullets with numbers/metrics sort first — recruiters skim for them.
    Nothing is reworded: suggestions quote the profile.
    """
    scored = []
    for b in bullets:
        b = (b or "").strip()
        if not b:
            continue
        score = 1 if re.search(r"\d", b) else 0
        scored.append((score, -len(b), b))
    scored.sort(reverse=True)
    out = []
    for _, _, b in scored:
        if len(b) > 220:
            b = b[:217].rstrip() + "..."
        out.append(b)
        if len(out) >= k:
            break
    return out


def _skills_for_role(profile: dict, entry: dict) -> list[str]:
    hay = " ".join([entry.get("title", ""), entry.get("company", ""),
                    " ".join(entry.get("bullets", []))]).lower()
    return [s for s in profile.get("skills", [])
            if re.search(r"\b" + re.escape(s) + r"\b", hay, re.I)]


def suggest_experience(profile: dict, about_text: str = "") -> list[dict]:
    """Per-role LinkedIn experience suggestions.

    For each role: a clean LinkedIn title line, a title check (flags
    inflation when ``about_text`` claims a different title at the same
    company), 3-5 bullet suggestions distilled verbatim from the resume
    bullets, and profile skills to tag for the role.
    """
    exp = _require_experience(profile, "suggest experience bullets")
    out = []
    for entry in exp:
        title = (entry.get("title") or "").strip()
        company = (entry.get("company") or "").strip()
        dates = (entry.get("dates") or "").strip()

        flags: list[str] = []
        if not title:
            flags.append("Title is missing — LinkedIn needs one.")
        if not company:
            flags.append("Company is missing — LinkedIn needs one.")
        for claimed in _title_claims_in_about(about_text, company):
            if _norm(claimed) and _norm(claimed) != _norm(title) \
                    and _norm(claimed) not in _norm(title) \
                    and _norm(title) not in _norm(claimed):
                flags.append(
                    f"Title mismatch at {company or 'this role'}: the about "
                    f"text claims '{claimed}' but the profile says "
                    f"'{title}'. Pick one — recruiters notice."
                )

        title_line = " | ".join(p for p in (title, company) if p)
        out.append({
            "title": title,
            "company": company,
            "dates": dates,
            "title_line": title_line,
            "flags": flags,
            "bullet_suggestions": _distill_bullets(
                entry.get("bullets", []), k=4),
            "skills_to_tag": _skills_for_role(profile, entry),
        })
    return out


# ---------------------------------------------------------------------------
# keyword gaps
# ---------------------------------------------------------------------------

def keyword_gaps(profile: dict) -> list[dict]:
    """Compare profile skills against seniority-appropriate industry keywords.

    Returns missing keywords as "consider adding if true" suggestions —
    the profile is NEVER modified. Each item is
    ``{"keyword", "source", "why", "note"}``.
    """
    _ = copy.deepcopy(profile)  # prove we don't mutate: work on nothing
    gaps: list[dict] = []
    seen: set[str] = set()

    def _add(keyword: str, source: str, why: str) -> None:
        key = keyword.lower()
        if key in seen or _has_skill(profile, keyword):
            return
        seen.add(key)
        gaps.append({
            "keyword": keyword,
            "source": source,
            "why": why,
            "note": "Consider adding this to your LinkedIn skills ONLY if "
                    "it is true of your experience — never list skills you "
                    "don't have.",
        })

    for domain in profile.get("domains", []):
        for kw in DOMAIN_KEYWORDS.get(domain, []):
            _add(kw, f"domain: {domain}",
                 f"Commonly listed by people in {domain}.")
    seniority = (profile.get("seniority") or "").lower()
    for kw in SENIORITY_KEYWORDS.get(seniority, []):
        _add(kw, f"seniority: {seniority}",
             f"Recruiters often search {seniority}-level candidates for this.")
    return gaps


# ---------------------------------------------------------------------------
# full report
# ---------------------------------------------------------------------------

def full_report(profile: dict, open_to_work: bool = False,
                about_text: str = "") -> str:
    """Render headline + about + experience + keyword gaps as markdown."""
    name = profile.get("name") or "your"
    lines = [f"# LinkedIn optimization report — {name}", ""]

    lines.append("## Headline options")
    lines.append("Pick one (all ≤ 220 characters):")
    for i, h in enumerate(suggest_headline(profile), 1):
        lines.append(f"{i}. {h}")
    lines.append("")

    lines.append("## About section")
    lines.append(suggest_about(profile, open_to_work=open_to_work))
    lines.append("")

    lines.append("## Experience")
    for role in suggest_experience(profile, about_text=about_text):
        lines.append(f"### {role['title_line'] or '(untitled role)'}")
        if role["dates"]:
            lines.append(f"*{role['dates']}*")
        for f in role["flags"]:
            lines.append(f"- ⚠️ {f}")
        if role["bullet_suggestions"]:
            lines.append("Suggested bullets (from your resume, verbatim):")
            for b in role["bullet_suggestions"]:
                lines.append(f"- {b}")
        if role["skills_to_tag"]:
            lines.append("Skills to tag: "
                         + ", ".join(role["skills_to_tag"]))
        lines.append("")

    lines.append("## Keyword gaps")
    gaps = keyword_gaps(profile)
    if gaps:
        lines.append("Missing from your skills — add only if true:")
        for g in gaps:
            lines.append(f"- **{g['keyword']}** ({g['source']}) — {g['why']}")
    else:
        lines.append("No gaps found against the keyword lexicon. Nice.")
    lines.append("")
    lines.append("_Every suggestion above traces to your onboarded profile. "
                 "Nothing was invented._")
    return "\n".join(lines)

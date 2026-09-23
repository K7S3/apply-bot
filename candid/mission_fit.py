"""Mission-fit scoring: measure how well a posting's cause/mission aligns with
the user's stated cause interests.

Pure local keyword logic - no network, no models. `classify_causes` scores a
job description against a cause-area taxonomy; `mission_fit_score` compares
the detected causes against the profile's "cause_interests" list:

    score = 60 * overlap_strength + 40 * cause_signal_clarity

  - overlap_strength: mean score of the JD-detected causes that appear in
    the user's cause_interests (0 if none).
  - cause_signal_clarity: mean score of the JD's top-3 detected causes - how
    clearly the posting signals any mission at all.

If the profile has no cause_interests, no fake number is produced: the score
is None with a note asking the user to set their interests first. If the JD
carries no cause signal, the score is low and the note says it reads like a
for-profit posting.
"""

from __future__ import annotations

import re

# cause-area key -> lowercase keywords/phrases (10-25 each). Single words are
# matched on word boundaries; multi-word phrases as substrings.
CAUSE_AREAS: dict[str, list[str]] = {
    "education": [
        "education", "school", "schools", "teacher", "teachers", "teaching",
        "student", "students", "classroom", "literacy", "curriculum",
        "tutoring", "mentor", "mentorship", "learning", "scholarship",
        "scholarships", "k-12", "higher education", "college access",
        "stem education", "edtech", "dropout", "educational equity",
    ],
    "health": [
        "health", "healthcare", "health care", "hospital", "hospitals",
        "clinic", "clinics", "public health", "patient", "patients",
        "medical", "medicine", "mental health", "wellness", "disease",
        "vaccine", "vaccination", "maternal health", "global health",
        "health equity", "telemedicine", "epidemiology",
    ],
    "climate_environment": [
        "climate", "climate change", "environment", "environmental",
        "sustainability", "sustainable", "conservation", "renewable",
        "renewable energy", "solar", "wind energy", "carbon", "emissions",
        "deforestation", "biodiversity", "ocean", "pollution", "recycling",
        "clean energy", "green energy", "zero waste", "ecosystem",
        "climate justice", "reforestation", "circular economy",
    ],
    "human_rights": [
        "human rights", "civil rights", "civil liberties", "justice",
        "advocacy", "refugee", "refugees", "asylum", "immigration",
        "migrant", "discrimination", "legal aid", "aclu",
        "freedom of speech", "voting rights", "due process", "torture",
        "political prisoners", "displacement", "stateless",
    ],
    "poverty_hunger": [
        "poverty", "hunger", "food insecurity", "food bank", "food banks",
        "homeless", "homelessness", "shelter", "soup kitchen", "nutrition",
        "malnutrition", "welfare", "basic needs", "living wage",
        "affordable housing", "food desert", "snap benefits", "eviction",
        "unhoused", "subsistence",
    ],
    "disaster_relief": [
        "disaster relief", "disaster", "emergency response", "humanitarian",
        "red cross", "fema", "relief efforts", "natural disaster",
        "earthquake", "hurricane", "flood relief", "wildfire", "crisis",
        "emergency aid", "first responders", "rescue", "evacuation",
        "recovery efforts", "war zone", "conflict zone",
    ],
    "animals": [
        "animal", "animals", "wildlife", "shelter animals", "adoption",
        "spay", "neuter", "veterinary", "vet clinic", "endangered",
        "conservation", "habitat", "poaching", "animal cruelty",
        "humane society", "aspca", "rescue animals", "sanctuary",
        "marine life", "biodiversity",
    ],
    "arts_culture": [
        "arts", "art", "culture", "cultural", "museum", "museums",
        "theater", "theatre", "music", "dance", "film", "cinema",
        "literature", "poetry", "gallery", "exhibition", "heritage",
        "preservation", "creative", "artists", "performing arts",
        "public art", "storytelling", "folklore",
    ],
    "economic_development": [
        "economic development", "microfinance", "microloans", "small business",
        "entrepreneurship", "job training", "workforce development",
        "financial inclusion", "unbanked", "livelihood", "income",
        "employment", "cooperative", "credit union", "savings group",
        "village savings", "economic empowerment", "fair trade",
        "supply chain", "informal economy",
    ],
    "peace_conflict": [
        "peace", "peacebuilding", "conflict", "conflict resolution",
        "ceasefire", "diplomacy", "mediation", "reconciliation",
        "post-conflict", "war", "violence", "gun violence",
        "community safety", "deradicalization", "peacekeeping",
        "arms", "disarmament", "negotiation", "dialogue", "nonviolence",
    ],
    "gender_equality": [
        "gender", "women", "girls", "feminism", "feminist",
        "gender equality", "women's rights", "reproductive",
        "reproductive health", "maternal", "domestic violence",
        "gender-based violence", "child marriage", "female genital",
        "women's empowerment", "girl child", "sexism", "misogyny",
        "paid leave", "childcare",
    ],
    "tech_for_good": [
        "tech for good", "civic tech", "open source", "open data",
        "digital divide", "digital literacy", "internet access",
        "connectivity", "ai for good", "data for good", "nonprofit tech",
        "social impact", "civic engagement", "e-governance",
        "digital inclusion", "tech equity", "community tech",
        "accessible technology", "assistive technology", "open science",
    ],
}


def _kw_pattern(kw: str) -> str:
    """Regex for one keyword: word-boundary match, case handled by caller."""
    return r"\b" + re.escape(kw.strip().lower()) + r"\b"


def classify_causes(text: str) -> list[tuple[str, float]]:
    """Score text against each cause area.

    A cause area's score is the fraction of its keyword list that matched
    (distinct keywords, normalized by list size so large lists don't
    dominate). Returns (area, 0-1 score) sorted by score descending, only for
    areas with at least one hit.
    """
    text = (text or "").lower()
    if not text.strip():
        return []
    scored: list[tuple[str, float]] = []
    for area, keywords in CAUSE_AREAS.items():
        hits = 0
        for kw in keywords:
            if re.search(_kw_pattern(kw), text):
                hits += 1
        if hits:
            scored.append((area, round(hits / len(keywords), 3)))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored


def mission_fit_score(jd_text: str, profile: dict) -> dict:
    """Score mission fit 0-100 from JD cause signals vs user cause interests.

    profile may carry "cause_interests": a list of CAUSE_AREAS keys. Returns
    a dict with keys: score (int 0-100, or None), matched_causes,
    top_jd_causes, note. Unknown interest keys are ignored. Deterministic.
    """
    interests = [i for i in (profile or {}).get("cause_interests", []) or []
                 if i in CAUSE_AREAS]
    jd_causes = classify_causes(jd_text)
    top_jd_causes = [area for area, _ in jd_causes[:3]]
    matched = [(area, score) for area, score in jd_causes if area in interests]
    matched_causes = [area for area, _ in matched]

    if not (profile or {}).get("cause_interests"):
        return {
            "score": None,
            "matched_causes": matched_causes,
            "top_jd_causes": top_jd_causes,
            "note": "set cause interests to enable mission-fit scoring",
        }

    if not jd_causes:
        return {
            "score": 0,
            "matched_causes": matched_causes,
            "top_jd_causes": top_jd_causes,
            "note": (
                "No clear mission or cause signal detected in this posting; "
                "it reads like a for-profit or generic corporate role, so "
                "mission fit is 0 regardless of your interests."
            ),
        }

    overlap_strength = sum(s for _, s in matched) / len(matched) if matched else 0.0
    clarity = sum(s for _, s in jd_causes[:3]) / min(3, len(jd_causes))
    score = round(60 * overlap_strength + 40 * clarity)
    score = max(0, min(100, score))

    if matched_causes:
        note = (
            f"Overlaps with your interests in {', '.join(matched_causes)}; "
            f"the posting signals {', '.join(top_jd_causes)}."
        )
    else:
        note = (
            f"No overlap with your cause interests; the posting signals "
            f"{', '.join(top_jd_causes)}."
        )
    return {
        "score": score,
        "matched_causes": matched_causes,
        "top_jd_causes": top_jd_causes,
        "note": note,
    }


def render_mission_fit(result: dict) -> str:
    """Render one compact human-readable block for CLI display."""
    lines = ["Mission fit"]
    score = result.get("score")
    if score is None:
        lines.append("  score: n/a")
    else:
        lines.append(f"  score: {score}/100")
    top = result.get("top_jd_causes") or []
    lines.append(f"  JD cause signals: {', '.join(top) if top else 'none detected'}")
    matched = result.get("matched_causes") or []
    lines.append(f"  matched interests: {', '.join(matched) if matched else 'none'}")
    note = result.get("note") or ""
    if note:
        lines.append(f"  note: {note}")
    return "\n".join(lines)

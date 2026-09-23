"""Tests for candid.pivot (career-pivot reframing).

Covers: pivots ranked by transferable-skill overlap; reframe output contains
no skill/company/metric absent from the input profile; credibility gaps are
non-empty and honest for a distant pivot; pivot_plan steps are concrete
(each with a verifiable "Deliverable:" outcome); angle changes but facts
don't (titles, companies, dates appear verbatim).

Run: python3 -m pytest tests/test_pivot.py -q
"""
import os
import sys
from pathlib import Path

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-pivot"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from candid import config as C  # noqa: E402
from candid import pivot  # noqa: E402


def _backend_profile(**kw):
    prof = {
        "name": "Jordan Lee",
        "headline": "Backend Engineer",
        "location": "New York, NY",
        "summary": "Backend engineer with 7 years of experience.",
        "skills": ["python", "sql", "cloud", "mlops", "javascript"],
        "experience": [
            {"title": "Backend Engineer", "company": "Acme Corp",
             "dates": "2021 - Present",
             "bullets": [
                 "Built REST APIs in Python serving 10k rps",
                 "Migrated Postgres to the cloud, cutting costs 20%",
                 "Added Docker-based CI that cut deploy time 40%",
             ]},
            {"title": "Software Engineer", "company": "Beta LLC",
             "dates": "2019 - 2021",
             "bullets": [
                 "Wrote SQL ETL jobs processing 2M rows daily",
                 "Built internal dashboards in React",
             ]},
        ],
        "education": [{"school": "State University",
                       "degree": "B.S. Computer Science",
                       "dates": "2015 - 2019"}],
        "years_experience": 7.0,
        "seniority": "senior",
        "source_files": [],
    }
    prof.update(kw)
    return prof


def _skills_mentioned(text, vocab):
    """Canonical lexicon skills from vocab mentioned in text."""
    low = text.lower()
    return {s for s in vocab
            if any(C.skill_regex(a).search(low)
                   for a in C.SKILL_LEXICON.get(s, [s]))}


# ---------------------------------------------------------------------------
# suggest_pivots
# ---------------------------------------------------------------------------

def test_suggest_pivots_ranked_by_overlap():
    p = _backend_profile()
    sugs = pivot.suggest_pivots(p, n=5)
    assert sugs, "expected pivot suggestions for a backend engineer"
    pcts = [s["overlap_pct"] for s in sugs]
    assert pcts == sorted(pcts, reverse=True), "not ranked by overlap desc"
    targets = [s["target"] for s in sugs]
    assert "platform engineer" in targets
    assert "devops engineer" in targets


def test_suggest_pivot_fields_grounded():
    p = _backend_profile()
    pset = set(p["skills"])
    for s in pivot.suggest_pivots(p):
        assert {"target", "overlap_pct", "transferable", "gaps", "why"} <= set(s)
        assert set(s["transferable"]) <= pset, "transferable skill not in profile"
        assert not (set(s["gaps"]) & pset), "gap skill is actually in profile"
        assert 0.0 <= s["overlap_pct"] <= 100.0
        assert s["why"], "known target should explain why"


def test_suggest_unknown_title_does_not_crash():
    p = _backend_profile(headline="Cobol Wizard",
                         experience=[{"title": "Cobol Wizard",
                                      "company": "Old Bank",
                                      "dates": "2000 - 2010",
                                      "bullets": ["Maintained ledgers"]}])
    sugs = pivot.suggest_pivots(p, n=3)
    assert len(sugs) == 3


def test_suggest_pivots_respects_n():
    p = _backend_profile()
    assert len(pivot.suggest_pivots(p, n=2)) == 2


# ---------------------------------------------------------------------------
# reframe: groundedness
# ---------------------------------------------------------------------------

def test_reframe_invents_nothing():
    p = _backend_profile()
    r = pivot.reframe(p, "platform engineer")
    pset = set(p["skills"])
    vocab = set(C.SKILL_LEXICON)

    # summary + angles + foreground may only mention skills in the profile
    summary = r["reframed_summary"]
    assert _skills_mentioned(summary, vocab) <= pset, summary
    for role in r["roles"]:
        assert _skills_mentioned(role["angle"], vocab) <= pset, role["angle"]
    assert set(r["skills_to_foreground"]) <= pset

    # bullets are verbatim: same multiset, only reordered
    for role, entry in zip(r["roles"], p["experience"]):
        assert sorted(role["bullets"]) == sorted(entry["bullets"]), \
            "bullet text changed during reframing"

    # only profile companies appear on roles
    companies = {e["company"] for e in p["experience"]}
    assert all(role["company"] in companies for role in r["roles"])
    assert all(role["title"] in {e["title"] for e in p["experience"]}
               for role in r["roles"])


def test_reframe_facts_verbatim_in_brief():
    p = _backend_profile()
    brief = pivot.pivot_brief(p, "devops engineer")
    for e in p["experience"]:
        assert e["title"] in brief
        assert e["company"] in brief
        assert e["dates"] in brief
        for b in e["bullets"]:
            assert b in brief, f"bullet lost from brief: {b}"
    # metrics survive reframing
    assert "10k rps" in brief
    assert "40%" in brief


def test_reframe_foreground_matches_target_needs():
    p = _backend_profile()
    r = pivot.reframe(p, "platform engineer")
    assert set(r["skills_to_foreground"]) == {"python", "cloud", "mlops", "sql"}
    assert any("dbt" in g or "product analytics" in g
               for g in r["credibility_gaps"]) is False  # not platform needs
    # devops target needs mlops/cloud/python/sql - all present -> no skill gaps
    r2 = pivot.reframe(p, "devops engineer")
    assert r2["gap_skills"] == []


def test_distant_pivot_gaps_are_honest_and_nonempty():
    p = _backend_profile()
    r = pivot.reframe(p, "clinical nurse")
    assert r["credibility_gaps"], "distant pivot must surface gaps"
    assert all("you'd need to address" in g for g in r["credibility_gaps"])
    assert r["skills_to_foreground"] == []
    assert "far pivot" in r["honest_read"].lower()
    # the brief must not imply qualification
    brief = pivot.pivot_brief(p, "clinical nurse")
    assert "you'd need to address" in brief


def test_reframe_empty_target_raises():
    with pytest.raises(pivot.PivotError):
        pivot.reframe(_backend_profile(), "   ")


# ---------------------------------------------------------------------------
# pivot_plan
# ---------------------------------------------------------------------------

def test_pivot_plan_steps_are_concrete():
    p = _backend_profile()
    plan = pivot.pivot_plan(p, "data scientist")
    phases = {s["phase"] for s in plan["steps"]}
    assert {"30", "60", "90"} <= phases, "plan must cover 30/60/90 days"
    for s in plan["steps"]:
        assert s["action"].strip(), "step action must be concrete, not empty"
        assert s["outcome"].lower().startswith("deliverable:"), \
            f"step lacks a verifiable outcome: {s}"
        assert s["addresses"].strip(), "step must name what it addresses"


def test_pivot_plan_derives_from_gaps():
    p = _backend_profile()
    r = pivot.reframe(p, "data scientist")
    plan = pivot.pivot_plan(p, "data scientist")
    addressed = {s["addresses"] for s in plan["steps"]}
    for g in r["gap_skills"]:
        assert g in addressed, f"gap '{g}' has no plan step"


def test_pivot_plan_no_vague_steps():
    p = _backend_profile()
    plan = pivot.pivot_plan(p, "solutions architect")
    vague = ("learn leadership", "get better", "try harder", "improve skills")
    for s in plan["steps"]:
        low = (s["action"] + " " + s["outcome"]).lower()
        assert not any(v in low for v in vague)


# ---------------------------------------------------------------------------
# pivot_brief
# ---------------------------------------------------------------------------

def test_pivot_brief_combines_reframe_gaps_plan():
    p = _backend_profile()
    brief = pivot.pivot_brief(p, "platform engineer")
    assert brief.startswith("# Pivot brief:")
    assert "platform engineer" in brief
    assert "## Reframed summary" in brief
    assert "## Credibility gaps" in brief
    assert "## 30/60/90-day plan" in brief
    assert "### Days 30" in brief and "### Days 90" in brief
    assert "Deliverable:" in brief

"""Tests for candid.redteam: adversarial resume review.

Every assertion guards the golden rule: findings must quote the input and
never invent facts about the candidate.
"""

import pytest

from candid import redteam as RT
from candid.redteam import RedTeamError


@pytest.fixture
def planted_resume():
    return """# Keshavan Seshadri
Software Engineer, Machine Learning

## Summary
Passionate self-starter leveraging synergies to disrupt machine learning.

## Experience
Senior ML Engineer - Acme Corp, Mar 2022 - Jan 2020
- Responsible for various machine learning tasks and model stuff.
- Increased revenue by 50%.
- Led migration of the ads ranking pipeline to a new serving stack, cutting p99 latency from 120ms to 40ms across 2B daily requests.

ML Engineer - Beta Inc, Jan 2018 - Dec 2019
- Built and shipped the experimentation platform used by 30 product teams.

## Skills
Python, PyTorch, SQL, Kubernetes

## Hobbies & Quirky Facts
Table tennis champion of building C.
"""


@pytest.fixture
def planted_profile():
    return {
        "name": "Keshavan Seshadri",
        "summary": "Senior machine learning engineer.",
        "skills": ["python", "machine learning"],
        "experience": [
            {"title": "Senior ML Engineer", "company": "Acme Corp",
             "dates": "Mar 2022 - Jan 2020",
             "bullets": ["Responsible for various machine learning tasks."]},
            {"title": "ML Engineer", "company": "Beta Inc",
             "dates": "Jan 2018 - Dec 2019",
             "bullets": ["Built and shipped the experimentation platform."]},
        ],
        "education": [],
        "years_experience": 4.0,
        "seniority": "mid",
    }


class TestReviewMarkdown:
    def test_finds_planted_issues(self, planted_resume):
        findings = RT.review(planted_resume)
        by_cat = {f["category"]: f for f in findings}
        assert by_cat["vague-bullet"]["severity"] == "medium"
        assert by_cat["inconsistency"]["severity"] == "high"      # end before start
        assert by_cat["buzzword-density"]["severity"] in ("low", "medium")
        assert by_cat["overclaim-risk"]["severity"] == "medium"   # 50% w/o context
        assert by_cat["ats-risk"]["severity"] in ("low", "medium")  # "Hobbies & Quirky Facts"

    def test_strong_bullet_not_flagged(self, planted_resume):
        findings = RT.review(planted_resume)
        strong = "cutting p99 latency from 120ms to 40ms"
        flagged = [f for f in findings if strong in f["quote"]]
        # The strong bullet has scope/context, so no overclaim or vague flag.
        assert not any(f["category"] in ("vague-bullet", "overclaim-risk")
                       for f in flagged)

    def test_every_finding_quotes_input(self, planted_resume):
        findings = RT.review(planted_resume)
        assert findings, "expected planted issues to be found"
        for f in findings:
            assert f["quote"], f"missing quote: {f}"
            assert f["quote"].strip() in planted_resume, \
                f"quote not verbatim from input: {f['quote']!r}"

    def test_verify_items_never_accuse(self, planted_resume):
        findings = RT.review(planted_resume)
        for f in findings:
            text = (f["critique"] + " " + f["fix"]).lower()
            assert "you lied" not in text
            assert "lying" not in text
            assert " fabricated" not in text
        overclaim = next(f for f in findings if f["category"] == "overclaim-risk")
        assert "verify" in overclaim["critique"].lower() or \
               "?" in overclaim["critique"] or "question" in overclaim["critique"].lower()

    def test_rejects_bad_input(self):
        with pytest.raises(RedTeamError):
            RT.review("")
        with pytest.raises(RedTeamError):
            RT.review("too short")
        with pytest.raises(RedTeamError):
            RT.review(123)

    def test_clean_resume_has_few_findings(self):
        clean = """# Jane Doe
## Experience
Data Scientist - Acme, Jan 2020 - Present
- Built churn model that reduced customer attrition from 8% to 5% over 12 months across 200k subscribers.
## Skills
Python, SQL
"""
        findings = RT.review(clean)
        assert not any(f["severity"] == "high" for f in findings)


class TestReviewProfile:
    def test_profile_input(self, planted_profile):
        findings = RT.review(planted_profile)
        by_cat = {f["category"]: f for f in findings}
        assert by_cat["vague-bullet"]["severity"] == "medium"
        assert by_cat["inconsistency"]["severity"] == "high"
        assert by_cat["gap-explanation"]["severity"] == "low"
        for f in findings:
            # quotes come from profile text
            assert f["quote"]
            blob = " ".join(
                [planted_profile["summary"]]
                + [b for e in planted_profile["experience"]
                   for b in e["bullets"]]
                + [f"{e['title']} - {e['company']}, {e['dates']}"
                   for e in planted_profile["experience"]])
            assert f["quote"].strip() in blob

    def test_gap_detection(self):
        profile = {
            "summary": "", "skills": [],
            "experience": [
                {"title": "A", "company": "X", "dates": "Jan 2020 - Jun 2020",
                 "bullets": ["Did things."]},
                {"title": "B", "company": "Y", "dates": "Jun 2022 - Present",
                 "bullets": ["Did more things."]},
            ],
            "education": [],
        }
        findings = RT.review(profile)
        gaps = [f for f in findings if f["category"] == "gap-explanation"]
        assert gaps, "expected a ~2-year gap to be flagged"
        assert "neutral" in gaps[0]["critique"].lower() or \
               "life happens" in gaps[0]["critique"].lower()

    def test_title_conflict_same_company(self):
        profile = {
            "summary": "", "skills": [],
            "experience": [
                {"title": "Engineer", "company": "Acme",
                 "dates": "Jan 2020 - Dec 2021", "bullets": ["Did things."]},
                {"title": "Manager", "company": "Acme",
                 "dates": "Jun 2021 - Present", "bullets": ["Did things."]},
            ],
            "education": [],
        }
        findings = RT.review(profile)
        assert any(f["category"] == "inconsistency" and f["severity"] == "medium"
                   for f in findings)


class TestSummaryAndFixes:
    def test_summary_is_nonempty_five_lines(self, planted_resume):
        findings = RT.review(planted_resume)
        summary = RT.hiring_manager_summary(findings)
        assert summary.strip()
        assert len(summary.strip().splitlines()) == 5
        assert "verdict" in summary.lower()

    def test_summary_clean_input(self):
        summary = RT.hiring_manager_summary([])
        assert summary.strip()
        assert "SURVIVES" in summary

    def test_prioritized_fixes_ordered(self, planted_resume):
        findings = RT.review(planted_resume)
        fixes = RT.prioritized_fixes(findings)
        assert 1 <= len(fixes) <= 5
        sev_rank = {"high": 0, "medium": 1, "low": 2}
        ranks = [sev_rank[f["severity"]] for f in fixes]
        assert ranks == sorted(ranks), "fixes must be ordered by severity"
        assert fixes[0]["severity"] == "high"  # the date inconsistency leads
        for f in fixes:
            assert set(f) == {"severity", "category", "quote", "fix"}

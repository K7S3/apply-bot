"""Tests for candid.switch_narrative and candid.switch_pivot.

Covers: bullet reframing through a target-role lens, the career story arc,
the pivot resume (functional/hybrid) template, and the pivot cover header.
Includes groundedness tests: reframed output must never introduce numbers,
tool names, or other facts that were not in the input.

Pytest style: classes with plain asserts.
Run: cd ~/workspace/candid-batch89 && python -m pytest tests/test_switch_narrative.py -q
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

BULLETS = [
    "Built Tableau dashboards used by 200 analysts, cutting report turnaround by 40%",
    "Led a 5-person team to ship the billing API two weeks ahead of schedule",
    "Presented quarterly findings to 40 stakeholders and wrote the exec summary doc",
    "Automated the ETL pipeline with Python and dbt, saving $120k per year",
]

ROLES = [
    {"title": "Data Analyst", "company": "Initech", "dates": "2021 - 2023",
     "highlights": ["Built Tableau dashboards used by 200 analysts",
                     "Presented quarterly findings to 40 stakeholders"]},
    {"title": "Analytics Lead", "company": "Globex", "dates": "2023 - Present",
     "highlights": ["Led a 5-person team to ship the billing API two weeks ahead of schedule"]},
]

TOOLS = ["Tableau", "Python", "dbt"]


def _profile(**kw):
    prof = {
        "name": "Test User",
        "location": "New York, NY",
        "email": "test@example.com",
        "headline": "Analytics Lead",
        "seniority": "mid",
        "years_experience": 5.0,
        "skills": ["python", "sql", "tableau"],
        "experience": [
            {"title": "Data Analyst", "company": "Initech", "dates": "2021 - 2023",
             "bullets": BULLETS[:2]},
            {"title": "Analytics Lead", "company": "Globex", "dates": "2023 - Present",
             "bullets": BULLETS[2:]},
        ],
        "education": [{"degree": "B.S. Statistics", "institution": "State University"}],
    }
    prof.update(kw)
    return prof


def _numbers(text):
    return re.findall(r"\$?\d[\d,.]*%?", text)


def _supplied_numbers():
    """Every number-bearing fact the modules are allowed to echo."""
    parts = list(BULLETS)
    for r in ROLES:
        parts.append(r.get("dates", ""))
        parts.extend(r.get("highlights", []))
    return set(_numbers(" ".join(parts)))


# --------------------------------------------------------------------------
# switch_narrative: reframe_bullets
# --------------------------------------------------------------------------

class TestReframeBullets:
    def test_preserves_bullet_count(self):
        from candid.switch_narrative import reframe_bullets
        out = reframe_bullets(BULLETS, "Product Manager")
        assert len(out) == len(BULLETS)

    def test_original_fact_text_preserved_verbatim(self):
        from candid.switch_narrative import reframe_bullets
        for orig, new in zip(BULLETS, reframe_bullets(BULLETS, "Product Manager")):
            cleaned = re.sub(r"\s+", " ", orig).strip().rstrip(".")
            assert cleaned in new

    def test_lens_prefix_names_transferable_competency(self):
        from candid.switch_narrative import reframe_bullets
        out = reframe_bullets(BULLETS, "Product Manager")
        joined = " ".join(out)
        assert "Stakeholder" in joined  # stakeholder-alignment frame fires
        assert "Shipping" in joined or "Data-informed" in joined

    def test_lens_changes_with_target_role(self):
        from candid.switch_narrative import reframe_bullets
        pm = reframe_bullets(BULLETS, "Product Manager")
        ds = reframe_bullets(BULLETS, "Data Scientist")
        assert pm != ds

    def test_unknown_role_falls_back_to_generic_lens(self):
        from candid.switch_narrative import reframe_bullets
        out = reframe_bullets(BULLETS, "Astronaut")
        assert len(out) == len(BULLETS)
        assert all(orig.rstrip(".") in new for orig, new in zip(BULLETS, out))

    def test_empty_bullets_returns_empty(self):
        from candid.switch_narrative import reframe_bullets
        assert reframe_bullets([], "Product Manager") == []

    def test_empty_role_raises(self):
        from candid.switch_narrative import reframe_bullets, SwitchNarrativeError
        for bad in ("", "   ", None):
            try:
                reframe_bullets(BULLETS, bad)
            except SwitchNarrativeError:
                pass
            else:
                raise AssertionError(f"no error for target_role={bad!r}")

    def test_bad_bullet_types_raise(self):
        from candid.switch_narrative import reframe_bullets, SwitchNarrativeError
        for bad in ("not a list", ["ok", 42], ["ok", "  "]):
            try:
                reframe_bullets(bad, "Product Manager")
            except SwitchNarrativeError:
                pass
            else:
                raise AssertionError(f"no error for bullets={bad!r}")


class TestGroundedness:
    def test_no_new_numbers_in_reframed_bullets(self):
        from candid.switch_narrative import reframe_bullets
        out = reframe_bullets(BULLETS, "Product Manager")
        in_nums = set(_numbers(" ".join(BULLETS)))
        out_nums = set(_numbers(" ".join(out)))
        assert out_nums <= in_nums, f"new numbers: {out_nums - in_nums}"

    def test_no_new_numbers_in_story_arc(self):
        from candid.switch_narrative import career_story_arc
        arc = career_story_arc(ROLES, "Product Manager")
        in_nums = _supplied_numbers()
        out_nums = set(_numbers(arc))
        assert out_nums <= in_nums, f"new numbers: {out_nums - in_nums}"

    def test_tools_come_only_from_input(self):
        from candid.switch_narrative import reframe_bullets
        out = reframe_bullets(BULLETS, "Product Manager")
        for tool in TOOLS:
            if tool in " ".join(out):
                assert tool in " ".join(BULLETS)

    def test_no_new_numbers_in_pivot_resume(self):
        from candid.switch_pivot import build_pivot_resume
        md = build_pivot_resume(_profile(), "Product Manager")
        in_nums = _supplied_numbers()
        out_nums = set(_numbers(md))
        assert out_nums <= in_nums, f"new numbers: {out_nums - in_nums}"

    def test_story_arc_adds_no_new_companies_or_titles(self):
        from candid.switch_narrative import career_story_arc
        target = "Product Manager"
        arc = career_story_arc(ROLES, target)
        supplied_words = set()
        for r in ROLES:
            supplied_words.update(
                " ".join([r["title"], r["company"], r.get("dates", "")]
                         + list(r.get("highlights", []))).split())
        supplied_words.update(target.split())
        connectors = {"I", "From", "The", "That", "So"}
        for word in re.findall(r"[A-Z][a-zA-Z]+", arc):
            assert word in supplied_words or word in connectors, \
                f"new capitalized word not in input: {word}"


# --------------------------------------------------------------------------
# switch_narrative: career_story_arc
# --------------------------------------------------------------------------

class TestCareerStoryArc:
    def test_arc_mentions_every_role(self):
        from candid.switch_narrative import career_story_arc
        arc = career_story_arc(ROLES, "Product Manager")
        assert "Data Analyst" in arc and "Initech" in arc
        assert "Analytics Lead" in arc and "Globex" in arc

    def test_arc_uses_supplied_facts(self):
        from candid.switch_narrative import career_story_arc
        arc = career_story_arc(ROLES, "Product Manager")
        assert "Tableau dashboards used by 200 analysts" in arc
        assert "5-person team" in arc

    def test_arc_names_target_role_and_closes(self):
        from candid.switch_narrative import career_story_arc
        arc = career_story_arc(ROLES, "Product Manager")
        assert "Product Manager" in arc
        assert "looking to bring" in arc

    def test_arc_has_common_thread(self):
        from candid.switch_narrative import career_story_arc
        arc = career_story_arc(ROLES, "Product Manager")
        assert "common thread" in arc

    def test_single_role_arc_still_works(self):
        from candid.switch_narrative import career_story_arc
        arc = career_story_arc(ROLES[:1], "Data Scientist")
        assert "Data Analyst" in arc and "Data Scientist" in arc

    def test_roles_without_highlights_ok(self):
        from candid.switch_narrative import career_story_arc
        arc = career_story_arc([{"title": "Clerk", "company": "Acme"}], "Designer")
        assert "Clerk" in arc and "Acme" in arc

    def test_missing_title_or_company_raises(self):
        from candid.switch_narrative import career_story_arc, SwitchNarrativeError
        for bad in ([], [{"title": "X"}], [{"company": "Y"}], ["nope"]):
            try:
                career_story_arc(bad, "Product Manager")
            except SwitchNarrativeError:
                pass
            else:
                raise AssertionError(f"no error for roles={bad!r}")

    def test_empty_role_raises(self):
        from candid.switch_narrative import career_story_arc, SwitchNarrativeError
        try:
            career_story_arc(ROLES, "")
        except SwitchNarrativeError:
            pass
        else:
            raise AssertionError("no error for empty target_role")


# --------------------------------------------------------------------------
# switch_pivot: pivot_cover_header
# --------------------------------------------------------------------------

class TestPivotCoverHeader:
    def test_header_mentions_target_role(self):
        from candid.switch_pivot import pivot_cover_header
        h = pivot_cover_header(_profile(), "Product Manager")
        assert "Product Manager" in h

    def test_header_mentions_years_and_current_identity(self):
        from candid.switch_pivot import pivot_cover_header
        h = pivot_cover_header(_profile(), "Product Manager")
        assert "5" in h and "Analytics Lead" in h

    def test_header_is_short(self):
        from candid.switch_pivot import pivot_cover_header
        h = pivot_cover_header(_profile(), "Product Manager")
        assert len(h) < 300

    def test_header_handles_sparse_profile(self):
        from candid.switch_pivot import pivot_cover_header
        h = pivot_cover_header({"name": "X"}, "Designer")
        assert "Designer" in h

    def test_header_bad_input_raises(self):
        from candid.switch_pivot import pivot_cover_header, PivotResumeError
        for prof, role in ((None, "PM"), ("x", "PM"), (_profile(), "")):
            try:
                pivot_cover_header(prof, role)
            except PivotResumeError:
                pass
            else:
                raise AssertionError(f"no error for {prof!r}, {role!r}")


# --------------------------------------------------------------------------
# switch_pivot: build_pivot_resume
# --------------------------------------------------------------------------

class TestBuildPivotResume:
    def test_capabilities_section_leads(self):
        from candid.switch_pivot import build_pivot_resume
        md = build_pivot_resume(_profile(), "Product Manager")
        caps = md.index("## Relevant capabilities")
        hist = md.index("## Work history")
        assert caps < hist

    def test_every_bullet_grouped_exactly_once(self):
        from candid.switch_pivot import build_pivot_resume
        md = build_pivot_resume(_profile(), "Product Manager")
        caps = md.split("## Relevant capabilities")[1].split("## Work history")[0]
        for b in BULLETS:
            cleaned = re.sub(r"\s+", " ", b).strip().rstrip(".")
            assert caps.count(cleaned) == 1, f"bullet not grouped exactly once: {b[:40]}"

    def test_bullets_carry_provenance(self):
        from candid.switch_pivot import build_pivot_resume
        md = build_pivot_resume(_profile(), "Product Manager")
        assert "Initech" in md and "Globex" in md

    def test_work_history_is_condensed(self):
        from candid.switch_pivot import build_pivot_resume
        md = build_pivot_resume(_profile(), "Product Manager")
        hist = md.split("## Work history")[1]
        assert "Data Analyst, Initech (2021 - 2023)" in hist
        assert "Tableau dashboards" not in hist  # bullets live in capabilities only

    def test_skills_and_education_included(self):
        from candid.switch_pivot import build_pivot_resume
        md = build_pivot_resume(_profile(), "Product Manager")
        assert "## Skills" in md and "python" in md
        assert "## Education" in md and "B.S. Statistics" in md

    def test_positioning_statement_at_top(self):
        from candid.switch_pivot import build_pivot_resume
        md = build_pivot_resume(_profile(), "Product Manager")
        assert "pivoting into Product Manager" in md

    def test_missing_experience_raises(self):
        from candid.switch_pivot import build_pivot_resume, PivotResumeError
        for bad in ({}, {"experience": []}, {"experience": "x"}, None):
            try:
                build_pivot_resume(bad, "Product Manager")
            except PivotResumeError:
                pass
            else:
                raise AssertionError(f"no error for profile={bad!r}")

    def test_duplicate_bullets_deduped(self):
        from candid.switch_pivot import build_pivot_resume
        prof = _profile()
        prof["experience"][1]["bullets"] = prof["experience"][0]["bullets"][:]  # dupes
        md = build_pivot_resume(prof, "Product Manager")
        caps = md.split("## Relevant capabilities")[1].split("## Work history")[0]
        for b in BULLETS[:2]:
            cleaned = re.sub(r"\s+", " ", b).strip().rstrip(".")
            assert caps.count(cleaned) == 1

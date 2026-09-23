"""Tests for candid.design_studio (Designer track, batch-94).

Uses tmp_path + CANDID_DATA_DIR monkeypatching so nothing touches real data.
"""

import os
from pathlib import Path

import pytest

from candid.design_studio import (
    SECTIONS,
    build_case_study,
    case_study_wizard,
    export_case_study,
    render_case_study_html,
    render_case_study_md,
    site_content,
    validate_case_study,
    walkthrough_script,
)


@pytest.fixture()
def project():
    return {
        "title": "Checkout Redesign",
        "role": "Product designer",
        "summary": "Redesigned mobile checkout to cut drop-off.",
        "outcomes": ["Drop-off down 18%", "NPS up 6 points"],
    }


@pytest.fixture()
def full_answers():
    return {
        "context_problem": "Checkout drop-off was 40% on mobile.",
        "role": "Lead product designer, research to ship.",
        "research": "5 usability tests and funnel analytics.",
        "ideation": "Explored one-page vs stepped flows; picked stepped.",
        "iteration": "Two prototype rounds; simplified address entry.",
        "outcome": "Drop-off down 18%; NPS up 6 points.",
        "learnings": "Test on real devices earlier.",
    }


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    return tmp_path


# --- case-study wizard -------------------------------------------------------

def test_wizard_complete(project, full_answers):
    cs = case_study_wizard(project, answers=full_answers)
    assert cs["title"] == "Checkout Redesign"
    assert cs["missing"] == []
    assert cs["sections"]["outcome"] == "Drop-off down 18%; NPS up 6 points."


def test_wizard_flags_missing_sections(project):
    cs = case_study_wizard(project, answers={"context_problem": "x", "role": "y"})
    assert set(cs["missing"]) == {k for k, _t, _p in SECTIONS} - {"context_problem", "role"}


def test_validate_case_study_blank_counts_as_missing(project):
    cs = build_case_study(project, {k: "  " for k, _t, _p in SECTIONS})
    assert validate_case_study(cs) == [k for k, _t, _p in SECTIONS]


def test_wizard_does_not_invent_metrics(project):
    cs = case_study_wizard(project, answers={"context_problem": "slow"})
    md = render_case_study_md(cs)
    # Nothing invented: the word "drop-off" came from the project, metrics only in sections
    assert "Drop-off down 18%" not in md
    for key, title, _ in SECTIONS:
        assert f"## {title}" in md


def test_render_md_marks_missing_sections(project):
    cs = case_study_wizard(project, answers={"context_problem": "slow"})
    md = render_case_study_md(cs)
    assert "## Outcome" in md
    assert "Not provided yet" in md
    assert "Sections still to complete" in md


def test_render_md_complete_has_all_headings(project, full_answers):
    cs = case_study_wizard(project, answers=full_answers)
    md = render_case_study_md(cs)
    assert md.startswith("# Checkout Redesign")
    for _key, title, _ in SECTIONS:
        assert f"\n## {title}\n" in md
    assert "Not provided yet" not in md


def test_wizard_interactive_prompt(tmp_path, project, monkeypatch, capsys):
    inputs = iter(["ctx", "role", "res", "idea", "iter", "out", "learn"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    cs = case_study_wizard(project)
    assert cs["missing"] == []
    assert cs["sections"]["learnings"] == "learn"


# --- site content ------------------------------------------------------------

def test_site_content_draft_labels_and_save(data_dir):
    profile = {
        "name": "Ava Designer",
        "headline": "Product designer",
        "summary": "I design checkout flows.",
        "skills": ["Figma", "Prototyping", "User research"],
    }
    projects = [
        {"title": "Checkout Redesign", "summary": "Redesigned mobile checkout.",
         "role": "Product designer", "outcomes": ["Drop-off down 18%"]},
        {"title": "Onboarding Flow", "description": "New user onboarding."},
    ]
    content = site_content(profile, projects)
    assert content["hero"].startswith("Ava Designer")
    path = Path(content["path"])
    assert path == data_dir / "design_packs" / "site_draft.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "DRAFT" in text
    assert text.count("DRAFT") >= 5
    # Per-project cards
    assert "## Project teaser cards" in text
    assert "### Checkout Redesign" in text
    assert "### Onboarding Flow" in text
    assert "Drop-off down 18%" in text
    assert "## About page" in text
    assert "## Homepage hero" in text
    # Missing role falls back to a draft placeholder, not invented content
    assert "[DRAFT: add your role]" in text


def test_site_content_outcomes_from_real_data_only(data_dir):
    profile = {"name": "Ava"}
    projects = [{"title": "Mystery Project", "role": "Designer"}]
    content = site_content(profile, projects)
    assert content["cards"][0]["outcomes"] == []
    text = Path(content["path"]).read_text(encoding="utf-8")
    assert "add 3 outcome bullets from real data" in text


# --- walkthrough script ------------------------------------------------------

def test_walkthrough_timing_sums_to_total():
    projects = [
        {"title": "Alpha", "summary": "Did alpha."},
        {"title": "Beta", "summary": "Did beta."},
        {"title": "Gamma", "summary": "Did gamma."},
    ]
    script = walkthrough_script(projects, total_minutes=5)
    total = sum(b["minutes"] for b in script["beats"])
    assert total == pytest.approx(5.0)
    assert all(b["minutes"] > 0 for b in script["beats"])


def test_walkthrough_timing_other_totals():
    projects = [{"title": "Solo", "summary": "Did solo."}]
    for total in (3, 5, 10):
        script = walkthrough_script(projects, total_minutes=total)
        assert sum(b["minutes"] for b in script["beats"]) == pytest.approx(float(total))


def test_walkthrough_structure():
    projects = [
        {"title": "Alpha", "summary": "Did alpha.", "theme": "onboarding"},
        {"title": "Beta", "summary": "Did beta.", "theme": "checkout"},
    ]
    script = walkthrough_script(projects)
    labels = [b["label"] for b in script["beats"]]
    assert labels[0] == "Opener"
    assert labels[-1] == "Closer"
    assert any(l.startswith("Transition") for l in labels)
    joined = " ".join(b["script"] for b in script["beats"])
    assert "Alpha" in joined and "Beta" in joined
    assert "thread connecting" in script["thread"].lower()
    assert "opener" in script["tips"] and "closer" in script["tips"]
    assert script["closing"] == script["beats"][-1]["script"]


def test_walkthrough_limits_to_three_projects():
    projects = [{"title": f"P{i}", "summary": "x"} for i in range(6)]
    script = walkthrough_script(projects)
    project_beats = [b for b in script["beats"] if b["label"].startswith("Project")]
    assert len(project_beats) == 3
    assert sum(b["minutes"] for b in script["beats"]) == pytest.approx(5.0)


def test_walkthrough_requires_a_project():
    with pytest.raises(ValueError):
        walkthrough_script([])


# --- export ------------------------------------------------------------------

def test_export_md(data_dir, project, full_answers):
    cs = case_study_wizard(project, answers=full_answers)
    path = export_case_study(cs, fmt="md")
    assert Path(path).is_file()
    assert Path(path).parent == data_dir / "design_packs"
    assert path.endswith(".md")
    text = Path(path).read_text(encoding="utf-8")
    assert "# Checkout Redesign" in text
    for _key, title, _ in SECTIONS:
        assert f"## {title}" in text


def test_export_html(data_dir, project, full_answers):
    cs = case_study_wizard(project, answers=full_answers)
    path = export_case_study(cs, fmt="html")
    assert path.endswith(".html")
    html = Path(path).read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html
    assert "<style>" in html  # inline CSS
    assert "<h1>Checkout Redesign</h1>" in html
    for _key, title, _ in SECTIONS:
        assert f"<h2>{title}</h2>" in html


def test_export_both(data_dir, project, full_answers):
    cs = case_study_wizard(project, answers=full_answers)
    path = export_case_study(cs, fmt="both")
    md, html = Path(path), Path(str(path).replace(".md", ".html"))
    assert md.is_file() and html.is_file()


def test_export_bad_fmt(project, full_answers):
    cs = case_study_wizard(project, answers=full_answers)
    with pytest.raises(ValueError):
        export_case_study(cs, fmt="pdf")


def test_export_escapes_html(data_dir, project):
    cs = case_study_wizard(project, answers={
        "context_problem": "<script>alert(1)</script>",
    })
    html = render_case_study_html(cs)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html

"""Tests for candid.research_frame (publication framing + research statement).

Pytest style, fully offline. File-system tests use tmp_path; the
profile-intake tests point intake_project at an explicit profile file.

Run: cd ~/workspace/candid-batch97 && python3 -m pytest tests/test_research_frame.py -q
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import research_frame as R  # noqa: E402


def _project(**kw):
    p = {
        "title": "Fast Approximate Retrieval",
        "description": "Built a retrieval system that answers queries over 10M documents.",
        "techniques": ["vector search", "quantization"],
        "outcomes": ["2x faster than the baseline we compared against"],
    }
    p.update(kw)
    return p


def _statement_data(**kw):
    d = {
        "name": "Test Researcher",
        "past_projects": [
            {"title": "Project Alpha",
             "description": "Built a thing that does X.",
             "outcomes": ["it worked in our tests"]},
            {"title": "Project Beta", "description": "Extended the thing to Y."},
        ],
        "current_focus": "scaling the thing to web scale",
        "future_agenda": [
            "Make it robust to noisy inputs",
            "Apply it to multilingual settings",
        ],
        "target": "ML research labs",
    }
    d.update(kw)
    return d


# ---------------------------------------------------------------------------
# FEATURE 1 — frame_project
# ---------------------------------------------------------------------------

def test_frame_project_returns_expected_keys():
    f = R.frame_project(_project())
    assert set(f) == {"project", "candidate_titles", "abstract_skeleton",
                      "claims", "venue_tiers", "related_work_checklist",
                      "disclaimer"}


def test_three_candidate_titles_use_user_words():
    f = R.frame_project(_project())
    titles = f["candidate_titles"]
    assert len(titles) == 3
    assert all("Fast Approximate Retrieval" in t for t in titles)
    assert any("vector search" in t for t in titles)


def test_abstract_skeleton_has_four_labeled_paragraphs():
    f = R.frame_project(_project())
    skel = f["abstract_skeleton"]
    assert set(skel) == {"problem", "approach", "results", "contribution"}
    for para in skel.values():
        assert R.FILL in para  # every paragraph has a slot for the user


def test_abstract_skeleton_echoes_user_description_and_outcomes():
    f = R.frame_project(_project())
    assert "answers queries over 10M documents" in f["abstract_skeleton"]["problem"]
    assert "2x faster than the baseline" in f["abstract_skeleton"]["results"]


def test_claims_all_labeled_user_stated_and_grounded():
    f = R.frame_project(_project())
    claims = f["claims"]
    assert claims, "expected at least one claim"
    for c in claims:
        assert c["basis"] == R.USER_STATED
        assert c["source"]
    texts = " ".join(c["text"] for c in claims)
    assert "vector search" in texts
    assert "quantization" in texts
    assert "2x faster than the baseline" in texts


def test_claims_contain_no_invented_numbers():
    # Outcomes must repeat the user's words, not add new metrics.
    f = R.frame_project(_project(techniques=[], outcomes=[]))
    for c in f["claims"]:
        assert "%" not in c["text"]
        assert "SOTA" not in c["text"] and "state-of-the-art" not in c["text"].lower()


def test_venue_tiers_are_generic_no_real_venue_names():
    f = R.frame_project(_project())
    tiers = [v["tier"] for v in f["venue_tiers"]]
    assert tiers == ["Workshop", "Top-tier conference", "Journal"]
    blob = json.dumps(f["venue_tiers"]).lower()
    for real_name in ("neurips", "icml", "iclr", "aaai", "nature", "science"):
        assert real_name not in blob


def test_related_work_checklist_covers_user_techniques():
    f = R.frame_project(_project())
    items = f["related_work_checklist"]
    assert any("vector search" in i for i in items)
    assert any("quantization" in i for i in items)
    assert any("Baselines" in i for i in items)


def test_missing_title_raises_clear_error():
    with pytest.raises(R.FrameError, match="title"):
        R.frame_project({"description": "built a thing"})


def test_missing_description_raises_clear_error():
    with pytest.raises(R.FrameError, match="description"):
        R.frame_project({"title": "A Thing"})


def test_non_dict_project_raises():
    with pytest.raises(R.FrameError):
        R.frame_project("just a string")


def test_techniques_accepted_as_plain_text():
    f = R.frame_project(_project(techniques="vector search\nquantization"))
    assert f["project"]["techniques"] == ["vector search", "quantization"]


def test_render_framing_is_markdown_with_all_sections():
    md = R.render_framing(R.frame_project(_project()))
    assert isinstance(md, str)
    for heading in ("## Candidate paper titles", "## Abstract skeleton",
                    "## Novelty claims", "## Venue tiers",
                    "## Related-work checklist"):
        assert heading in md
    assert R.FILL in md
    assert "- [ ]" in md  # checklist checkboxes


def test_save_framing_writes_markdown(tmp_path):
    dest = R.save_framing(R.frame_project(_project()), tmp_path / "framing.md")
    assert dest.exists()
    text = dest.read_text(encoding="utf-8")
    assert "# Publication framing" in text
    assert "Fast Approximate Retrieval" in text


# ---------------------------------------------------------------------------
# FEATURE 1 — intake
# ---------------------------------------------------------------------------

def test_intake_parses_labeled_text_standalone():
    text = (
        "Title: My Cool Project\n"
        "What was built: A system that summarizes papers.\n"
        "Techniques: transformers\nfine-tuning\n"
        "Outcomes: reviewers liked the demo\n"
    )
    proj = R.intake_project(text=text)
    assert proj["title"] == "My Cool Project"
    assert "summarizes papers" in proj["description"]
    assert "transformers" in proj["techniques"]
    assert "reviewers liked the demo" in proj["outcomes"]
    # and the result feeds straight into frame_project
    assert R.frame_project(proj)["project"]["title"] == "My Cool Project"


def test_intake_unlabeled_text_uses_first_line_as_title():
    proj = R.intake_project(text="Recommender Thing\nBuilt a recommender for movies.\nIt was fun.")
    assert proj["title"] == "Recommender Thing"
    assert "recommender for movies" in proj["description"]


def test_intake_from_profile_projects(tmp_path):
    prof_path = tmp_path / "profile.json"
    prof_path.write_text(json.dumps({
        "name": "Test User",
        "projects": [
            {"title": "Profile Project",
             "description": "From the stored profile.",
             "techniques": ["logistic regression"],
             "outcomes": ["shipped internally"]},
        ],
    }), encoding="utf-8")
    proj = R.intake_project(profile_path=prof_path)
    assert proj["title"] == "Profile Project"
    assert "logistic regression" in proj["techniques"]


def test_intake_pasted_text_wins_over_profile(tmp_path):
    prof_path = tmp_path / "profile.json"
    prof_path.write_text(json.dumps({
        "projects": [{"title": "Old Title", "description": "old desc"}],
    }), encoding="utf-8")
    proj = R.intake_project(text="Title: New Title\nDescription: new desc",
                            profile_path=prof_path)
    assert proj["title"] == "New Title"
    assert proj["description"] == "new desc"


def test_intake_profile_index_out_of_range(tmp_path):
    prof_path = tmp_path / "profile.json"
    prof_path.write_text(json.dumps({"projects": [{"title": "Only"}]}), encoding="utf-8")
    with pytest.raises(R.FrameError, match="out of range"):
        R.intake_project(profile_path=prof_path, project_index=5)


def test_intake_profile_without_projects_raises_friendly(tmp_path):
    prof_path = tmp_path / "profile.json"
    prof_path.write_text(json.dumps({"name": "No Projects"}), encoding="utf-8")
    with pytest.raises(R.FrameError, match="No 'projects' entries"):
        R.intake_project(profile_path=prof_path)


def test_intake_with_nothing_raises():
    with pytest.raises(R.FrameError, match="Nothing to frame"):
        R.intake_project()


# ---------------------------------------------------------------------------
# FEATURE 2 — build_statement
# ---------------------------------------------------------------------------

def test_build_statement_sections_and_fit():
    stmt = R.build_statement(_statement_data())
    assert set(stmt["sections"]) == {"past_research", "current_focus",
                                    "future_agenda", "fit"}
    assert "Project Alpha" in stmt["sections"]["past_research"]
    assert "Project Beta" in stmt["sections"]["past_research"]
    assert "scaling the thing to web scale" in stmt["sections"]["current_focus"]
    assert "noisy inputs" in stmt["sections"]["future_agenda"]
    assert "ML research labs" in stmt["sections"]["fit"]


def test_build_statement_omits_fit_without_target():
    stmt = R.build_statement(_statement_data(target=""))
    assert "fit" not in stmt["sections"]


def test_user_words_appear_verbatim():
    stmt = R.build_statement(_statement_data())
    blob = " ".join(stmt["sections"].values())
    assert "Built a thing that does X." in blob
    assert "it worked in our tests" in blob


def test_placeholders_present_not_invented_results():
    stmt = R.build_statement(_statement_data())
    blob = " ".join(stmt["sections"].values())
    assert R.FILL in blob
    assert "published in" not in blob.lower()


def test_missing_past_projects_raises():
    with pytest.raises(R.FrameError, match="past_projects"):
        R.build_statement(_statement_data(past_projects=[]))


def test_missing_current_focus_raises():
    with pytest.raises(R.FrameError, match="current_focus"):
        R.build_statement(_statement_data(current_focus="  "))


def test_missing_future_agenda_raises():
    with pytest.raises(R.FrameError, match="future_agenda"):
        R.build_statement(_statement_data(future_agenda=[]))


def test_project_without_title_raises():
    with pytest.raises(R.FrameError, match="past_projects\\[0\\]"):
        R.build_statement(_statement_data(
            past_projects=[{"description": "no title here"}]))


def test_non_dict_data_raises():
    with pytest.raises(R.FrameError):
        R.build_statement(["not", "a", "dict"])


def test_length_note_warns_when_far_under_target():
    stmt = R.build_statement(_statement_data(
        past_projects=[{"title": "Tiny", "description": "Did a thing."}],
        current_focus="stuff",
        future_agenda=["more stuff"],
    ))
    assert stmt["word_count"] < R.MIN_OK_WORDS
    assert "under" in stmt["length_note"]


def test_length_note_warns_when_far_over_target():
    long_para = "word " * 600
    stmt = R.build_statement(_statement_data(
        past_projects=[{"title": "Huge", "description": long_para}],
        current_focus=long_para,
        future_agenda=[long_para, long_para],
    ))
    assert stmt["word_count"] > R.MAX_OK_WORDS
    assert "over" in stmt["length_note"]


def test_render_statement_markdown_structure():
    md = R.render_statement(R.build_statement(_statement_data()))
    assert md.startswith("# Research Statement")
    for heading in ("## Past Research", "## Current Focus",
                    "## Future Agenda", "## Fit"):
        assert heading in md
    assert "Length check" in md


def test_render_statement_without_target_has_no_fit_heading():
    md = R.render_statement(R.build_statement(_statement_data(target="")))
    assert "## Fit" not in md


def test_save_statement_writes_file(tmp_path):
    stmt = R.build_statement(_statement_data())
    dest = R.save_statement(stmt, tmp_path / "statement.md")
    assert dest.exists()
    text = dest.read_text(encoding="utf-8")
    assert "# Research Statement" in text
    assert "Project Alpha" in text


def test_load_statement_data_round_trip(tmp_path):
    p = tmp_path / "data.json"
    p.write_text(json.dumps(_statement_data()), encoding="utf-8")
    data = R.load_statement_data(p)
    stmt = R.build_statement(data)
    assert "Project Alpha" in stmt["sections"]["past_research"]


def test_load_statement_data_bad_json_raises(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(R.FrameError, match="not valid JSON"):
        R.load_statement_data(p)


def test_load_statement_data_missing_file_raises(tmp_path):
    with pytest.raises(R.FrameError, match="not found"):
        R.load_statement_data(tmp_path / "nope.json")

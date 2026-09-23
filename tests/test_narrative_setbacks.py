"""Tests for candid.narrative_setbacks.

CANDID_DATA_DIR is set before candid imports so all state stays in the
fixture sandbox; C.DATA_DIR is rebound per-test for tmp_path isolation.
"""
import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-narrative-setbacks")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import narrative_setbacks as N  # noqa: E402


PROFILE = {
    "name": "Alex Rivera",
    "headline": "Senior ML Engineer",
    "location": "New York, NY",
    "summary": "",
    "skills": ["python", "machine learning"],
    "experience": [
        {"title": "Senior ML Engineer", "company": "Meridian Financial",
         "dates": "2023 - present", "bullets": ["Shipped X"]},
        {"title": "ML Engineer", "company": "Dataworks",
         "dates": "2021 - 2023", "bullets": ["Built Y"]},
    ],
    "education": [],
    "years_experience": 5,
    "seniority": "senior",
    "source_files": [],
}


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    old = C.DATA_DIR
    C.DATA_DIR = tmp_path
    yield tmp_path
    C.DATA_DIR = old


def _write_profile(data_dir):
    (data_dir / "profile.json").write_text(json.dumps(PROFILE), encoding="utf-8")


def _write_debriefs(data_dir):
    (data_dir / "debriefs.json").write_text(json.dumps([
        {"id": 1, "company": "Acme Corp", "role": "ML Engineer",
         "date": "2026-02-10",
         "what_went_wrong": "Missed the launch deadline; underestimated data cleaning."},
        {"id": 2, "company": "Beta Inc", "role": "SWE",
         "mistake": "Deployed without a feature flag and caused a partial outage."},
    ]), encoding="utf-8")


def _write_rejections(data_dir):
    (data_dir / "rejections.json").write_text(json.dumps([
        {"id": 7, "company": "Gamma LLC", "role": "Senior SWE",
         "reason": "Feedback said my system-design answer lacked depth on tradeoffs."},
    ]), encoding="utf-8")


# --- setback scaffolds -------------------------------------------------------

def test_scaffolds_from_debrief_cite_source(data_dir):
    _write_debriefs(data_dir)
    stories = N.build_setback_stories()
    by_kind = {s["kind"]: s for s in stories if not s["is_template"]}
    assert "failure" in by_kind and "mistake" in by_kind
    failure = by_kind["failure"]
    assert "debrief" in failure["source_citation"]
    assert "Acme Corp" in failure["source_citation"]
    assert "what_went_wrong" in failure["source_citation"]
    assert "Missed the launch deadline" in failure["source_excerpt"]
    assert failure["frame"]["situation"] == "[fill in: your story]"
    assert not failure["is_template"]


def test_scaffolds_from_rejection_cite_source(data_dir):
    _write_rejections(data_dir)
    stories = N.build_setback_stories()
    data_driven = [s for s in stories if not s["is_template"]]
    assert len(data_driven) == 1
    assert "Gamma LLC" in data_driven[0]["source_citation"]
    assert "rejection" in data_driven[0]["source_citation"]


def test_bare_rejection_without_feedback_is_skipped(data_dir):
    (data_dir / "rejections.json").write_text(json.dumps([
        {"id": 7, "company": "Gamma LLC", "role": "Senior SWE"},
    ]), encoding="utf-8")
    stories = N.build_setback_stories()
    assert all(s["is_template"] for s in stories)


def test_generic_templates_when_no_data(data_dir):
    stories = N.build_setback_stories()
    assert len(stories) == 3
    for s in stories:
        assert s["is_template"]
        assert s["source_citation"] == "[TEMPLATE]"
        assert "[TEMPLATE]" in s["note"]
        assert set(s["frame"]) == {"situation", "what_went_wrong", "lesson", "what_changed"}
    assert {s["kind"] for s in stories} == {"failure", "mistake", "weakness"}


def test_update_story_roundtrip(data_dir):
    stories = N.build_setback_stories()
    sid = stories[0]["id"]
    updated = N.update_setback_story(sid, "My written story about the outage.")
    assert updated["user_text"] == "My written story about the outage."
    state = json.loads((data_dir / "narrative.json").read_text(encoding="utf-8"))
    saved = {s["id"]: s for s in state["setbacks"]["stories"]}
    assert saved[sid]["user_text"] == "My written story about the outage."


def test_update_unknown_story_raises(data_dir):
    N.build_setback_stories()
    with pytest.raises(N.NarrativeError):
        N.update_setback_story("no-such-id", "text")


def test_rebuild_preserves_saved_user_text(data_dir):
    _write_debriefs(data_dir)
    stories = N.build_setback_stories()
    sid = stories[0]["id"]
    N.update_setback_story(sid, "My saved version.")
    rebuilt = N.build_setback_stories()
    saved = {s["id"]: s for s in rebuilt}
    assert saved[sid]["user_text"] == "My saved version."


# --- one-pager ---------------------------------------------------------------

def test_onepager_contains_all_sections(data_dir):
    _write_profile(data_dir)
    text = N.export_onepager()
    for section in ("Career Arc", "2-Minute Pitch", "Hooks", "Transitions", "Why Us"):
        assert section in text
    assert "Alex Rivera" in text
    assert "Senior ML Engineer" in text
    assert "New York, NY" in text


def test_onepager_draft_banner_when_pitch_unapproved(data_dir):
    _write_profile(data_dir)
    text = N.export_onepager(narrative={
        "pitches": {"2min": {"text": "I am a draft pitch.", "approved": False}},
    })
    assert "DRAFT - not yet approved" in text
    assert "I am a draft pitch." in text


def test_onepager_no_banner_when_pitch_approved(data_dir):
    _write_profile(data_dir)
    text = N.export_onepager(narrative={
        "pitches": {"2min": {"text": "My approved pitch.", "approved": True}},
    })
    assert "DRAFT - not yet approved" not in text
    assert "My approved pitch." in text


def test_onepager_narrative_json_keys_resolve(data_dir):
    _write_profile(data_dir)
    (data_dir / "narrative.json").write_text(json.dumps({
        "arc": "From data analyst to ML engineer, one thread: measurable impact.",
        "hooks": ["Cut inference cost 40%"],
        "transitions": ["Moved to Meridian for ads-ranking scope"],
        "why_us": "Your ads-ranking problem matches my track record.",
        "pitches": {"2min": {"text": "Approved pitch text.", "approved": True}},
    }), encoding="utf-8")
    text = N.export_onepager()
    assert "measurable impact" in text
    assert "Cut inference cost 40%" in text
    assert "ads-ranking scope" in text
    assert "Your ads-ranking problem" in text


def test_onepager_word_counts_and_times(data_dir):
    _write_profile(data_dir)
    text = N.export_onepager()
    for section in ("Career Arc", "2-Minute Pitch", "Hooks", "Transitions", "Why Us"):
        assert f"words, ~" in text  # stat line per section
    assert "140 wpm" in text
    assert "Total:" in text


def test_onepager_text_format(data_dir):
    _write_profile(data_dir)
    text = N.export_onepager(format="text")
    assert "CAREER ARC" in text
    assert "DRAFT - not yet approved" in text  # unapproved fallback pitch
    assert "#" not in text.splitlines()[0]


def test_onepager_bad_format_raises(data_dir):
    _write_profile(data_dir)
    with pytest.raises(N.NarrativeError):
        N.export_onepager(format="pdf")


def test_onepager_missing_profile_raises(data_dir):
    with pytest.raises(N.NarrativeError):
        N.export_onepager()


def test_write_onepager_records_exports(data_dir):
    _write_profile(data_dir)
    out = data_dir / "onepager.md"
    record = N.write_onepager(out)
    assert out.exists()
    assert "# Interview Narrative One-Pager" in out.read_text(encoding="utf-8")
    assert record["format"] == "markdown"
    assert set(record["word_counts"]) == {"Career Arc", "2-Minute Pitch", "Hooks",
                                          "Transitions", "Why Us"}
    assert all(record["word_counts"].values())
    assert all(record["seconds"].values())
    assert record["total_words"] == sum(record["word_counts"].values())
    state = json.loads((data_dir / "narrative.json").read_text(encoding="utf-8"))
    assert state["exports"]["last_export"]["path"] == str(out)


def test_sibling_keys_preserved(data_dir):
    _write_profile(data_dir)
    (data_dir / "narrative.json").write_text(json.dumps({
        "arc": "keep me",
        "pitches": {"2min": {"text": "keep pitch", "approved": True}},
        "custom_sibling_key": {"x": 1},
    }), encoding="utf-8")
    N.build_setback_stories()
    N.write_onepager(data_dir / "onepager.md")
    state = json.loads((data_dir / "narrative.json").read_text(encoding="utf-8"))
    assert state["arc"] == "keep me"
    assert state["pitches"]["2min"]["text"] == "keep pitch"
    assert state["custom_sibling_key"] == {"x": 1}
    assert "setbacks" in state and "exports" in state


def test_corrupt_narrative_json_raises(data_dir):
    (data_dir / "narrative.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(N.NarrativeError):
        N.build_setback_stories()

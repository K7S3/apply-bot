"""Tests for candid/narrative_review.py: word-level approval flow + pitch tailoring."""
import json
import os
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-narrative-review")

import pytest

from candid import config as C
from candid import narrative_review as NR

PITCH_TEXT = (
    "I am Keshavan, a machine learning engineer at Meta. "
    "I built ads ranking models in Python that lifted revenue. "
    "Dr. Rao mentored me on statistics, e.g. experiment design. "
    "I want to bring that rigor to your team."
)

PITCH_CITATIONS = [
    ["resume:experience[0]"],
    ["resume:experience[1]", "jd:python"],
    ["resume:education"],
    [],
]


@pytest.fixture
def tdir(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "DATA_DIR", tmp_path)
    return tmp_path


def _write_narrative(tdir, pitches=None, extra=None):
    doc = extra or {}
    doc["pitches"] = pitches if pitches is not None else {
        "2min": {"text": PITCH_TEXT, "citations": PITCH_CITATIONS}
    }
    (tdir / "narrative.json").write_text(json.dumps(doc), encoding="utf-8")
    return doc


def _write_profile(tdir, skills=("python", "machine learning", "sql", "statistics")):
    (tdir / "profile.json").write_text(
        json.dumps({"name": "Keshavan", "skills": list(skills)}), encoding="utf-8"
    )


# --- sentence splitting ------------------------------------------------------


def test_split_sentences_basic():
    out = NR.split_sentences("First sentence. Second one! Is this third? Yes.")
    assert out == ["First sentence.", "Second one!", "Is this third?", "Yes."]


def test_split_sentences_protects_abbreviations():
    out = NR.split_sentences(
        "Dr. Rao mentored me on statistics, e.g. experiment design. I loved it."
    )
    assert len(out) == 2
    assert out[0].endswith("experiment design.")


def test_split_sentences_empty_raises():
    with pytest.raises(NR.NarrativeError):
        NR.split_sentences("   ")


# --- review_pitch --------------------------------------------------------------


def test_review_pitch_missing_draft_raises(tdir):
    _write_narrative(tdir, pitches={})
    with pytest.raises(NR.NarrativeError):
        NR.review_pitch("2min")


def test_review_pitch_numbered_sentences_with_citations(tdir):
    _write_narrative(tdir)
    sents = NR.review_pitch("2min")
    assert len(sents) == 4
    assert [s["index"] for s in sents] == [0, 1, 2, 3]
    assert sents[1]["citations"] == ["resume:experience[1]", "jd:python"]
    assert all(s["decision"] == "pending" for s in sents)
    # recorded under our own "approvals" key
    doc = json.loads((tdir / "narrative.json").read_text(encoding="utf-8"))
    assert "2min" in doc["approvals"]
    assert doc["approvals"]["2min"]["fully_approved"] is False


def test_review_pitch_accepts_plain_string_pitch(tdir):
    _write_narrative(tdir, pitches={"30s": "I build ML systems. I ship them fast."})
    sents = NR.review_pitch("30s")
    assert len(sents) == 2
    assert sents[0]["citations"] == []


# --- approve / edit / reject flow ------------------------------------------------


def test_approve_all_marks_fully_approved(tdir):
    _write_narrative(tdir)
    NR.review_pitch("2min")
    record = NR.submit_review("2min", {0: "approve", 1: "approve", 2: "approve", 3: "approve"})
    assert record["fully_approved"] is True
    assert record["approved_text"] == PITCH_TEXT
    status = NR.approval_status("2min")
    assert status["fully_approved"] is True
    assert status["approved"] == 4
    assert status["pending"] == 0


def test_edited_sentence_counts_as_approved_and_replaces_text(tdir):
    _write_narrative(tdir)
    NR.review_pitch("2min")
    new_text = "I want to bring that rigor to Acme."
    NR.submit_review("2min", {0: "approve", 1: "approve", 2: "approve", 3: f"edit:{new_text}"})
    status = NR.approval_status("2min")
    assert status["fully_approved"] is True
    assert status["edited"] == 1
    assert status["approved_text"].endswith(new_text)
    assert "your team" not in status["approved_text"]


def test_reject_drops_sentence_and_blocks_full_approval(tdir):
    _write_narrative(tdir)
    NR.review_pitch("2min")
    NR.submit_review("2min", {0: "approve", 1: "reject", 2: "approve", 3: "approve"})
    status = NR.approval_status("2min")
    assert status["fully_approved"] is False
    assert status["rejected"] == 1
    assert "lifted revenue" not in status["approved_text"]
    assert "machine learning engineer" in status["approved_text"]


def test_partial_review_not_fully_approved(tdir):
    _write_narrative(tdir)
    NR.review_pitch("2min")
    status = NR.approval_status("2min")
    assert status["fully_approved"] is False
    assert status["pending"] == 4
    NR.submit_review("2min", {0: "approve"})
    status = NR.approval_status("2min")
    assert status["fully_approved"] is False
    assert status["pending"] == 3


def test_bad_decision_format_raises(tdir):
    _write_narrative(tdir)
    NR.review_pitch("2min")
    with pytest.raises(NR.NarrativeError):
        NR.submit_review("2min", {0: "maybe"})
    with pytest.raises(NR.NarrativeError):
        NR.submit_review("2min", {0: "edit:   "})
    with pytest.raises(NR.NarrativeError):
        NR.submit_review("2min", {99: "approve"})
    with pytest.raises(NR.NarrativeError):
        NR.submit_review("nope", {0: "approve"})


def test_sibling_keys_preserved(tdir):
    _write_narrative(tdir, extra={"arcs": {"origin": "Chennai"}, "version": 3})
    NR.review_pitch("2min")
    NR.submit_review("2min", {0: "approve", 1: "approve", 2: "approve", 3: "approve"})
    doc = json.loads((tdir / "narrative.json").read_text(encoding="utf-8"))
    assert doc["arcs"] == {"origin": "Chennai"}
    assert doc["version"] == 3
    assert doc["pitches"]["2min"]["text"] == PITCH_TEXT


# --- tailoring -----------------------------------------------------------------


JD = (
    "We need a machine learning engineer with strong Python and statistics "
    "skills for ads ranking. SQL a plus."
)


def test_tailor_reorders_by_keyword_overlap_and_needs_approval(tdir):
    _write_narrative(tdir)
    _write_profile(tdir)
    record = NR.tailor_pitch(JD, "Acme", "ML Engineer")
    key = "Acme::ML Engineer::2min"
    assert record["key"] == key
    assert record["fully_approved"] is False
    assert record["needs_approval"] is True
    assert record["approved_text"] == ""
    assert set(record["jd_keywords"]) == {"python", "machine learning", "sql", "statistics"}
    # sentences 0, 1, 2 each match exactly one keyword, so the stable sort
    # keeps their original relative order; the keyword-free sentence sinks last
    assert record["sentences"][0]["original_index"] == 0
    assert record["sentences"][0]["matched_keywords"] == ["machine learning"]
    assert record["sentences"][1]["matched_keywords"] == ["python"]
    assert record["sentences"][2]["matched_keywords"] == ["statistics"]
    assert record["sentences"][3]["matched_keywords"] == []
    assert record["sentences"][3]["original_index"] == 3
    # persisted under approvals with metadata
    doc = json.loads((tdir / "narrative.json").read_text(encoding="utf-8"))
    stored = doc["approvals"][key]
    assert stored["company"] == "Acme"
    assert stored["role"] == "ML Engineer"
    assert stored["length"] == "2min"


def test_tailor_preserves_all_factual_content_verbatim(tdir):
    _write_narrative(tdir)
    _write_profile(tdir)
    record = NR.tailor_pitch(JD, "Acme", "ML Engineer")
    original = [s["text"] for s in NR.review_pitch("2min")]
    tailored = [s["text"] for s in record["sentences"]]
    assert set(tailored) == set(original)
    assert sorted(tailored) == sorted(original)


def test_tailor_reorders_highest_overlap_first(tdir):
    _write_narrative(tdir, pitches={"2min": {
        "text": "I love hiking on weekends. I write Python and SQL daily for ads ranking. I also know machine learning.",
        "citations": [[], [], []],
    }})
    _write_profile(tdir)
    record = NR.tailor_pitch(JD, "Acme", "ML Engineer")
    # sentence 1 matches python + sql (2 keywords) so it jumps to the front
    assert record["sentences"][0]["original_index"] == 1
    assert set(record["sentences"][0]["matched_keywords"]) == {"python", "sql"}
    # verbatim set still intact
    original = {"I love hiking on weekends.", "I write Python and SQL daily for ads ranking.", "I also know machine learning."}
    assert {s["text"] for s in record["sentences"]} == original


def test_tailor_no_keyword_overlap_keeps_original_order(tdir):
    _write_narrative(tdir)
    _write_profile(tdir)
    record = NR.tailor_pitch("We need a pastry chef for our bakery.", "BakeryCo", "Chef")
    assert record["jd_keywords"] == []
    original = [s["text"] for s in NR.review_pitch("2min")]
    assert [s["text"] for s in record["sentences"]] == original


def test_tailor_missing_profile_raises_friendly(tdir):
    _write_narrative(tdir)
    with pytest.raises(NR.NarrativeError) as excinfo:
        NR.tailor_pitch(JD, "Acme", "ML Engineer")
    assert "onboard" in str(excinfo.value).lower()


def test_tailor_missing_pitch_raises(tdir):
    _write_profile(tdir)
    _write_narrative(tdir, pitches={})
    with pytest.raises(NR.NarrativeError):
        NR.tailor_pitch(JD, "Acme", "ML Engineer")


def test_tailored_draft_can_be_reviewed_and_approved(tdir):
    _write_narrative(tdir)
    _write_profile(tdir)
    record = NR.tailor_pitch(JD, "Acme", "ML Engineer")
    key = record["key"]
    decisions = {s["index"]: "approve" for s in record["sentences"]}
    NR.submit_review(key, decisions)
    status = NR.approval_status(key)
    assert status["fully_approved"] is True
    assert status["approved_text"] != ""

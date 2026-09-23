"""Tests for candid.research_prep (research-taste prep + hard-Q&A).

pytest, fully offline. Uses tmp_path for storage isolation.
"""
import builtins
import json

import pytest

from candid import research_prep as rp


@pytest.fixture()
def datadir(tmp_path, monkeypatch):
    """Point the module at an isolated data dir."""
    d = tmp_path / "research_prep"
    monkeypatch.setattr(rp, "RESEARCH_PREP_DIR", d)
    return d


def _feed(monkeypatch, answers):
    it = iter(answers)
    monkeypatch.setattr(builtins, "input", lambda *a: next(it))


# --- Feature 1: question bank ------------------------------------------------

def test_list_questions_all_have_required_fields():
    qs = rp.list_questions()
    assert len(qs) >= 20
    for q in qs:
        assert {"qid", "q", "category", "hint"} <= set(q)
        assert q["q"] and q["hint"]


def test_question_ids_unique():
    qids = [q["qid"] for q in rp.list_questions()]
    assert len(qids) == len(set(qids))


def test_list_questions_filter_by_category():
    qs = rp.list_questions("research_taste")
    assert qs
    assert all(q["category"] == "research_taste" for q in qs)
    assert any("pick research problems" in q["q"] for q in qs)


def test_list_questions_covers_expected_categories():
    assert set(rp.RESEARCH_CATEGORIES) == {
        "research_taste", "technical_depth", "failed_experiments",
        "collaboration", "research_vision",
    }
    for cat in rp.RESEARCH_CATEGORIES:
        assert rp.list_questions(cat), cat


def test_list_questions_unknown_category_raises():
    with pytest.raises(ValueError):
        rp.list_questions("astrology")


def test_bank_has_no_attributions():
    """Guardrail: curated bank must not name real people/papers/venues."""
    blob = json.dumps(rp.RESEARCH_QUESTIONS).lower()
    for token in ("arxiv", "neurips", "icml", "nature", "science journal", "et al"):
        assert token not in blob


# --- Feature 1: scoring / stats ----------------------------------------------

def test_record_score_validates_range(datadir):
    session = rp.build_session(rp.list_questions("research_taste")[:2])
    with pytest.raises(ValueError):
        rp.record_score(session, session["questions"][0]["qid"], 0)
    with pytest.raises(ValueError):
        rp.record_score(session, session["questions"][0]["qid"], 6)
    with pytest.raises(ValueError):
        rp.record_score(session, session["questions"][0]["qid"], "5")


def test_record_score_unknown_qid_raises(datadir):
    session = rp.build_session(rp.list_questions("research_taste")[:1])
    with pytest.raises(ValueError):
        rp.record_score(session, "nope-99", 3)


def test_record_score_persists_session_and_history(datadir):
    session = rp.build_session(rp.list_questions("research_taste")[:1])
    qid = session["questions"][0]["qid"]
    rp.record_score(session, qid, 4)
    assert session["scores"] == [{"qid": qid, "category": "research_taste", "score": 4}]
    saved = json.loads((datadir / "sessions" / f"{session['id']}.json").read_text())
    assert saved["scores"][0]["score"] == 4
    hist = json.loads((datadir / "history.json").read_text())["records"]
    assert hist and hist[0]["qid"] == qid and hist[0]["score"] == 4


def test_record_score_replaces_earlier_score(datadir):
    session = rp.build_session(rp.list_questions("research_taste")[:1])
    qid = session["questions"][0]["qid"]
    rp.record_score(session, qid, 2)
    rp.record_score(session, qid, 5)
    assert [s["score"] for s in session["scores"] if s["qid"] == qid] == [5]


def test_category_stats_aggregates(datadir):
    s1 = rp.build_session(rp.list_questions("research_taste")[:1] +
                          rp.list_questions("technical_depth")[:1])
    rp.record_score(s1, s1["questions"][0]["qid"], 2)
    rp.record_score(s1, s1["questions"][1]["qid"], 5)
    s2 = rp.build_session(rp.list_questions("research_taste")[:1])
    rp.record_score(s2, s2["questions"][0]["qid"], 4)
    stats = rp.category_stats()
    assert stats["research_taste"] == {"n": 2, "avg": 3.0}
    assert stats["technical_depth"] == {"n": 1, "avg": 5.0}


def test_category_stats_empty_history(datadir):
    assert rp.category_stats() == {}


def test_drill_next_weakest_first(datadir):
    s = rp.build_session(rp.list_questions("research_taste")[:1] +
                         rp.list_questions("collaboration")[:1] +
                         rp.list_questions("research_vision")[:1])
    rp.record_score(s, s["questions"][0]["qid"], 5)
    rp.record_score(s, s["questions"][1]["qid"], 1)
    rp.record_score(s, s["questions"][2]["qid"], 3)
    ranked = rp.drill_next()
    assert [d["category"] for d in ranked] == ["collaboration", "research_vision", "research_taste"]
    assert rp.drill_next(limit=1)[0]["category"] == "collaboration"


def test_practice_session_interactive_scoring(monkeypatch, datadir, capsys):
    qs = rp.list_questions("research_taste")
    _feed(monkeypatch, ["4", "skip"])
    session = rp.practice_session(2, categories=["research_taste"], seed=0)
    assert len(session["questions"]) == 2
    assert len(session["scores"]) == 1
    assert session["scores"][0]["score"] == 4
    out = capsys.readouterr().out
    assert "Drill next" in out


def test_practice_session_rejects_bad_inputs(monkeypatch, datadir):
    with pytest.raises(ValueError):
        rp.practice_session(0)
    with pytest.raises(ValueError):
        rp.practice_session(2, categories=["bogus"])


def test_practice_session_clamps_n_to_available(monkeypatch, datadir):
    _feed(monkeypatch, ["skip"] * 5)
    session = rp.practice_session(99, categories=["collaboration"], seed=1)
    assert len(session["questions"]) == 5  # only 5 exist in the category


# --- Feature 2: hard-Q&A generation ------------------------------------------

SAMPLE_PROJECT = (
    "We propose SparseRoute, a sparse mixture-of-experts router for long-context "
    "inference. Compared to the dense baseline used in prior work on efficient "
    "transformers, SparseRoute cuts KV-cache memory by 40% on 128k-token inputs "
    "with no accuracy drop on our long-context QA suite."
)


def test_generate_hard_questions_structure():
    qs = rp.generate_hard_questions(SAMPLE_PROJECT)
    assert len(qs) == 7
    for q in qs:
        assert q["question"] and isinstance(q["checklist"], list) and len(q["checklist"]) >= 4
        assert all(isinstance(p, str) and p for p in q["checklist"])


def test_generate_hard_questions_uses_user_named_prior_work():
    qs = rp.generate_hard_questions(SAMPLE_PROJECT)
    novelty = qs[0]["question"]
    assert "dense baseline" in novelty or "prior work on efficient transformers" in novelty


def test_generate_hard_questions_without_named_prior_work():
    qs = rp.generate_hard_questions("A new widget that makes toast faster.")
    assert "prior work you build on" in qs[0]["question"]
    # Nothing fabricated about the toast widget beyond the user's words
    assert "toast" in qs[5]["question"]


def test_generate_hard_questions_covers_expected_themes():
    qs = rp.generate_hard_questions(SAMPLE_PROJECT)
    blob = " ".join(q["question"] for q in qs).lower()
    for theme in ("baseline", "ablation", "fail", "limit", "care", "next experiment"):
        assert theme in blob, theme


def test_generate_hard_questions_empty_raises():
    with pytest.raises(ValueError):
        rp.generate_hard_questions("   ")


def test_checklists_are_generic_not_fabricated():
    """Checklists must be advice, never invented results about the user's work."""
    qs = rp.generate_hard_questions(SAMPLE_PROJECT)
    blob = " ".join(p for q in qs for p in q["checklist"]).lower()
    assert "sparseroute" not in blob
    assert "40%" not in blob


# --- Feature 2: practice + stats ----------------------------------------------

def test_practice_hard_qa_records_scores(monkeypatch, datadir, capsys):
    qs = rp.generate_hard_questions(SAMPLE_PROJECT)[:2]
    _feed(monkeypatch, ["", "5", "", "3"])  # Enter to answer, then score, x2
    results = rp.practice_hard_qa(qs)
    assert [r["score"] for r in results] == [5, 3]
    out = capsys.readouterr().out
    assert "Checklist" in out
    stats = rp.qa_stats()
    assert len(stats) == 2
    assert {s["avg"] for s in stats} == {5.0, 3.0}


def test_practice_hard_qa_skip_leaves_no_score(monkeypatch, datadir):
    qs = rp.generate_hard_questions(SAMPLE_PROJECT)[:1]
    _feed(monkeypatch, ["", "skip"])
    results = rp.practice_hard_qa(qs)
    assert results[0]["score"] is None
    assert rp.qa_stats() == []


def test_practice_hard_qa_empty_raises():
    with pytest.raises(ValueError):
        rp.practice_hard_qa([])


def test_qa_stats_weakest_first(datadir):
    qs = rp.generate_hard_questions(SAMPLE_PROJECT)[:2]
    for q, score in zip(qs, (4, 2)):
        rp._append_history({"at": "t", "session": "s", "kind": "hard_qa",
                            "qid": q["qid"], "question": q["question"], "score": score})
    stats = rp.qa_stats()
    assert [s["qid"] for s in stats] == [qs[1]["qid"], qs[0]["qid"]]
    assert stats[0]["n"] == 1


def test_qa_stats_empty(datadir):
    assert rp.qa_stats() == []


def test_research_and_hardqa_histories_do_not_mix(datadir):
    s = rp.build_session(rp.list_questions("research_taste")[:1])
    rp.record_score(s, s["questions"][0]["qid"], 4)
    assert rp.qa_stats() == []
    assert set(rp.category_stats()) == {"research_taste"}

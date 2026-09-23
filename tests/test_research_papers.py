"""Tests for candid/research_papers.py: paper library + deep-dive drills."""

from __future__ import annotations

import json

import pytest

from candid import research_papers as rp


@pytest.fixture
def paths(tmp_path):
    return {
        "path": tmp_path / "research_papers.json",
        "drills_path": tmp_path / "research_drills.json",
    }


def _add(paths, **kw):
    kw.setdefault("path", paths["path"])
    defaults = {"title": "Attention Is All You Need", "authors": ["Vaswani", "Shazeer"]}
    defaults.update(kw)
    return rp.add_paper(**defaults)


# ---------------------------------------------------------------- add_paper

def test_add_paper_defaults(paths):
    p = _add(paths)
    assert p["id"] == "attention-is-all-you-need"
    assert p["status"] == "unread"
    assert p["authors"] == ["Vaswani", "Shazeer"]
    assert p["year"] is None
    assert p["venue"] == ""


def test_add_paper_full_record(paths):
    p = _add(paths, venue="NeurIPS", year=2017,
             url="https://arxiv.org/abs/1706.03762",
             abstract="We propose the Transformer.", notes="Read the intro.",
             status="reading")
    assert p["venue"] == "NeurIPS"
    assert p["year"] == 2017
    assert p["abstract"] == "We propose the Transformer."
    assert p["notes"] == "Read the intro."
    assert p["status"] == "reading"
    assert p["date_added"] and p["date_updated"]


def test_add_paper_empty_title_rejected(paths):
    with pytest.raises(rp.ResearchError):
        _add(paths, title="   ")


def test_add_paper_bad_status_rejected(paths):
    with pytest.raises(rp.ResearchError):
        _add(paths, status="skimmed")


def test_add_paper_bad_year_rejected(paths):
    for bad in ("twenty", 3.5, 1500, 3000):
        with pytest.raises(rp.ResearchError):
            _add(paths, year=bad)
    ok = _add(paths, title="Other paper", year="2020")
    assert ok["year"] == 2020


def test_add_paper_authors_string_split(paths):
    p = _add(paths, authors="Alice Smith, Bob Jones; Carol Lee")
    assert p["authors"] == ["Alice Smith", "Bob Jones", "Carol Lee"]


def test_add_paper_duplicate_title_unique_slug(paths):
    a = _add(paths)
    b = _add(paths)
    assert a["id"] != b["id"]
    assert b["id"] == a["id"] + "-2"


# ---------------------------------------------------------------- get/list/search

def test_get_paper_round_trip(paths):
    p = _add(paths)
    got = rp.get_paper(p["id"], paths["path"])
    assert got["title"] == p["title"]


def test_get_paper_unknown_id(paths):
    with pytest.raises(rp.ResearchError):
        rp.get_paper("nope", paths["path"])


def test_list_papers_status_filter(paths):
    _add(paths, status="unread")
    _add(paths, title="Second paper", status="read")
    assert len(rp.list_papers(path=paths["path"])) == 2
    assert len(rp.list_papers(status="read", path=paths["path"])) == 1
    with pytest.raises(rp.ResearchError):
        rp.list_papers(status="skimmed", path=paths["path"])


def test_search_papers(paths):
    _add(paths, title="Attention Is All You Need",
         authors=["Vaswani"], abstract="We propose the Transformer.",
         notes="great positional encoding trick")
    assert len(rp.search_papers("transformer", paths["path"])) == 1
    assert len(rp.search_papers("VASWANI", paths["path"])) == 1
    assert len(rp.search_papers("positional encoding", paths["path"])) == 1
    assert rp.search_papers("quantum", paths["path"]) == []
    assert rp.search_papers("   ", paths["path"]) == []


# ---------------------------------------------------------------- status/notes

def test_update_status(paths):
    p = _add(paths)
    out = rp.update_status(p["id"], "summarized", paths["path"])
    assert out["status"] == "summarized"
    assert rp.get_paper(p["id"], paths["path"])["status"] == "summarized"


def test_update_status_bad(paths):
    p = _add(paths)
    with pytest.raises(rp.ResearchError):
        rp.update_status(p["id"], "skimmed", paths["path"])
    with pytest.raises(rp.ResearchError):
        rp.update_status("nope", "read", paths["path"])


def test_append_notes(paths):
    p = _add(paths)
    out = rp.append_notes(p["id"], "Core idea: self-attention.", paths["path"])
    assert "self-attention" in out["notes"]
    out2 = rp.append_notes(p["id"], "Second thought.", paths["path"])
    assert "self-attention" in out2["notes"] and "Second thought" in out2["notes"]


def test_append_notes_empty_or_unknown(paths):
    p = _add(paths)
    with pytest.raises(rp.ResearchError):
        rp.append_notes(p["id"], "   ", paths["path"])
    with pytest.raises(rp.ResearchError):
        rp.append_notes("nope", "x", paths["path"])


# ---------------------------------------------------------------- persistence

def test_persistence_survives_reload(paths):
    p = _add(paths)
    again = rp.get_paper(p["id"], paths["path"])
    assert again["title"] == "Attention Is All You Need"
    raw = json.loads(paths["path"].read_text(encoding="utf-8"))
    assert p["id"] in raw


# ---------------------------------------------------------------- drill questions

def test_build_drill_questions_categories(paths):
    p = _add(paths, venue="NeurIPS", year=2017)
    qs = rp.build_drill_questions(p)
    assert len(qs) == 8
    cats = [q["category"] for q in qs]
    for want in ("main_contribution", "key_method", "baselines",
                 "missing_ablations", "limitations", "extension",
                 "one_sentence_pitch", "hardest_reviewer_question"):
        assert want in cats


def test_drill_questions_use_only_user_metadata(paths):
    p = _add(paths, venue="NeurIPS", year=2017)
    qs = rp.build_drill_questions(p)
    for q in qs:
        assert "Attention Is All You Need" in q["question"]
        assert "GPT" not in q["question"] and "ImageNet" not in q["question"]
    cited = [q for q in qs if q["category"] in
             ("main_contribution", "hardest_reviewer_question")]
    assert all("NeurIPS" in q["question"] and "2017" in q["question"]
               for q in cited)


def test_drill_questions_flag_missing_notes(paths):
    no_notes = rp.build_drill_questions(_add(paths))
    assert all("[fill in]" in q["fill_in_hint"] for q in no_notes)
    with_notes = rp.build_drill_questions(_add(paths, title="P2", notes="has notes"))
    assert all("[fill in]" not in q["fill_in_hint"] for q in with_notes)


# ---------------------------------------------------------------- record + stats

def _scores():
    return [4, 3, 2, 5, 4, 3, 5, 2]


def test_record_drill(paths):
    p = _add(paths)
    s = rp.record_drill(p["id"], _scores(), path=paths["path"],
                        drills_path=paths["drills_path"])
    assert s["paper_id"] == p["id"]
    assert s["avg_confidence"] == 3.5
    assert len(s["items"]) == 8
    assert s["items"][0]["category"] == "main_contribution"
    assert s["started_at"] and s["finished_at"]


def test_record_drill_validates_scores(paths):
    p = _add(paths)
    with pytest.raises(rp.ResearchError):
        rp.record_drill(p["id"], [4, 3], path=paths["path"],
                        drills_path=paths["drills_path"])
    with pytest.raises(rp.ResearchError):
        rp.record_drill(p["id"], [0] * 8, path=paths["path"],
                        drills_path=paths["drills_path"])
    with pytest.raises(rp.ResearchError):
        rp.record_drill(p["id"], [6] * 8, path=paths["path"],
                        drills_path=paths["drills_path"])
    with pytest.raises(rp.ResearchError):
        rp.record_drill("nope", _scores(), path=paths["path"],
                        drills_path=paths["drills_path"])


def test_record_drill_stores_answers(paths):
    p = _add(paths)
    answers = [f"answer {i}" for i in range(8)]
    s = rp.record_drill(p["id"], _scores(), answers=answers,
                        path=paths["path"], drills_path=paths["drills_path"])
    assert s["items"][3]["answer"] == "answer 3"


def test_drill_stats(paths):
    p = _add(paths)
    s0 = rp.drill_stats(p["id"], path=paths["path"], drills_path=paths["drills_path"])
    assert s0["sessions"] == 0
    assert s0["avg_confidence"] is None
    assert s0["weakest_categories"] == []
    rp.record_drill(p["id"], _scores(), path=paths["path"],
                    drills_path=paths["drills_path"])
    rp.record_drill(p["id"], [5] * 8, path=paths["path"],
                    drills_path=paths["drills_path"])
    s = rp.drill_stats(p["id"], path=paths["path"], drills_path=paths["drills_path"])
    assert s["sessions"] == 2
    assert s["avg_confidence"] == 4.25
    assert set(s["weakest_categories"][:2]) == {"baselines", "hardest_reviewer_question"}
    assert s["per_category"]["main_contribution"]["samples"] == 2
    assert rp.drill_history(p["id"], path=paths["path"],
                            drills_path=paths["drills_path"]) != []


def test_drill_interactive(paths):
    p = _add(paths)
    answers = iter(["", "key idea", "", "", "a", "b", "c", "d"])
    confs = iter(["4", "3", "2", "5", "4", "3", "5", "2"])

    def fake_input(prompt):
        if "Confidence" in prompt:
            return next(confs)
        return next(answers)

    printed = []
    s = rp.drill_interactive(p["id"], path=paths["path"],
                             drills_path=paths["drills_path"],
                             input_fn=fake_input, print_fn=printed.append)
    assert s["paper_id"] == p["id"]
    assert len(s["items"]) == 8
    assert any("[1/8]" in line for line in printed)
    assert s["avg_confidence"] is not None


def test_drill_interactive_retries_bad_confidence(paths):
    p = _add(paths)
    confs = iter(["bad", "0", "6", "3"] + ["4"] * 7)
    answers = iter([""] * 8)

    def fake_input(prompt):
        return next(confs) if "Confidence" in prompt else next(answers)

    printed = []
    s = rp.drill_interactive(p["id"], path=paths["path"],
                             drills_path=paths["drills_path"],
                             input_fn=fake_input, print_fn=printed.append)
    assert s["items"][0]["confidence"] == 3


# ---------------------------------------------------------------- render

def test_render_list_and_paper(paths):
    p = _add(paths, venue="NeurIPS", year=2017)
    text = rp.render_list(rp.list_papers(path=paths["path"]))
    assert p["id"] in text and "unread" in text
    assert "No papers yet" in rp.render_list([])
    card = rp.render_paper(p)
    assert "NeurIPS" in card and "2017" in card
    stats = rp.render_drill_stats(rp.drill_stats(p["id"], path=paths["path"],
                                                 drills_path=paths["drills_path"]))
    assert "sessions: 0" in stats

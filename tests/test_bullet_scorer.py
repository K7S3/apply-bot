"""Tests for candid.bullet_scorer (pure functions, no I/O)."""
import re

import pytest

from candid import bullet_scorer as bs


STRONG = ("Built a streaming ETL pipeline in Python serving 2M requests per "
          "day, reducing data latency by 40% and saving $120K annually.")
WEAK = "Responsible for helping with various tasks on the team."
NO_RESULT = "Developed a dashboard for the analytics team."
NO_SCOPE = "Improved checkout conversion by 12%."


def _digits(text):
    return set(re.findall(r"\d[\d,.]*%?", text))


def test_score_bullet_deterministic():
    a = bs.score_bullet(STRONG)
    b = bs.score_bullet(STRONG)
    assert a == b
    assert a["score"] == 100 or a["score"] <= 100
    assert sum(a["breakdown"].values()) == a["score"]
    assert set(a["breakdown"]) == {"action_verb", "result", "scope",
                                   "specificity", "length"}


def test_strong_beats_weak():
    assert bs.score_bullet(STRONG)["score"] > bs.score_bullet(WEAK)["score"]
    assert bs.score_bullet(WEAK)["score"] < 50


def test_weak_verb_detection_with_alternatives():
    res = bs.score_bullet(WEAK)
    weak_flags = [f for f in res["flags"] if f["type"] == "weak_verb"]
    assert weak_flags, "weak lead-in must be flagged"
    assert weak_flags[0]["alternatives"], "alternatives must be suggested"
    assert "responsible for" in weak_flags[0]["detail"]


@pytest.mark.parametrize("bullet,phrase", [
    ("Helped with deployment of the new API.", "helped with"),
    ("Worked on the payments service.", "worked on"),
    ("Assisted with customer onboarding.", "assisted with"),
    ("Tasked with migrating legacy jobs.", "tasked with"),
    ("Involved in the redesign effort.", "involved in"),
])
def test_weak_verb_variants(bullet, phrase):
    res = bs.score_bullet(bullet)
    assert any(f["type"] == "weak_verb" and phrase in f["detail"]
               for f in res["flags"])


def test_missing_result_flagged_with_question_not_invention():
    res = bs.score_bullet(NO_RESULT)
    assert any(f["type"] == "missing_result" for f in res["flags"])
    q = next(f["question"] for f in res["flags"]
             if f["type"] == "missing_result")
    assert q and "?" in q


def test_missing_scope_flagged():
    res = bs.score_bullet(NO_SCOPE)
    assert any(f["type"] == "missing_scope" for f in res["flags"])


def test_suggest_reword_weak_verb_no_invention():
    out = bs.suggest_reword(WEAK)
    assert out["changed"] is True
    assert not out["reworded"].lower().startswith("responsible for")
    # no digits/claims absent from the input
    assert _digits(out["reworded"]) <= _digits(WEAK)
    # the rest of the sentence is preserved verbatim
    assert "helping with various tasks on the team" in out["reworded"]
    # missing facts became questions, not claims
    assert out["questions"], "missing result/scope must yield questions"


def test_suggest_reword_never_adds_metrics():
    corpus = [
        "Responsible for maintaining the data pipeline.",
        "Helped with deployment of services.",
        "Worked on the reporting dashboard for finance.",
        "Assisted with testing new features.",
        "Involved in migrating legacy systems to the cloud.",
        "Developed internal tools for the support team.",
    ]
    for bullet in corpus:
        out = bs.suggest_reword(bullet)
        # every digit-bearing token in the reword must exist in the input
        assert _digits(out["reworded"]) <= _digits(bullet), bullet
        assert "$" not in out["reworded"] or "$" in bullet, bullet
        # no percent claims invented
        assert out["reworded"].count("%") <= bullet.count("%"), bullet


def test_suggest_reword_strong_bullet_asks_questions():
    out = bs.suggest_reword(NO_RESULT)
    assert out["questions"], "a bullet with no result must prompt the user"
    assert any("?" in q for q in out["questions"])


def test_suggest_reword_uses_only_bullet_words():
    bullet = "Responsible for building ETL pipelines in Python."
    out = bs.suggest_reword(bullet, profile_skills=["python", "sql"])
    vocab = {w.lower() for w in re.findall(r"[A-Za-z0-9'+.#]+",
                                           bullet + " python sql")}
    glue = {"owned", "led", "drove", "the", "a", "an", "and", "for",
            "with", "in", "on", "of", "to"}
    for w in re.findall(r"[A-Za-z']+", out["reworded"]):
        assert w.lower() in vocab | glue, f"unexpected new word: {w}"


def test_suggest_reword_empty_raises():
    with pytest.raises(bs.BulletScorerError):
        bs.suggest_reword("   ")


def test_score_resume_overall_and_fixes():
    md = ("# Jane\n\n## Experience\n\n### Engineer — Acme\n2020 - 2022\n"
          f"- {STRONG}\n- {WEAK}\n- {NO_RESULT}\n")
    res = bs.score_resume(md)
    assert res["bullet_count"] == 3
    assert 0 <= res["overall"] <= 100
    assert len(res["bullets"]) == 3
    # fixes prioritized: lowest score first, only sub-70 bullets
    scores = [f["score"] for f in res["fixes"]]
    assert scores == sorted(scores)
    assert all(s < 70 for s in scores)
    assert any(f["bullet"] == WEAK for f in res["fixes"])
    assert all("question" in f for f in res["fixes"])


def test_score_resume_no_bullets_raises():
    with pytest.raises(bs.BulletScorerError):
        bs.score_resume("# Jane\n\nNo bullets here.\n")


def test_score_bullet_empty_raises():
    with pytest.raises(bs.BulletScorerError):
        bs.score_bullet("")


def test_length_sanity():
    tiny = bs.score_bullet("Did stuff.")
    assert tiny["breakdown"]["length"] < bs.WEIGHTS["length"]
    assert any(f["type"] == "too_short" for f in tiny["flags"])
    long_bullet = ("Led the comprehensive end-to-end redesign and "
                   "reimplementation of the entire global payments "
                   "orchestration platform spanning twelve microservices "
                   "across three cloud regions while mentoring a team of "
                   "eight engineers and coordinating with product managers "
                   "and stakeholders in four different time zones every week.")
    res = bs.score_bullet(long_bullet)
    assert any(f["type"] == "too_long" for f in res["flags"])

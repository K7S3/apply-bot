"""Tests for candid/drafting/voice.py -- style learning from approved samples."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid.drafting import voice  # noqa: E402


SAMPLES = [
    {
        "subject": "Re: Staff Engineer interview",
        "body": (
            "Hi Maya,\n\n"
            "Thanks for the chat today. I'd love to move forward. "
            "I'm excited about the team.\n\n"
            "Best,\nKeshavan"
        ),
    },
    {
        "subject": "Re: follow-up",
        "body": (
            "Hi Maya,\n\n"
            "Just following up on last week's note. Don't want this to slip.\n\n"
            "Best,\nKeshavan"
        ),
    },
    {
        "subject": "Re: offer timeline",
        "body": (
            "Hello Priya,\n\n"
            "Circling back here. Could you share the timeline?\n\n"
            "Thanks,\nKeshavan"
        ),
    },
]


def test_learn_style_stats():
    p = voice.learn_style(SAMPLES)
    assert p["sample_count"] == 3
    # most common opening line across the three samples
    assert p["greeting"] == "Hi Maya,"
    # most common closing line
    assert p["signoff"] == "Keshavan"
    # hand-computed from the sample bodies:
    # words per body: 19 + 16 + 12 = 47 -> avg 15.67
    assert p["avg_body_words"] == 15.67
    # apostrophe forms: "I'd", "I'm", "week's" (possessive counts), "Don't"
    # = 4 / 47 words = 0.085
    assert p["contraction_rate"] == 0.085
    # sentences only count segments ending in .!? ("Hi Maya," has none);
    # sentence word counts: 5,5,5,7,5,3,5 = 35 over 7 sentences -> 5.0
    assert p["avg_sentence_len"] == 5.0


def test_learn_style_tie_is_deterministic():
    tied = [
        {"subject": "a", "body": "Hi A,\n\nBody one.\n\nBye"},
        {"subject": "b", "body": "Hi B,\n\nBody two.\n\nBye"},
    ]
    p1 = voice.learn_style(tied)
    p2 = voice.learn_style(tied)
    # tie broken by first-seen order, stable across runs
    assert p1["greeting"] == "Hi A,"
    assert p1 == p2


def test_learn_style_empty_samples():
    p = voice.learn_style([])
    assert p == {
        "avg_sentence_len": 0.0,
        "greeting": "",
        "signoff": "",
        "contraction_rate": 0.0,
        "avg_body_words": 0.0,
        "sample_count": 0,
    }
    # also tolerates None
    assert voice.learn_style(None)["sample_count"] == 0


def test_apply_style_rewrites_edges():
    profile = voice.learn_style(SAMPLES)
    draft = {"subject": "Re: hello", "body": "Hey there,\n\nQuick note.\n\nCheers,\nK"}
    out = voice.apply_style(draft, profile)
    assert out["subject"] == "Re: hello"
    lines = [ln for ln in out["body"].splitlines() if ln.strip()]
    assert lines[0] == "Hi Maya,"
    assert lines[-1] == "Keshavan"
    assert "Quick note." in out["body"]
    assert sorted(out["changed"]) == ["greeting", "signoff"]


def test_apply_style_no_change_when_already_matching():
    profile = voice.learn_style(SAMPLES)
    draft = {"subject": "s", "body": "Hi Maya,\n\nBody here.\n\nBest,\nKeshavan"}
    out = voice.apply_style(draft, profile)
    assert out["changed"] == []
    assert out["body"] == draft["body"]


def test_apply_style_neutral_profile_is_noop():
    draft = {"subject": "s", "body": "Hey,\n\nBody.\n\nLater"}
    out = voice.apply_style(draft, voice.learn_style([]))
    assert out["changed"] == []
    assert out["body"] == draft["body"]


def test_apply_style_single_line_body():
    profile = {"greeting": "Hi Sam,", "signoff": "Thanks"}
    out = voice.apply_style({"subject": "s", "body": "One line only"}, profile)
    assert out["body"] == "Hi Sam,"
    assert out["changed"] == ["greeting"]  # signoff not forced onto same line

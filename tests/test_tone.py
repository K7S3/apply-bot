"""Tests for candid.tone: the tone tuner for outreach drafts."""

import pytest

from candid.tone import detect_tone, list_tones, match_voice, tune

DRAFT = (
    "Subject: Following up - Senior SWE interview\n\n"
    "Hi Priya,\n\n"
    "I hope you're doing well! I was wondering if you could share any updates "
    "on the Senior SWE interview process at Acme. We last spoke on March 3, "
    "and I am excited about the 2 openings on the team.\n\n"
    "Thanks so much for your time.\n\n"
    "Best,\n"
    "Keshavan"
)

FACTS = ["Priya", "March 3", "Acme", "Senior SWE", "2", "Keshavan"]


def test_list_tones():
    assert list_tones() == ["warm", "formal", "concise", "enthusiastic", "direct"]


@pytest.mark.parametrize("tone", list_tones())
def test_facts_preserved_all_tones(tone):
    out = tune(DRAFT, tone)
    for fact in FACTS:
        assert fact in out, f"fact {fact!r} dropped by tone {tone!r}"


@pytest.mark.parametrize("tone", list_tones())
def test_no_em_dashes_all_tones(tone):
    out = tune(DRAFT, tone)
    assert "\u2014" not in out
    assert "\u2013" not in out


@pytest.mark.parametrize("tone", list_tones())
def test_tune_deterministic(tone):
    assert tune(DRAFT, tone) == tune(DRAFT, tone)


def test_formal_greeting_and_closer():
    out = tune(DRAFT, "formal")
    assert "Dear Priya," in out
    assert "Sincerely," in out


def test_warm_closer():
    assert "Warm regards," in tune(DRAFT, "warm")


def test_concise_drops_pleasantry_and_shrinks():
    out = tune(DRAFT, "concise")
    assert "I hope you're doing well" not in out
    assert len(out) < len(DRAFT)


def test_enthusiastic_adds_energy():
    out = tune(DRAFT, "enthusiastic")
    assert "Hi Priya!" in out


def test_direct_removes_hedge():
    out = tune(DRAFT, "direct")
    assert "I was wondering if" not in out
    assert "Could you" in out


def test_invalid_tone_raises():
    with pytest.raises(ValueError):
        tune(DRAFT, "sarcastic")


def test_empty_draft_raises():
    with pytest.raises(ValueError):
        tune("", "warm")
    with pytest.raises(ValueError):
        tune("   \n  ", "warm")


def test_match_voice_adopts_greeting_and_signoff():
    sample = "Hey Sam,\n\nJust a quick note here.\n\nCheers,\nSam"
    out = match_voice(DRAFT, sample)
    assert "Hey Priya," in out
    assert "Cheers," in out
    assert "Keshavan" in out  # draft's own name line kept
    assert "Sam" not in out


def test_match_voice_shortens_long_sentences():
    long_draft = (
        "Hi Priya,\n\n"
        "I wanted to follow up on our conversation last Tuesday, because the "
        "role sounds like a great fit for my background, and I would love to "
        "hear about next steps soon.\n\n"
        "Best,\n"
        "Keshavan"
    )
    sample = "Hey Sam,\n\nNoted. Will reply soon.\n\nBest,\nSam"
    before = [s for s in long_draft.split("\n\n")[1].split(". ") if s]
    out = match_voice(long_draft, sample)
    after = [s for s in out.split("\n\n")[1].split(". ") if s]
    assert len(after) > len(before)


def test_match_voice_joins_toward_long_sample():
    short_draft = (
        "Hi Priya,\n\n"
        "Thanks for the update. Happy to wait. Let me know anytime.\n\n"
        "Best,\n"
        "Keshavan"
    )
    sample = (
        "Hello Sam,\n\n"
        "Thank you very much for the detailed update on the interview process, "
        "which I have now shared with the entire hiring committee for review, "
        "and I will follow up with you as soon as we have reached a decision "
        "on the next steps in this process together.\n\n"
        "Sincerely,\n"
        "Sam"
    )
    out = match_voice(short_draft, sample)
    assert "Hello Priya," in out
    assert "Sincerely," in out
    assert out.split("\n\n")[1].count(";") >= 1


def test_match_voice_adopts_contractions():
    sample = (
        "Hey Sam,\n\n"
        "I don't think we're ready yet, but I'll keep you posted on it.\n\n"
        "Best,\n"
        "Sam"
    )
    out = match_voice(DRAFT, sample)
    assert "I'm excited" in out


def test_match_voice_expands_when_sample_avoids_contractions():
    draft = "Hi Priya,\n\nI don't have updates yet but I'll ask.\n\nBest,\nKeshavan"
    sample = "Dear Sam,\n\nI do not have updates yet but I will ask.\n\nSincerely,\nSam"
    out = match_voice(draft, sample)
    assert "do not" in out
    assert "don't" not in out


def test_match_voice_empty_inputs_raise():
    with pytest.raises(ValueError):
        match_voice("", "Hey Sam,\n\nHi.\n\nBest,\nSam")
    with pytest.raises(ValueError):
        match_voice(DRAFT, "")
    with pytest.raises(ValueError):
        match_voice(DRAFT, "   ")


def test_detect_tone_formal():
    text = (
        "Dear Mr. Rao,\n\n"
        "Thank you for speaking with me about the role. I found our "
        "discussion very insightful.\n\n"
        "Sincerely,\nKeshavan"
    )
    assert detect_tone(text) == "formal"


def test_detect_tone_warm():
    text = (
        "Hi Priya,\n\n"
        "Thanks so much for your time today. I really appreciate it, "
        "and I hope you're doing well.\n\n"
        "Warm regards,\nKeshavan"
    )
    assert detect_tone(text) == "warm"


def test_detect_tone_enthusiastic():
    text = (
        "Hi Priya!\n\n"
        "I loved our chat! I am so excited about the role and can't wait "
        "for next steps!\n\n"
        "Best,\nKeshavan"
    )
    assert detect_tone(text) == "enthusiastic"


def test_detect_tone_concise():
    text = "Hi Priya,\n\nAny updates on the role? Still interested.\n\nBest,\nKeshavan"
    assert detect_tone(text) == "concise"


def test_detect_tone_direct():
    text = (
        "Hello Priya,\n\n"
        "Could you please send the interview timeline? Please confirm by Friday.\n\n"
        "Best,\nKeshavan"
    )
    assert detect_tone(text) == "direct"


def test_detect_tone_empty_raises():
    with pytest.raises(ValueError):
        detect_tone("")
    with pytest.raises(ValueError):
        detect_tone("   ")

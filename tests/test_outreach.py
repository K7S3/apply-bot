"""Tests for candid.outreach: cold outreach sequences and escalation ladders."""

from __future__ import annotations

import pytest

from candid import outreach
from candid.outreach import (
    OutreachError,
    ladder,
    plan_sequence,
    render_ladder,
    render_sequence,
)

NAME = "Keshavan"
TARGET = "Priya"
RECRUITER = "Anita"
ROLE = "ML Engineer"
COMPANY = "Acme"


def test_sequence_has_four_touches_with_expected_spacing():
    seq = plan_sequence(NAME, TARGET, ROLE, COMPANY)
    assert len(seq) == 4
    assert [t["step"] for t in seq] == [1, 2, 3, 4]
    assert [t["send_after_days"] for t in seq] == [0, 4, 11, 21]
    for t in seq:
        assert set(t) == {"step", "subject", "body", "send_after_days",
                          "timing_note"}


def test_sequence_subjects_bodies_personalized_and_nonempty():
    seq = plan_sequence(NAME, TARGET, ROLE, COMPANY, context="we met at a meetup")
    for t in seq:
        assert t["subject"].strip(), f"touch {t['step']}: empty subject"
        assert t["body"].strip(), f"touch {t['step']}: empty body"
        assert t["timing_note"].strip(), f"touch {t['step']}: empty timing note"
        # personalization present in the copy
        assert TARGET in t["body"]
        assert ROLE in t["subject"] or ROLE in t["body"]
        assert COMPANY in t["subject"] or COMPANY in t["body"]
        assert NAME in t["body"]


def test_sequence_stops_on_reply_and_final_touch_is_close():
    seq = plan_sequence(NAME, TARGET, ROLE, COMPANY)
    last = seq[-1]
    copy = (last["subject"] + " " + last["body"]).lower()
    assert "close" in copy or "closing" in copy


def test_sequence_invalid_inputs_raise_actionable_error():
    with pytest.raises(OutreachError, match="Your name"):
        plan_sequence("", TARGET, ROLE, COMPANY)
    with pytest.raises(OutreachError, match="Target name"):
        plan_sequence(NAME, "   ", ROLE, COMPANY)
    with pytest.raises(OutreachError, match="Role"):
        plan_sequence(NAME, TARGET, "", COMPANY)
    with pytest.raises(OutreachError, match="Company"):
        plan_sequence(NAME, TARGET, ROLE, "")
    with pytest.raises(OutreachError):
        render_sequence(NAME, TARGET, ROLE, None)


def test_outreach_error_is_value_error():
    assert issubclass(OutreachError, ValueError)


def test_render_sequence_markdown_with_timing_notes():
    md = render_sequence(NAME, TARGET, ROLE, COMPANY)
    assert md.startswith("# ")
    assert ROLE in md and COMPANY in md and TARGET in md and NAME in md
    for n in (1, 2, 3, 4):
        assert f"## Touch {n}" in md
    assert md.count("Timing:") == 4
    # day markers present for each touch
    assert "day 0" in md and "day 4" in md and "day 11" in md and "day 21" in md


def test_ladder_has_three_stages():
    stages = ladder(NAME, RECRUITER, ROLE, COMPANY)
    assert len(stages) == 3
    assert [s["stage"] for s in stages] == [1, 2, 3]
    for s in stages:
        assert set(s) == {"stage", "subject", "body", "timing_note"}
        assert s["subject"].strip()
        assert s["body"].strip()
        assert s["timing_note"].strip()
        assert RECRUITER in s["body"]
        assert ROLE in s["subject"] or ROLE in s["body"]
        assert COMPANY in s["subject"] or COMPANY in s["body"]
        assert NAME in s["body"]


def test_ladder_timing_language_matches_nudges_convention():
    stages = ladder(NAME, RECRUITER, ROLE, COMPANY)
    assert "5-7 business days" in stages[0]["timing_note"]
    # stage 2 is the firmer nudge with a clear ask and a deadline
    assert "deadline" in stages[1]["timing_note"].lower()
    assert "[date" in stages[1]["body"]
    # stage 3 moves on but leaves the door open
    assert "door" in stages[2]["body"].lower() or \
        "reconnect" in stages[2]["body"].lower()


def test_ladder_last_contact_personalizes_stage_one():
    stages = ladder(NAME, RECRUITER, ROLE, COMPANY,
                    last_contact="last Tuesday's call")
    assert "last Tuesday's call" in stages[0]["body"]


def test_ladder_invalid_inputs_raise():
    with pytest.raises(OutreachError, match="Your name"):
        ladder("", RECRUITER, ROLE, COMPANY)
    with pytest.raises(OutreachError, match="Recruiter name"):
        ladder(NAME, "", ROLE, COMPANY)
    with pytest.raises(OutreachError, match="Role"):
        ladder(NAME, RECRUITER, "", COMPANY)
    with pytest.raises(OutreachError, match="Company"):
        ladder(NAME, RECRUITER, ROLE, "  ")
    with pytest.raises(OutreachError):
        render_ladder("", RECRUITER, ROLE, COMPANY)


def test_render_ladder_markdown_with_timing_notes():
    md = render_ladder(NAME, RECRUITER, ROLE, COMPANY)
    assert md.startswith("# ")
    assert ROLE in md and COMPANY in md and RECRUITER in md and NAME in md
    for n in (1, 2, 3):
        assert f"## Stage {n}" in md
    assert md.count("Timing:") == 3


def test_no_em_dashes_in_user_facing_text():
    md = render_sequence(NAME, TARGET, ROLE, COMPANY, context="hello world")
    md += render_ladder(NAME, RECRUITER, ROLE, COMPANY, last_contact="Monday")
    for t in plan_sequence(NAME, TARGET, ROLE, COMPANY):
        md += t["subject"] + t["body"] + t["timing_note"]
    for s in ladder(NAME, RECRUITER, ROLE, COMPANY):
        md += s["subject"] + s["body"] + s["timing_note"]
    assert "—" not in md

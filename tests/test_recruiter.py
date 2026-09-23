"""Tests for candid.recruiter."""

from __future__ import annotations

import sys
import types

import pytest

from candid import recruiter
from candid.recruiter import (
    RecruiterError,
    call_prep,
    connection_note,
    connection_notes_for_company,
    recruiter_reply,
    render_call_prep,
    render_reply,
)


# ---------------------------------------------------------------------------
# connection_note
# ---------------------------------------------------------------------------

def test_connection_note_length_cap():
    note = connection_note("Keshavan", "Priya Nair", "Acme Corp",
                           "ML Engineer",
                           context=("Senior Staff Engineer who led the ranking "
                                    "team for five years and shipped the "
                                    "core ads models used across the entire "
                                    "stack with massive impact on revenue."))
    assert len(note) <= 300


def test_connection_note_length_cap_plain():
    note = connection_note("Keshavan", "Priya Nair", "Acme Corp", "ML Engineer")
    assert len(note) <= 300


def test_connection_note_personalization_tokens():
    note = connection_note("Keshavan", "Priya Nair", "Acme Corp",
                           "ML Engineer", context="Staff Engineer there")
    assert "Priya" in note
    assert "Keshavan" in note
    assert "Acme Corp" in note
    assert "ML Engineer" in note


def test_connection_note_bad_input():
    with pytest.raises(ValueError):
        connection_note("", "Priya", "Acme", "ML Engineer")
    with pytest.raises(ValueError):
        connection_note("Keshavan", "", "Acme", "ML Engineer")
    with pytest.raises(ValueError):
        connection_note("Keshavan", "Priya", "  ", "ML Engineer")
    with pytest.raises(ValueError):
        connection_note("Keshavan", "Priya", "Acme", "")


# ---------------------------------------------------------------------------
# connection_notes_for_company (defensive referrals path)
# ---------------------------------------------------------------------------

def _stub_referrals():
    mod = types.ModuleType("candid.referrals")

    def find_referrals(companies, connections=None):
        return {
            "Acme Corp": [
                {"name": "Priya Nair", "position": "Staff Engineer",
                 "connected_on": "12 Jan 2024",
                 "rank_reason": "works at Acme Corp now; senior-level title"},
                {"name": "Tom Lee", "position": "Recruiter",
                 "connected_on": "3 Mar 2023",
                 "rank_reason": "works at Acme Corp now"},
            ]
        }
    mod.find_referrals = find_referrals
    return mod


def test_connection_notes_with_stubbed_referrals(monkeypatch):
    monkeypatch.setitem(sys.modules, "candid.referrals", _stub_referrals())
    notes = connection_notes_for_company("Keshavan", "Acme Corp",
                                         "ML Engineer", top_n=2)
    assert len(notes) == 2
    first = notes[0]
    assert first["contact_name"] == "Priya Nair"
    assert first["position"] == "Staff Engineer"
    assert first["company"] == "Acme Corp"
    # why-this-contact comes from the referral data
    assert "works at Acme Corp now" in first["why_this_contact"]
    assert "Staff Engineer" in first["note"]
    assert "Acme Corp" in first["note"]
    assert len(first["note"]) <= 300


def test_connection_notes_top_n_respected(monkeypatch):
    monkeypatch.setitem(sys.modules, "candid.referrals", _stub_referrals())
    notes = connection_notes_for_company("Keshavan", "Acme Corp",
                                         "ML Engineer", top_n=1)
    assert len(notes) == 1


def test_connection_notes_without_referrals(monkeypatch):
    # Simulate candid.referrals being absent: remove any stub and make the
    # import fail. The worktree has no candid/referrals.py, but guard anyway.
    monkeypatch.delitem(sys.modules, "candid.referrals", raising=False)
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "candid.referrals" or (
                args and args[0] == "candid" and "referrals" in str(kwargs)):
            raise ImportError("No module named 'candid.referrals'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RecruiterError) as exc:
        connection_notes_for_company("Keshavan", "Acme Corp", "ML Engineer")
    assert "connection_note" in str(exc.value)


def test_connection_notes_bad_input():
    with pytest.raises(ValueError):
        connection_notes_for_company("", "Acme", "ML Engineer")
    with pytest.raises(ValueError):
        connection_notes_for_company("Keshavan", "Acme", "ML Engineer", top_n=0)


# ---------------------------------------------------------------------------
# recruiter_reply
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["interested", "not_interested", "need_details"])
def test_reply_all_kinds(kind):
    reply = recruiter_reply(kind, "Keshavan", "Dana", "ML Engineer", "Acme Corp")
    assert set(reply) >= {"subject", "body", "timing_note"}
    assert reply["kind"] == kind
    for token in ("Keshavan", "Dana", "ML Engineer", "Acme Corp"):
        assert token in reply["body"]
    assert "Acme Corp" in reply["subject"]
    md = render_reply(reply)
    assert reply["subject"] in md
    assert "Timing:" in md


def test_reply_interested_asks_for_call():
    reply = recruiter_reply("interested", "Keshavan", "Dana",
                            "ML Engineer", "Acme Corp")
    assert "call" in reply["body"].lower()


def test_reply_not_interested_keeps_door_open():
    reply = recruiter_reply("not_interested", "Keshavan", "Dana",
                            "ML Engineer", "Acme Corp")
    assert "stay in touch" in reply["body"].lower()


def test_reply_need_details_asks_for_band():
    reply = recruiter_reply("need_details", "Keshavan", "Dana",
                            "ML Engineer", "Acme Corp")
    assert "compensation band" in reply["body"].lower()


def test_reply_detail_included():
    reply = recruiter_reply("interested", "Keshavan", "Dana", "ML Engineer",
                            "Acme Corp", detail="I noticed the posting mentions LLM evals.")
    assert "LLM evals" in reply["body"]


def test_reply_invalid_kind():
    with pytest.raises(ValueError):
        recruiter_reply("maybe", "Keshavan", "Dana", "ML Engineer", "Acme Corp")


def test_reply_bad_input():
    with pytest.raises(ValueError):
        recruiter_reply("interested", "", "Dana", "ML Engineer", "Acme Corp")


def test_render_reply_bad_input():
    with pytest.raises(ValueError):
        render_reply({})
    with pytest.raises(ValueError):
        render_reply({"subject": "x"})


# ---------------------------------------------------------------------------
# call_prep
# ---------------------------------------------------------------------------

def test_call_prep_has_both_lists():
    prep = call_prep("ML Engineer", "Acme Corp")
    assert prep["questions_to_ask"]
    assert prep["red_flags"]
    assert all(isinstance(q, str) and q for q in prep["questions_to_ask"])
    assert all(isinstance(f, str) and f for f in prep["red_flags"])


def test_call_prep_covers_key_topics():
    prep = call_prep("ML Engineer", "Acme Corp")
    joined = " ".join(prep["questions_to_ask"]).lower()
    for topic in ("compensation", "team", "interview", "sponsorship",
                  "remote", "backfill"):
        assert topic in joined
    flags = " ".join(prep["red_flags"]).lower()
    for topic in ("compensation", "pressure", "written", "posting"):
        assert topic in flags


def test_call_prep_no_em_dashes():
    prep = call_prep("ML Engineer", "Acme Corp")
    md = render_call_prep(prep)
    assert "\u2014" not in md
    assert "ML Engineer" in md and "Acme Corp" in md


def test_call_prep_bad_input():
    with pytest.raises(ValueError):
        call_prep("", "Acme Corp")
    with pytest.raises(ValueError):
        call_prep("ML Engineer", "  ")

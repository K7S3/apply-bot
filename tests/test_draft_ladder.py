"""Tests for candid/drafting/ladder.py (follow-up tone ladder).

pytest-style; deterministic, no network, no sending.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from candid.drafting import ladder as L  # noqa: E402

CTX = {
    "company": "Acme",
    "role": "ML Engineer",
    "contact_name": "Priya",
    "last_contact_date": "2026-09-01",
    "sender_name": "Keshavan",
}


# --- rung boundaries (applied stage, zero offset) ----------------------------

def test_boundary_day_3_is_rung_1():
    assert L.ladder_for(3, "applied")["rung"] == 1


def test_day_7_still_rung_1():
    assert L.ladder_for(7, "applied")["rung"] == 1


def test_day_8_is_rung_2():
    assert L.ladder_for(8, "applied")["rung"] == 2


def test_day_14_still_rung_2():
    assert L.ladder_for(14, "applied")["rung"] == 2


def test_day_15_is_rung_3():
    assert L.ladder_for(15, "applied")["rung"] == 3


def test_day_21_still_rung_3():
    assert L.ladder_for(21, "applied")["rung"] == 3


def test_day_22_is_rung_4():
    assert L.ladder_for(22, "applied")["rung"] == 4


def test_fresh_days_are_rung_0():
    for d in (0, 1, 2):
        r = L.ladder_for(d, "applied")
        assert r["rung"] == 0, d
        assert r["rung_name"] == "Too early to follow up"


def test_result_dict_shape():
    r = L.ladder_for(10, "applied")
    assert set(r) >= {"rung", "rung_name", "tone", "guidance"}
    assert isinstance(r["rung"], int)
    assert isinstance(r["tone"], str) and r["tone"]


# --- stage adjustments --------------------------------------------------------

def test_interview_stage_runs_faster():
    # day 6 interview -> effective 8 -> rung 2, applied is still rung 1
    assert L.ladder_for(6, "selected_for_interview")["rung"] == 2
    assert L.ladder_for(6, "applied")["rung"] == 1


def test_interview_reaches_breakup_earlier():
    assert L.ladder_for(20, "selected_for_interview")["rung"] == 4
    assert L.ladder_for(20, "applied")["rung"] == 3


def test_offer_stage_runs_slower():
    # day 9 offer -> effective 6 -> rung 1, applied day 9 -> rung 2
    assert L.ladder_for(9, "offer")["rung"] == 1
    assert L.ladder_for(9, "applied")["rung"] == 2


def test_offer_reaches_breakup_later():
    assert L.ladder_for(22, "offer")["rung"] == 3  # effective 19
    assert L.ladder_for(25, "offer")["rung"] == 4  # effective 22


def test_unknown_stage_has_no_offset():
    assert L.ladder_for(10, "bogus") == L.ladder_for(10, "applied") | {
        "stage": "bogus"}


# --- render_ladder_draft ------------------------------------------------------

def test_render_uses_all_context_keys():
    draft = L.render_ladder_draft(L.ladder_for(5, "applied"), CTX)
    assert set(draft) == {"subject", "body", "rung"}
    assert draft["rung"] == 1
    assert "Acme" in draft["subject"]
    assert "ML Engineer" in draft["subject"]
    assert "Priya" in draft["body"]
    assert "Keshavan" in draft["body"]
    assert "2026-09-01" in L.render_ladder_draft(
        L.ladder_for(16, "applied"), CTX)["body"]


def test_render_is_deterministic():
    lad = L.ladder_for(30, "offer")
    assert L.render_ladder_draft(lad, CTX) == L.render_ladder_draft(lad, CTX)


def test_rung_subjects_differ():
    subjects = {L.render_ladder_draft(L.ladder_for(d, "applied"), CTX)["subject"]
                for d in (4, 10, 16, 30)}
    assert len(subjects) == 4


def test_render_missing_context_uses_placeholders():
    draft = L.render_ladder_draft(L.ladder_for(10, "applied"), {})
    assert draft["subject"] and draft["body"]
    assert "there" in draft["body"]  # default contact_name


def test_breakup_draft_offers_graceful_exit():
    draft = L.render_ladder_draft(L.ladder_for(30, "applied"), CTX)
    assert "assume" in draft["body"].lower()
    assert "stop following up" in draft["body"].lower()

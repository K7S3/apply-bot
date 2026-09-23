"""Tests for candid.reject_coach."""

import os
import sys

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-reject-coach"
sys.path.insert(0, "/home/hatch/workspace/candid-batch87")

import pytest  # noqa: E402

from candid import config as C  # noqa: E402
from candid import reject_coach as rc  # noqa: E402


@pytest.fixture(autouse=True)
def clean_data_dir(tmp_path=None):
    # Wipe the data dir before each test; the env var above fixed it pre-import.
    if C.DATA_DIR.exists():
        for child in C.DATA_DIR.iterdir():
            if child.is_file():
                child.unlink()
    C.DATA_DIR.mkdir(parents=True, exist_ok=True)
    yield


def _rejection(stage="technical", notes="", **kw):
    base = {
        "app_id": 1,
        "company": "Acme",
        "role": "ML Engineer",
        "stage": stage,
        "reason_notes": notes,
        "feedback": "",
    }
    base.update(kw)
    return base


# --- categorize ----------------------------------------------------------------

@pytest.mark.parametrize(
    "notes,expected",
    [
        ("Not enough years of experience for the senior bar", "experience_gap"),
        ("They were more experienced than I expected", "experience_gap"),
        ("Ghosted after the onsite, never heard back", "ghosted"),
        ("The recruiter went dark after two pings", "ghosted"),
        ("No remote option, must relocate to Seattle", "location"),
        ("Sponsorship was a hard requirement", "location"),
        ("Salary expectations were above band", "compensation"),
        ("Could not meet my total comp ask", "compensation"),
        ("Headcount freeze, req frozen for Q4", "headcount_freeze"),
        ("Budget cuts killed the opening", "headcount_freeze"),
        ("Culture fit concerns from the panel", "culture_fit"),
        ("Role closed after an internal candidate took it", "role_closed"),
        ("The position was already filled", "role_closed"),
    ],
)
def test_categorize_each_category(notes, expected):
    assert rc.categorize(notes) == expected


@pytest.mark.parametrize("notes", ["", "   ", "Great process, tough panel"])
def test_categorize_unstated(notes):
    assert rc.categorize(notes) == rc.UNSTATED


def test_categorize_first_match_wins_in_dict_order():
    # Both experience_gap ("years of experience") and location ("remote") hit;
    # experience_gap comes first in CATEGORY_KEYWORDS order.
    assert rc.categorize("needed more years of experience for this remote role") == "experience_gap"


# --- next_actions ----------------------------------------------------------------

def test_next_actions_technical_stage():
    actions = rc.next_actions(_rejection(stage="technical", notes="tough panel"))
    texts = [a["action"] for a in actions]
    assert any("Drill coding problems" in t for t in texts)
    assert any("debrief of what stumped you" in t for t in texts)
    assert texts[-1] == "Write a 5-minute debrief while it is fresh." or \
        "Write a 5-minute debrief while it is fresh." in texts
    for a in actions:
        assert set(a) == {"action", "why", "priority"}
        assert a["priority"] in ("high", "medium", "low")


def test_next_actions_highs_first():
    actions = rc.next_actions(_rejection(stage="technical", notes="tough panel"))
    ranks = {"high": 0, "medium": 1, "low": 2}
    order = [ranks[a["priority"]] for a in actions]
    assert order == sorted(order)


def test_next_actions_ghosted():
    actions = rc.next_actions(_rejection(stage="applied", notes="Never heard back, ghosted"))
    texts = [a["action"] for a in actions]
    assert any("7-day follow-up cadence" in t for t in texts)


def test_next_actions_recruiter_screen():
    actions = rc.next_actions(_rejection(stage="recruiter_screen", notes=""))
    texts = [a["action"] for a in actions]
    assert any("JD keywords" in t for t in texts)
    assert any("location" in t.lower() and "remote" in t.lower() for t in texts)


def test_next_actions_onsite_final():
    for stage in ("onsite", "final"):
        texts = [a["action"] for a in rc.next_actions(_rejection(stage=stage, notes=""))]
        assert any("story bank" in t for t in texts)
        assert any("system-design" in t for t in texts)


def test_next_actions_freeze_and_compensation():
    freeze = [a["action"] for a in rc.next_actions(_rejection(notes="hiring freeze, req frozen"))]
    assert any("9 months" in t for t in freeze)
    comp = [a["action"] for a in rc.next_actions(_rejection(notes="salary above band"))]
    assert any("band" in t.lower() for t in comp)


def test_next_actions_unstated_asks_for_feedback():
    texts = [a["action"] for a in rc.next_actions(_rejection(notes=""))]
    assert any("Ask for feedback" in t for t in texts)


def test_next_actions_capped_at_six():
    actions = rc.next_actions(
        _rejection(stage="technical", notes="never heard back and no response and ghosted")
    )
    assert len(actions) <= 6
    assert "Write a 5-minute debrief while it is fresh." in [a["action"] for a in actions]


def test_next_actions_rejects_non_dict():
    with pytest.raises(rc.RejectCoachError):
        rc.next_actions("not a dict")


# --- pattern_advice ----------------------------------------------------------------

def test_pattern_advice_empty():
    assert rc.pattern_advice([]) == [
        "No rejections logged yet - advice appears once there is data."
    ]


def test_pattern_advice_two_onsite():
    advice = rc.pattern_advice([
        _rejection(stage="onsite", notes="tough panel"),
        _rejection(stage="onsite", notes="culture fit concerns"),
    ])
    assert any("onsite" in a.lower() and "story" in a.lower() for a in advice)


def test_pattern_advice_ghosted_top_category():
    advice = rc.pattern_advice([
        _rejection(stage="applied", notes="ghosted, never heard back"),
        _rejection(stage="applied", notes="no response after two emails"),
        _rejection(stage="recruiter_screen", notes="tough screen"),
    ])
    assert any("Ghosting is your most common outcome" in a for a in advice)


def test_pattern_advice_no_feedback():
    advice = rc.pattern_advice([
        _rejection(stage="technical", notes="tough questions"),
        _rejection(stage="technical", notes="tough questions"),
        _rejection(stage="onsite", notes="tough panel"),
    ])
    assert any("feedback" in a.lower() for a in advice)


def test_pattern_advice_honest_not_toxic():
    advice = " ".join(rc.pattern_advice([
        _rejection(stage="onsite", notes="a"),
        _rejection(stage="onsite", notes="b"),
        _rejection(stage="onsite", notes="c"),
    ])).lower()
    assert "everything happens for a reason" not in advice
    assert "keep your chin up" not in advice


# --- morale_summary ----------------------------------------------------------------

def test_morale_summary_counts():
    apps = [
        {"id": 1, "status": "selected_for_interview"},
        {"id": 2, "status": "applied"},
        {"id": 3, "status": "rejected"},
        {"id": 4, "status": "withdrawn"},
        {"id": 5, "status": "offer"},
    ]
    summary = rc.morale_summary(apps, [_rejection(), _rejection()])
    assert summary["applications"] == 5
    assert summary["rejections"] == 2
    assert summary["interviews"] == 1
    assert summary["active"] == 2
    assert "2 applications in flight" in summary["line"]
    assert "1 interviews so far" in summary["line"]


def test_morale_summary_no_rejections_line():
    summary = rc.morale_summary([{"id": 1, "status": "applied"}], [])
    assert "No rejections yet." in summary["line"]


def test_morale_summary_no_apps():
    summary = rc.morale_summary([], [])
    assert "No applications tracked yet" in summary["line"]
    assert summary["active"] == 0


# --- renderers ----------------------------------------------------------------

def test_render_actions():
    actions = rc.next_actions(_rejection(stage="recruiter_screen", notes=""))
    out = rc.render_actions(actions)
    assert "Next actions:" in out
    assert "[high]" in out
    assert rc.render_actions([]) == "No actions."


def test_render_advice():
    out = rc.render_advice(["do the thing"])
    assert "- do the thing" in out


def test_render_morale():
    summary = rc.morale_summary([{"id": 1, "status": "applied"}], [_rejection()])
    out = rc.render_morale(summary)
    assert summary["line"] in out
    assert "Applications: 1" in out

"""Tests for candid.interviewers."""

import json

import pytest

from candid import interviewers as I


@pytest.fixture()
def store(tmp_path):
    """Isolated JSON store path for each test."""
    return tmp_path / "interviewers.json"


def test_add_interviewer_minimal(store):
    rec = I.add_interviewer("Jane Doe", path=store)
    assert rec["id"] == 1
    assert rec["name"] == "Jane Doe"
    assert rec["app_id"] is None
    assert rec["role"] == ""
    assert rec["round_label"] == ""
    assert rec["background"]["title"] is None
    assert rec["background"]["focus_areas"] == []
    assert rec["background"]["public_links"] == []
    assert rec["background"]["talks"] == []
    assert rec["debrief"] == {"asked": [], "signals": [], "follow_up": ""}
    assert rec["created"]  # ISO date string


def test_add_interviewer_full(store):
    rec = I.add_interviewer(
        "Jane Doe",
        app_id=7,
        role=I.InterviewerRole.HIRING_MANAGER,
        round_label="Round 2",
        background={
            "title": "Engineering Manager",
            "team": "Ads Ranking",
            "focus_areas": ["ranking", "experiments"],
            "notes": "user-supplied from a public blog",
        },
        path=store,
    )
    assert rec["app_id"] == 7
    assert rec["role"] == "hiring_manager"
    assert rec["round_label"] == "Round 2"
    assert rec["background"]["title"] == "Engineering Manager"
    assert rec["background"]["focus_areas"] == ["ranking", "experiments"]


def test_add_rejects_empty_name(store):
    with pytest.raises(I.InterviewerError):
        I.add_interviewer("", path=store)


def test_ids_autoincrement(store):
    a = I.add_interviewer("A", path=store)
    b = I.add_interviewer("B", path=store)
    assert b["id"] == a["id"] + 1


def test_list_and_get(store):
    a = I.add_interviewer("A", path=store)
    b = I.add_interviewer("B", path=store)
    assert [r["id"] for r in I.list_interviewers(path=store)] == [a["id"], b["id"]]
    got = I.get_interviewer(a["id"], path=store)
    assert got["name"] == "A"
    assert I.get_interviewer(999, path=store) is None


def test_list_filters_by_app_id(store):
    I.add_interviewer("A", app_id=1, path=store)
    I.add_interviewer("B", app_id=2, path=store)
    I.add_interviewer("C", path=store)
    filtered = I.list_interviewers(app_id=1, path=store)
    assert [r["name"] for r in filtered] == ["A"]


def test_find_by_app(store):
    I.add_interviewer("A", app_id=3, path=store)
    I.add_interviewer("B", app_id=3, path=store)
    I.add_interviewer("C", app_id=4, path=store)
    found = I.find_by_app(3, path=store)
    assert sorted(r["name"] for r in found) == ["A", "B"]
    assert I.find_by_app(999, path=store) == []


def test_remove_interviewer(store):
    a = I.add_interviewer("A", path=store)
    b = I.add_interviewer("B", path=store)
    I.remove_interviewer(a["id"], path=store)
    assert [r["name"] for r in I.list_interviewers(path=store)] == ["B"]
    assert I.get_interviewer(a["id"], path=store) is None


def test_remove_bad_id(store):
    with pytest.raises(I.InterviewerError):
        I.remove_interviewer(999, path=store)


def test_update_background(store):
    rec = I.add_interviewer("A", path=store)
    updated = I.update_background(
        rec["id"],
        title="Senior Engineer",
        team="Core",
        tenure="2 years",
        focus_areas=["caching"],
        public_links=[{"label": "talk", "url": "https://example.com/talk"}],
        talks=[{"title": "Caching deep dive", "topics": ["caching"]}],
        notes="met at a meetup",
        path=store,
    )
    assert updated["background"]["title"] == "Senior Engineer"
    assert updated["background"]["team"] == "Core"
    assert updated["background"]["talks"] == [
        {"title": "Caching deep dive", "topics": ["caching"]}
    ]
    # persisted
    again = I.get_interviewer(rec["id"], path=store)
    assert again["background"]["notes"] == "met at a meetup"


def test_update_background_partial_keeps_other_fields(store):
    rec = I.add_interviewer("A", background={"title": "Eng"}, path=store)
    I.update_background(rec["id"], team="Core", path=store)
    again = I.get_interviewer(rec["id"], path=store)
    assert again["background"]["title"] == "Eng"
    assert again["background"]["team"] == "Core"


def test_update_background_rejects_unknown_field(store):
    rec = I.add_interviewer("A", path=store)
    with pytest.raises(I.InterviewerError):
        I.update_background(rec["id"], scraped_bio="nope", path=store)


def test_update_background_bad_id(store):
    with pytest.raises(I.InterviewerError):
        I.update_background(999, title="x", path=store)


def test_add_debrief(store):
    rec = I.add_interviewer("A", path=store)
    updated = I.add_debrief(
        rec["id"],
        asked=["Tell me about a tough bug", "System design: cache"],
        signals=["probes tradeoffs", "wants metrics"],
        follow_up="Send the cache write-up.",
        path=store,
    )
    assert updated["debrief"]["asked"] == ["Tell me about a tough bug", "System design: cache"]
    assert updated["debrief"]["signals"] == ["probes tradeoffs", "wants metrics"]
    assert updated["debrief"]["follow_up"] == "Send the cache write-up."


def test_add_debrief_appends_and_dedups(store):
    rec = I.add_interviewer("A", path=store)
    I.add_debrief(rec["id"], asked=["Q1"], signals=["S1"], follow_up="first", path=store)
    updated = I.add_debrief(
        rec["id"], asked=["Q1", "Q2"], signals=["S2"], follow_up="", path=store
    )
    assert updated["debrief"]["asked"] == ["Q1", "Q2"]
    assert updated["debrief"]["signals"] == ["S1", "S2"]
    # empty follow_up does not wipe the previous note
    assert updated["debrief"]["follow_up"] == "first"


def test_add_debrief_bad_id(store):
    with pytest.raises(I.InterviewerError):
        I.add_debrief(999, asked=["Q"], path=store)


def test_json_round_trip(store):
    I.add_interviewer(
        "A",
        app_id=1,
        role=I.InterviewerRole.PEER_ENGINEER,
        round_label="Round 1",
        background={"title": "Engineer", "focus_areas": ["infra"]},
        path=store,
    )
    rec = I.get_interviewer(1, path=store)
    I.add_debrief(rec["id"], asked=["Q"], signals=["S"], follow_up="n", path=store)
    raw = json.loads(store.read_text(encoding="utf-8"))
    assert isinstance(raw, list) and len(raw) == 1
    entry = raw[0]
    assert entry["name"] == "A"
    assert entry["background"]["focus_areas"] == ["infra"]
    assert entry["debrief"]["asked"] == ["Q"]


def test_path_override_isolation(tmp_path):
    p1 = tmp_path / "one.json"
    p2 = tmp_path / "two.json"
    I.add_interviewer("A", path=p1)
    assert I.list_interviewers(path=p1) != []
    assert I.list_interviewers(path=p2) == []
    assert not p2.exists()


def test_role_constants():
    assert I.InterviewerRole.HIRING_MANAGER == "hiring_manager"
    assert I.InterviewerRole.PEER_ENGINEER == "peer_engineer"
    assert I.InterviewerRole.BAR_RAISER == "bar_raiser"
    assert I.InterviewerRole.RECRUITER == "recruiter"
    assert I.InterviewerRole.SKIP_LEVEL == "skip_level"
    assert I.InterviewerRole.DOMAIN_SPECIALIST == "domain_specialist"
    assert set(I.ROLES) == {
        "hiring_manager",
        "peer_engineer",
        "bar_raiser",
        "recruiter",
        "skip_level",
        "domain_specialist",
    }
    assert len(I.ROLES) == 6


def test_freeform_role_allowed(store):
    rec = I.add_interviewer("A", role="lunch buddy", path=store)
    assert rec["role"] == "lunch buddy"

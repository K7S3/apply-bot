"""Tests for candid.nonprofit_prep: verified question bank, heuristic
org_status, and the grounded mission-pitch helper."""

from __future__ import annotations

from candid.nonprofit_prep import (
    NONPROFIT_QUESTIONS,
    VALID_CATEGORIES,
    get_questions,
    mission_pitch_helper,
    org_status,
    render_questions,
)

REQUIRED_KEYS = {"q", "category", "source", "url", "reported"}


def test_bank_size_and_categories():
    assert 12 <= len(NONPROFIT_QUESTIONS) <= 18
    cats = {q["category"] for q in NONPROFIT_QUESTIONS}
    assert cats == {"mission", "behavioral", "situational"}
    assert VALID_CATEGORIES == cats


def test_entry_schema_all_keys_non_empty():
    for i, q in enumerate(NONPROFIT_QUESTIONS):
        assert set(q.keys()) >= REQUIRED_KEYS, f"entry {i} missing keys"
        for key in REQUIRED_KEYS:
            val = q[key]
            assert isinstance(val, str) and val.strip(), (
                f"entry {i} key {key!r} is empty"
            )


def test_urls_https_format():
    for i, q in enumerate(NONPROFIT_QUESTIONS):
        assert q["url"].startswith("https://"), f"entry {i} url not https"
        assert " " not in q["url"], f"entry {i} url has spaces"


def test_sources_are_real_published_pages():
    # Every entry must carry a verified published source, not a
    # placeholder domain.
    known_hosts = ("trupathsearch.com", "idealist.org",
                   "alabamanonprofits.org")
    for i, q in enumerate(NONPROFIT_QUESTIONS):
        assert any(h in q["url"] for h in known_hosts), (
            f"entry {i} has unexpected host: {q['url']}"
        )
        assert len(q["source"]) > 10, f"entry {i} source looks fake"


def test_get_questions_default_limit():
    qs = get_questions()
    assert len(qs) == 10
    assert qs == NONPROFIT_QUESTIONS[:10]


def test_get_questions_category_filter():
    mission = get_questions("mission", limit=100)
    assert mission
    assert all(q["category"] == "mission" for q in mission)
    assert len(mission) == sum(
        1 for q in NONPROFIT_QUESTIONS if q["category"] == "mission")
    behavioral = get_questions("behavioral", limit=100)
    assert all(q["category"] == "behavioral" for q in behavioral)
    situational = get_questions("situational", limit=100)
    assert all(q["category"] == "situational" for q in situational)


def test_get_questions_limit_edge_cases():
    assert get_questions(limit=2) == NONPROFIT_QUESTIONS[:2]
    assert get_questions(limit=1000) == NONPROFIT_QUESTIONS
    assert get_questions(limit=0) == []
    assert get_questions(limit=-5) == []


def test_get_questions_unknown_category_empty():
    assert get_questions("technical") == []
    assert get_questions("") == []


def test_render_questions_grouping_and_sources():
    qs = get_questions(limit=100)
    out = render_questions(qs)
    assert "### Mission" in out
    assert "### Behavioral" in out
    assert "### Situational" in out
    # every question text and source URL shows up
    for q in qs:
        assert q["q"] in out
        assert q["url"] in out


def test_render_questions_empty():
    out = render_questions([])
    assert "No nonprofit interview questions" in out


def test_org_status_known_nonprofit():
    res = org_status("Ford Foundation")
    assert set(res.keys()) == {"company", "looks_nonprofit", "signals",
                               "pslf_note"}
    assert res["company"] == "Ford Foundation"
    assert res["looks_nonprofit"] is True
    assert "foundation" in res["signals"]


def test_org_status_known_for_profit():
    res = org_status("Goldman Sachs")
    assert res["looks_nonprofit"] is False
    assert res["signals"] == []


def test_org_status_multiple_markers():
    res = org_status("American Cancer Society Institute Fund")
    assert res["looks_nonprofit"] is True
    assert {"society", "institute", "fund"} <= set(res["signals"])


def test_org_status_signals_are_transparent():
    res = org_status("Tech Coalition")
    assert res["signals"] == ["coalition"]  # exactly why it fired


def test_org_status_pslf_note_links_not_scraped():
    res = org_status("Ford Foundation")
    note = res["pslf_note"]
    assert "studentaid.gov" in note
    assert "apps.irs.gov" in note
    assert "confirm" in note.lower()  # user must confirm, not us


def test_mission_pitch_includes_user_words():
    mission = "provide free tutoring to first-generation college students"
    background = "I tutored high schoolers in math for two years in college"
    out = mission_pitch_helper(mission, background)
    assert mission in out
    assert background in out  # background echoed verbatim


def test_mission_pitch_invents_nothing():
    background = "I volunteered at a food bank on weekends"
    out = mission_pitch_helper("end hunger in our city", background)
    invented = ["10 years", "managed a team", "PhD", "certified",
                "led a department", "$"]
    assert not any(phrase in out for phrase in invented), (
        "pitch must not invent experience, credentials, or numbers"
    )
    # facts must be traceable to the user's own text
    assert background in out


def test_mission_pitch_handles_empty_inputs():
    out = mission_pitch_helper("", "")
    assert "[their mission" in out
    assert "[your background" in out

"""Tests for candid.mission_employers."""

from candid.mission_employers import (
    ALIASES,
    MISSION_EMPLOYERS,
    VALID_TYPES,
    boost_for_watchlist,
    is_mission_employer,
    mission_digest,
    render_digest,
)


def test_entries_have_all_keys_and_https_url():
    assert len(MISSION_EMPLOYERS) >= 40
    for rec in MISSION_EMPLOYERS:
        assert rec["name"]
        assert rec["type"] in VALID_TYPES
        assert rec["cause"]
        assert rec["url"].startswith("https://")


def test_no_duplicate_names_or_urls():
    names = [r["name"].lower() for r in MISSION_EMPLOYERS]
    urls = [r["url"] for r in MISSION_EMPLOYERS]
    assert len(names) == len(set(names))
    assert len(urls) == len(set(urls))


def test_exact_match():
    rec = is_mission_employer("Khan Academy")
    assert rec is not None
    assert rec["name"] == "Khan Academy"
    assert rec["type"] == "nonprofit"


def test_case_variant_and_suffixes():
    assert is_mission_employer("KHAN ACADEMY")["name"] == "Khan Academy"
    assert is_mission_employer("patagonia, inc.")["name"] == "Patagonia"
    assert is_mission_employer("Wikimedia Foundation")["name"] == "Wikimedia Foundation"
    assert is_mission_employer("The Gates Foundation")["name"] == "Bill & Melinda Gates Foundation"


def test_alias_forms():
    assert len(ALIASES) >= 10
    assert is_mission_employer("MSF")["name"] == "Doctors Without Borders"
    assert is_mission_employer("WWF")["name"] == "World Wildlife Fund"
    assert is_mission_employer("CZI")["name"] == "Chan Zuckerberg Initiative"
    assert is_mission_employer("eff")["name"] == "Electronic Frontier Foundation"
    assert is_mission_employer("TFA")["name"] == "Teach for America"


def test_unknown_company_returns_none():
    assert is_mission_employer("Acme Corp") is None
    assert is_mission_employer("") is None
    assert is_mission_employer(None) is None


def test_boost_for_watchlist():
    for name in ("Khan Academy", "patagonia", "MSF", "Gates Foundation"):
        boost = boost_for_watchlist(name)
        assert isinstance(boost, int)
        assert 1 <= boost <= 15
    assert boost_for_watchlist("Acme Corp") == 0
    assert boost_for_watchlist("") == 0


def _sample_jobs():
    return [
        {
            "source": "greenhouse", "source_id": "1", "title": "Curriculum Designer",
            "company": "Khan Academy", "location": "Remote",
            "url": "https://www.khanacademy.org/jobs/1", "description": "",
            "salary_text": "", "remote": True, "posted_at": "2026-09-20",
        },
        {
            "source": "greenhouse", "source_id": "2", "title": "Backend Engineer",
            "company": "Google", "location": "New York, NY",
            "url": "https://example.com/2", "description": "",
            "salary_text": "", "remote": False, "posted_at": "2026-09-21",
        },
        {
            "source": "greenhouse", "source_id": "3", "title": "Field Officer",
            "company": "MSF", "location": "Nairobi",
            "url": "https://example.com/3", "description": "",
            "salary_text": "", "remote": False, "posted_at": "2026-09-21",
        },
    ]


def test_mission_digest_filters_and_tags():
    digest = mission_digest(
        {"name": "Keshavan", "cause_interests": ["education"]},
        _sample_jobs(),
        [{"company": "Patagonia", "note": "new posting matched"}],
    )
    assert digest["profile_name"] == "Keshavan"
    assert digest["cause_interests"] == ["education"]
    assert len(digest["mission_jobs"]) == 2  # Khan Academy + MSF, Google dropped
    assert all("mission_employer" in j for j in digest["mission_jobs"])
    assert len(digest["watchlist_hits"]) == 1
    assert digest["watchlist_hits"][0]["mission_employer"]["name"] == "Patagonia"
    assert digest["cause_breakdown"]["education"] == 1
    assert "2 new mission-sector posting(s)" in digest["summary"]


def test_mission_digest_empty():
    digest = mission_digest({}, [], [])
    assert digest["mission_jobs"] == []
    assert digest["watchlist_hits"] == []
    assert digest["cause_breakdown"] == {}
    assert "No mission-sector" in digest["summary"]


def test_render_digest_sections():
    digest = mission_digest(
        {"name": "Keshavan"},
        _sample_jobs(),
        [{"company": "Patagonia", "note": "new posting matched"}],
    )
    md = render_digest(digest)
    assert "## Summary" in md
    assert "## Mission-sector jobs" in md
    assert "## Watchlist hits at mission employers" in md
    assert "Khan Academy" in md
    assert "Patagonia" in md
    assert "## Cause breakdown" in md


def test_render_digest_empty_state():
    md = render_digest(mission_digest({}, [], []))
    assert "No new mission-sector postings this week" in md
    assert "No watchlist hits at mission employers this week" in md

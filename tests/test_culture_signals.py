"""Tests for candid.culture_signals: JD work-style, benefits, flag extraction."""

import re

from candid import culture_signals as CS


def _job(desc, jid=7, title="Backend Engineer", company="Acme"):
    return {"id": jid, "title": title, "company": company,
            "description": desc}


def _quotes_in(items, desc):
    """Every quote must be a verbatim substring of the JD text."""
    for item in items:
        assert item["quote"] in desc, f"quote not verbatim: {item['quote']!r}"


def _labels(items):
    return [i["label"] for i in items]


# ---------------------------------------------------------------------------
# work-style detection
# ---------------------------------------------------------------------------

def test_fully_remote_detected():
    desc = "We are hiring a backend engineer. This is a fully remote position."
    r = CS.analyze_jd(_job(desc))
    assert "fully remote" in _labels(r["workstyle"])
    _quotes_in(r["workstyle"], desc)


def test_remote_first_detected():
    desc = "We are a remote-first company with engineers in 12 countries."
    r = CS.analyze_jd(_job(desc))
    assert "remote-first" in _labels(r["workstyle"])


def test_hybrid_detected():
    desc = "This is a hybrid role, 3 days a week in our New York office."
    r = CS.analyze_jd(_job(desc))
    assert "hybrid" in _labels(r["workstyle"])
    assert "onsite" not in _labels(r["workstyle"])


def test_onsite_detected():
    desc = "This is an onsite position, five days a week at headquarters."
    r = CS.analyze_jd(_job(desc))
    assert "onsite" in _labels(r["workstyle"])
    assert "hybrid" not in _labels(r["workstyle"])


def test_async_first_detected():
    desc = "We are async-first: most collaboration happens in writing."
    r = CS.analyze_jd(_job(desc))
    assert "async-first" in _labels(r["workstyle"])


def test_timezone_requirement_detected():
    desc = "You must overlap with US time zones for at least 4 hours a day."
    r = CS.analyze_jd(_job(desc))
    assert "timezone requirements" in _labels(r["workstyle"])
    _quotes_in(r["workstyle"], desc)


def test_oncall_detected():
    desc = "You will participate in an on-call rotation one week in six."
    r = CS.analyze_jd(_job(desc))
    assert "on-call" in _labels(r["workstyle"])
    _quotes_in(r["workstyle"], desc)


def test_travel_detected():
    desc = "This role requires up to 25% travel to customer sites."
    r = CS.analyze_jd(_job(desc))
    assert "travel" in _labels(r["workstyle"])
    _quotes_in(r["workstyle"], desc)


def test_workstyle_quote_verbatim():
    desc = "We offer a hybrid schedule and async-first communication."
    r = CS.analyze_jd(_job(desc))
    _quotes_in(r["workstyle"], desc)
    assert len(r["workstyle"]) == 2


# ---------------------------------------------------------------------------
# benefits extraction
# ---------------------------------------------------------------------------

BENEFITS_JD = """Benefits:
- Unlimited PTO and paid parental leave
- 401(k) match up to 4%
- Comprehensive health coverage, medical, dental, and vision
- Stock options with a four-year vest
- $2,000 home office stipend
"""


def test_benefits_pto():
    r = CS.analyze_jd(_job(BENEFITS_JD))
    assert "PTO" in _labels(r["benefits"])
    _quotes_in(r["benefits"], BENEFITS_JD)


def test_benefits_401k():
    r = CS.analyze_jd(_job(BENEFITS_JD))
    labels = _labels(r["benefits"])
    assert "401k" in labels
    item = r["benefits"][labels.index("401k")]
    assert item["quote"] in BENEFITS_JD


def test_benefits_health_equity_stipend_parental():
    r = CS.analyze_jd(_job(BENEFITS_JD))
    labels = _labels(r["benefits"])
    assert "health insurance" in labels
    assert "equity" in labels
    assert "stipends" in labels
    assert "parental leave" in labels
    assert len(r["benefits"]) == 6  # all six categories hit
    _quotes_in(r["benefits"], BENEFITS_JD)


def test_days_off_pto_variant():
    desc = "We offer 20 days of paid time off per year."
    r = CS.analyze_jd(_job(desc))
    assert "PTO" in _labels(r["benefits"])
    _quotes_in(r["benefits"], desc)


# ---------------------------------------------------------------------------
# flag patterns
# ---------------------------------------------------------------------------

def _flag_labels(desc):
    return _labels(CS.analyze_jd(_job(desc))["flags"])


def _flags(desc):
    return CS.analyze_jd(_job(desc))["flags"]


def test_red_family():
    flags = _flags("We're a family here, not just a team.")
    assert len(flags) == 1
    f = flags[0]
    assert f["label"] == "we are a family"
    assert f["severity"] == "red"
    assert f["quote"] == "We're a family"
    assert f["why"]
    assert f["source"] == "JD #7 'Backend Engineer'"


def test_red_rockstar():
    desc = "We are looking for a 10x rockstar developer to join the team."
    flags = _flags(desc)
    assert flags[0]["severity"] == "red"
    assert flags[0]["quote"] in desc


def test_red_ninja():
    flags = _flags("Join us as our next code ninja.")
    assert flags[0]["severity"] == "red"
    assert flags[0]["quote"] == "ninja"


def test_red_wear_many_hats():
    flags = _flags("In this startup you will wear many hats every day.")
    assert flags[0]["label"] == "wear many hats"
    assert flags[0]["severity"] == "red"


def test_red_fast_paced_with_nuance():
    flags = _flags("We thrive in a fast-paced environment.")
    assert flags[0]["label"] == "fast-paced environment"
    assert flags[0]["severity"] == "red"
    # nuance: the why acknowledges it is not purely negative
    assert "growth" in flags[0]["why"].lower()


def test_amber_competitive_salary():
    flags = _flags("We offer competitive salary and great perks.")
    assert flags[0]["label"] == "competitive salary (vague)"
    assert flags[0]["severity"] == "amber"


def test_amber_unlimited_pto():
    flags = _flags("Benefits include unlimited PTO.")
    assert flags[0]["severity"] == "amber"
    assert flags[0]["quote"] == "unlimited PTO"


def test_green_async_first():
    flags = _flags("We are an async-first team with written-first norms.")
    assert flags[0]["label"] == "async-first"
    assert flags[0]["severity"] == "green"


def test_green_no_meeting_days():
    flags = _flags("We keep no-meeting days on Wednesdays for focus time.")
    assert flags[0]["severity"] == "green"


def test_green_transparent_salary_bands():
    flags = _flags("Our transparent salary bands are published internally.")
    assert flags[0]["label"] == "transparent salary bands"
    assert flags[0]["severity"] == "green"


def test_green_defined_oncall_rotation():
    flags = _flags("A defined on-call rotation keeps nights and weekends free.")
    assert flags[0]["label"] == "defined on-call rotation"
    assert flags[0]["severity"] == "green"


def test_flag_quote_verbatim():
    desc = ("We are a family of rockstars who wear many hats in a "
            "fast-paced environment, with competitive salary and unlimited PTO.")
    flags = _flags(desc)
    assert len(flags) == 6
    for f in flags:
        assert f["quote"] in desc
        assert f["source"] == "JD #7 'Backend Engineer'"
        assert f["severity"] in {"red", "amber", "green"}
        assert f["why"]


def test_no_flag_matches_empty():
    r = CS.analyze_jd(_job("Build APIs in Go. 3+ years experience required."))
    assert r["flags"] == []


# ---------------------------------------------------------------------------
# structure, sources, empty input
# ---------------------------------------------------------------------------

def test_every_item_carries_source():
    desc = "Fully remote role. Unlimited PTO. We are a family."
    r = CS.analyze_jd(_job(desc, jid=42, title="DevOps"))
    for key in ("workstyle", "benefits", "flags"):
        for item in r[key]:
            assert item["source"] == "JD #42 'DevOps'"


def test_empty_description():
    r = CS.analyze_jd(_job(""))
    assert r == {"workstyle": [], "benefits": [], "flags": []}


def test_missing_description_key():
    r = CS.analyze_jd({"id": 1, "title": "X", "company": "Y"})
    assert r == {"workstyle": [], "benefits": [], "flags": []}


def test_source_id_fallback():
    job = {"source_id": "remoteok:123", "title": "SRE",
           "company": "Acme", "description": "This is a fully remote role."}
    r = CS.analyze_jd(job)
    assert r["workstyle"][0]["source"] == "JD #remoteok:123 'SRE'"


def test_no_em_dashes_or_emojis():
    desc = ("Fully remote, hybrid friendly, async-first, onsite optional. "
            "Unlimited PTO, 401(k) match, health coverage, stock options, "
            "home office stipend, parental leave. We are a family of "
            "rockstars in a fast-paced environment with competitive salary, "
            "no-meeting days, transparent salary bands, and a defined "
            "on-call rotation.")
    r = CS.analyze_jd(_job(desc))
    blob = repr(r)
    assert "\u2014" not in blob  # no em dashes
    assert not re.search(r"[\U0001F300-\U0001FAFF]", blob)  # no emojis


# ---------------------------------------------------------------------------
# company aggregation
# ---------------------------------------------------------------------------

def test_company_jd_signals_aggregates_and_dedupes():
    j1 = _job("Fully remote role with unlimited PTO.", jid=1,
              company="Acme")
    j2 = _job("Fully remote role with unlimited PTO.", jid=2,
              title="Frontend Engineer", company="Acme")
    j3 = _job("Onsite role, competitive salary.", jid=3,
              title="Designer", company="Acme")
    r = CS.company_jd_signals("Acme", [j1, j2, j3])
    assert r["company"] == "Acme"
    assert r["job_count"] == 3
    # identical (label, quote) hits across JDs dedupe
    assert len([i for i in r["workstyle"]
                if i["label"] == "fully remote"]) == 1
    assert len([i for i in r["benefits"]
                if i["label"] == "PTO"]) == 1
    assert len(r["sources"]) == len(set(r["sources"]))
    assert r["sources"] == ["JD #1 'Backend Engineer'",
                           "JD #3 'Designer'"]
    assert set(r.keys()) == {"company", "job_count", "workstyle",
                             "benefits", "flags", "sources"}


def test_company_jd_signals_filters_other_companies():
    j1 = _job("Fully remote role.", jid=1, company="Acme")
    j2 = _job("Fully remote role.", jid=2, company="OtherCo")
    r = CS.company_jd_signals("Acme", [j1, j2])
    assert r["job_count"] == 1
    assert r["sources"] == ["JD #1 'Backend Engineer'"]


def test_company_jd_signals_case_insensitive_match():
    j1 = _job("Hybrid role.", jid=1, company="acme inc")
    r = CS.company_jd_signals("Acme Inc", [j1])
    assert r["job_count"] == 1


def test_company_jd_signals_empty_jobs():
    r = CS.company_jd_signals("Acme", [])
    assert r["job_count"] == 0
    assert r["workstyle"] == []
    assert r["benefits"] == []
    assert r["flags"] == []
    assert r["sources"] == []


def test_company_jd_signals_aggregation_items_keep_own_source():
    j1 = _job("We are a family here.", jid=1, company="Acme")
    j2 = _job("We offer competitive salary.", jid=2,
              title="PM", company="Acme")
    r = CS.company_jd_signals("Acme", [j1, j2])
    assert len(r["flags"]) == 2
    assert {f["source"] for f in r["flags"]} == {
        "JD #1 'Backend Engineer'", "JD #2 'PM'"}

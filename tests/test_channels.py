"""Tests for candid.channels (direct-apply vs portal guidance) and the
tracker channel field.

Run: python -m pytest tests/test_channels.py -q
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import channels as CH
from candid import tracker as T


CONNS = [
    {"name": "Priya Nair", "company": "Acme Corp", "position": "Senior Engineer",
     "connected_on": "12 Jan 2024"},
    {"name": "Bob Lee", "company": "Other Inc", "position": "Manager",
     "connected_on": "03 Mar 2020"},
]

GH_JOB = {
    "title": "ML Engineer", "company": "Acme Corp",
    "url": "https://boards.greenhouse.io/acme/jobs/123",
    "description": "We are hiring. Apply now!",
    "source": "greenhouse",
    "posted_at": "2 days ago",
}

EMAIL_JOB = {
    "title": "ML Engineer", "company": "Beta LLC",
    "url": "https://beta.example/careers/ml",
    "description": "To apply, please send your resume to jobs@beta.example today.",
    "source": "",
    "posted_at": "2026-09-20",
}

AGG_JOB = {
    "title": "Data Scientist", "company": "Gamma Inc",
    "url": "https://www.indeed.com/viewjob?jk=abc123",
    "description": "Great role. Apply on Indeed.",
    "source": "aggregator",
    "posted_at": "45 days ago",
}


# ---------------------------------------------------------------------------
# ATS identification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("https://boards.greenhouse.io/acme/jobs/1", "Greenhouse"),
    ("https://acme.lever.co/ml-engineer/abc", "Lever"),
    ("https://acme.ashbyhq.com/posting/xyz", "Ashby"),
    ("https://acme.myworkdayjobs.com/en-US/External/job/1", "Workday"),
    ("https://acme.wd1.myworkdayjobs.com/External", "Workday"),
    ("https://jobs-acme.icims.com/jobs/1/job", "iCIMS"),
    ("https://acme.taleo.net/careersection/2/jobdetail.ftl", "Taleo"),
    ("https://smrtr.io/abc", None),  # short links are not identifiable
    ("https://acme.smartrecruiters.com/job/1", "SmartRecruiters"),
    ("https://acme.bamboohr.com/jobs/view.php?id=1", "BambooHR"),
    ("https://apply.workable.com/acme/j/1", "Workable"),
    ("https://jobs.jobvite.com/acme/job/1", "Jobvite"),
    ("https://acme.jazzhr.com/jobs/1", "JazzHR"),
    ("https://acme.breezy.hr/p/abc", "Breezy HR"),
    ("https://jobs.rippling.com/acme/1", "Rippling"),
    ("https://acme.wellfound.com/jobs/1", "Wellfound"),
    ("https://careers.acme.com/jobs/1", None),
    ("", None),
])
def test_identify_ats_hosts(url, expected):
    assert CH.identify_ats(url) == expected


def test_identify_ats_case_insensitive():
    assert CH.identify_ats("https://BOARDS.GREENHOUSE.IO/acme/jobs/1") == "Greenhouse"


def test_identify_ats_text_fallback():
    assert CH.identify_ats("https://careers.acme.com/jobs/1",
                           text="Powered by Greenhouse. Apply below.") == "Greenhouse"


def test_identify_ats_host_wins_over_text():
    assert CH.identify_ats("https://acme.lever.co/x",
                           text="powered by greenhouse") == "Lever"


# ---------------------------------------------------------------------------
# ATS notes
# ---------------------------------------------------------------------------

def test_ats_notes_greenhouse():
    n = CH.ats_notes("Greenhouse")
    assert n["account_required"] is False
    assert n["parsing_quality"] == "good"
    assert n["quirks"] and n["tips"]


def test_ats_notes_workday_account_required():
    n = CH.ats_notes("Workday")
    assert n["account_required"] is True
    assert any("account" in q.lower() for q in n["quirks"])


def test_ats_notes_unknown_generic():
    n = CH.ats_notes("SomeNewATS")
    assert n["ats"] == "SomeNewATS"
    assert n["account_required"] is None
    assert n["tips"]


def test_ats_notes_none_generic():
    n = CH.ats_notes(None)
    assert n["ats"] == "unknown"


def test_all_ats_notes_have_required_keys():
    for ats in CH.ATS_NOTES:
        n = CH.ats_notes(ats)
        assert {"account_required", "parsing_quality", "time_minutes",
                "quirks", "tips"} <= set(n), ats


# ---------------------------------------------------------------------------
# Aggregators
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("https://www.indeed.com/viewjob?jk=1", "Indeed"),
    ("https://www.glassdoor.com/job-listing/x", "Glassdoor"),
    ("https://www.ziprecruiter.com/jobs/1", "ZipRecruiter"),
    ("https://www.linkedin.com/jobs/view/123", "LinkedIn Jobs"),
    ("https://boards.greenhouse.io/acme/jobs/1", None),
    ("https://careers.acme.com/jobs/1", None),
    ("", None),
])
def test_aggregator_info(url, expected):
    info = CH.aggregator_info(url)
    assert (info or {}).get("aggregator") == expected
    if expected:
        assert "company" in info["warning"].lower() or "stale" in info["warning"].lower()


# ---------------------------------------------------------------------------
# Direct-email extraction
# ---------------------------------------------------------------------------

def test_extract_apply_emails_found():
    text = "Interested? Send your resume to jobs@acme.example and we will reply."
    out = CH.extract_apply_emails(text)
    assert [e["email"] for e in out] == ["jobs@acme.example"]
    assert out[0]["context"]


def test_extract_apply_emails_ignores_noreply():
    text = "Apply now. Questions? noreply@acme.example (do not reply)."
    assert CH.extract_apply_emails(text) == []


def test_extract_apply_emails_ignores_contextless_mentions():
    # A bare email with no apply context and no hiring-like local part is skipped.
    text = "Our office wifi password was emailed by it-help@acme.example last week."
    assert CH.extract_apply_emails(text) == []


def test_extract_apply_emails_hiring_inbox_without_hint():
    text = "Reach the team at hiring@acme.example for details."
    out = CH.extract_apply_emails(text)
    assert [e["email"] for e in out] == ["hiring@acme.example"]


def test_extract_apply_emails_dedupes():
    text = "Send resume to jobs@acme.example. Again: jobs@acme.example."
    assert len(CH.extract_apply_emails(text)) == 1


def test_extract_apply_emails_empty():
    assert CH.extract_apply_emails("") == []


# ---------------------------------------------------------------------------
# Channel classification + recommendation
# ---------------------------------------------------------------------------

def test_classify_ats_portal():
    c = CH.classify_channels(GH_JOB)
    assert c["ats_portal"]["available"] is True
    assert "Greenhouse" in c["ats_portal"]["detail"]
    assert c["aggregator"]["available"] is False


def test_classify_direct_email():
    c = CH.classify_channels(EMAIL_JOB)
    assert c["direct_email"]["available"] is True
    assert "jobs@beta.example" in c["direct_email"]["detail"]


def test_classify_aggregator():
    c = CH.classify_channels(AGG_JOB)
    assert c["aggregator"]["available"] is True
    assert c["company_site"]["available"] is False


def test_classify_company_site():
    c = CH.classify_channels(EMAIL_JOB)
    assert c["company_site"]["available"] is True


def test_classify_empty_job():
    c = CH.classify_channels({})
    assert set(c) == {"referral", "direct_email", "ats_portal",
                      "company_site", "linkedin_easy_apply", "aggregator"}


def test_recommend_referral_first():
    ref = CH.referral_path("Acme Corp", CONNS)
    recs = CH.recommend_channels(GH_JOB, ref)
    assert recs[0]["channel"] == "referral"
    assert "Priya Nair" in recs[0]["why"]


def test_recommend_direct_email_before_portal():
    job = dict(EMAIL_JOB)
    job["url"] = "https://boards.greenhouse.io/beta/jobs/9"
    recs = CH.recommend_channels(job, None)
    order = [r["channel"] for r in recs]
    assert order.index("direct_email") < order.index("ats_portal")


def test_recommend_aggregator_last():
    recs = CH.recommend_channels(AGG_JOB, None)
    assert recs[-1]["channel"] == "aggregator"
    assert "company site" in recs[-1]["next_step"]


def test_recommend_channels_sorted_by_rank():
    recs = CH.recommend_channels(GH_JOB, None)
    ranks = [r["rank"] for r in recs]
    assert ranks == sorted(ranks)


def test_recommend_every_rec_has_next_step():
    for job in (GH_JOB, EMAIL_JOB, AGG_JOB):
        for r in CH.recommend_channels(job, None):
            assert r["next_step"] and r["why"] and r["label"]


# ---------------------------------------------------------------------------
# Referral path
# ---------------------------------------------------------------------------

def test_referral_path_finds_connection():
    rp = CH.referral_path("Acme Corp", CONNS)
    assert rp["count"] == 1
    assert rp["best"]["name"] == "Priya Nair"


def test_referral_path_no_match():
    rp = CH.referral_path("Nobody Corp", CONNS)
    assert rp["count"] == 0 and rp["best"] is None


def test_referral_path_empty_company_raises():
    with pytest.raises(CH.ChannelError):
        CH.referral_path("", CONNS)


def test_referral_path_unconfigured_export_raises_helpful():
    with pytest.raises(CH.ChannelError) as e:
        CH.referral_path("Acme Corp", None)
    assert "LinkedIn" in str(e.value)


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------

def test_posting_age_relative():
    job = {"posted_at": "2 days ago"}
    assert CH.posting_age_days(job, now=datetime(2026, 9, 22, 12, 0)) == 2


def test_posting_age_iso():
    job = {"posted_at": "2026-09-20"}
    assert CH.posting_age_days(job, now=datetime(2026, 9, 22, 12, 0)) == 2


def test_posting_age_unknown():
    assert CH.posting_age_days({"posted_at": "sometime"}) is None
    assert CH.posting_age_days({}) is None


@pytest.mark.parametrize("posted_at,verdict", [
    ("1 day ago", "fresh"),
    ("6 days ago", "recent"),
    ("20 days ago", "aging"),
    ("45 days ago", "stale"),
    ("", "unknown"),
])
def test_freshness_verdicts(posted_at, verdict):
    f = CH.freshness_note({"posted_at": posted_at},
                          now=datetime(2026, 9, 22, 12, 0))
    assert f["verdict"] == verdict
    assert f["advice"]


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------

def test_draft_direct_apply_email():
    d = CH.draft_direct_apply_email("Keshavan S", "Acme", "ML Engineer",
                                    to_email="jobs@acme.example")
    assert "To: jobs@acme.example" in d
    assert "Subject: Application for ML Engineer" in d
    assert "[LIKE THIS]" not in d  # placeholders use [brackets], spelled out
    assert "[Phone]" in d


def test_draft_direct_apply_email_placeholders():
    d = CH.draft_direct_apply_email("", "", "")
    assert "[Name]" in d and "[Company]" in d and "[Role]" in d


# ---------------------------------------------------------------------------
# Full guide
# ---------------------------------------------------------------------------

def test_guide_keys_and_headline():
    g = CH.guide(GH_JOB, connections=CONNS)
    assert {"title", "company", "url", "ats", "ats_notes", "emails",
            "aggregator", "freshness", "referral", "channels",
            "headline"} <= set(g)
    assert g["ats"] == "Greenhouse"
    assert g["headline"].startswith("Best channel:")
    assert "Referral" in g["headline"]  # Priya is at Acme


def test_guide_referral_error_passthrough():
    g = CH.guide(GH_JOB, connections_error="no export configured")
    assert g["referral"]["error"] == "no export configured"
    assert g["referral"]["count"] == 0


def test_guide_aggregator_warning():
    g = CH.guide(AGG_JOB, connections=CONNS)
    assert g["aggregator"]["aggregator"] == "Indeed"
    assert g["channels"][-1]["channel"] == "aggregator"


def test_render_guide_contains_sections():
    g = CH.guide(EMAIL_JOB, connections=CONNS)
    text = CH.render_guide(g)
    assert "HEADLINE" in text
    assert "Ranked channels" in text
    assert "jobs@beta.example" in text
    assert "Freshness" in text
    assert "Referral path" in text


def test_render_guide_json_serializable():
    g = CH.guide(GH_JOB, connections=CONNS,
                 now=datetime(2026, 9, 22, 12, 0))
    json.dumps(g, default=str)


# ---------------------------------------------------------------------------
# Tracker channel field + stats
# ---------------------------------------------------------------------------

def _tmp_tracker(tmp_path):
    return tmp_path / "apps.json"


def test_tracker_add_channel(tmp_path):
    rec = T.add("Acme", "ML Engineer", channel="referral",
                path=_tmp_tracker(tmp_path))
    assert rec["channel"] == "referral"


def test_tracker_add_channel_normalized(tmp_path):
    rec = T.add("Acme", "ML Engineer", channel="Direct Email",
                path=_tmp_tracker(tmp_path))
    assert rec["channel"] == "direct_email"


def test_tracker_add_channel_invalid(tmp_path):
    with pytest.raises(T.TrackerError):
        T.add("Acme", "ML Engineer", channel="carrier-pigeon",
              path=_tmp_tracker(tmp_path))


def test_tracker_update_channel(tmp_path):
    p = _tmp_tracker(tmp_path)
    rec = T.add("Acme", "ML Engineer", path=p)
    rec = T.update(rec["id"], channel="ats_portal", path=p)
    assert rec["channel"] == "ats_portal"


def test_tracker_update_channel_invalid(tmp_path):
    p = _tmp_tracker(tmp_path)
    rec = T.add("Acme", "ML Engineer", path=p)
    with pytest.raises(T.TrackerError):
        T.update(rec["id"], channel="smoke-signals", path=p)


def test_channel_stats_rates(tmp_path):
    p = _tmp_tracker(tmp_path)
    r1 = T.add("A", "R1", channel="referral", status="applied", path=p)
    r2 = T.add("B", "R2", channel="referral", status="selected_for_interview", path=p)
    T.add("C", "R3", channel="ats_portal", status="rejected", path=p)
    T.add("D", "R4", status="applied", path=p)  # unlogged
    T.update(r1["id"], status="offer", path=p)
    T.update(r2["id"], status="offer", path=p)
    stats = CH.channel_stats(path=p)
    ref = stats["referral"]
    assert ref["applied"] == 2
    assert ref["interviews"] == 2
    assert ref["offers"] == 2
    assert ref["interview_rate"] == 1.0
    ats = stats["ats_portal"]
    assert ats["applied"] == 1 and ats["response_rate"] == 1.0
    assert stats["unlogged"]["applied"] == 1


def test_channel_stats_empty():
    assert CH.channel_stats(path="/nonexistent-dir-xyz/apps.json") == {}


def test_render_channel_stats_table():
    stats = {"referral": {"applied": 2, "interviews": 1, "offers": 0,
                          "rejections": 1, "responses": 2,
                          "response_rate": 1.0, "interview_rate": 0.5}}
    text = CH.render_channel_stats(stats)
    assert "referral" in text and "channel" in text


def test_render_channel_stats_empty():
    assert "guide log" in CH.render_channel_stats({})


def test_channel_labels_cover_channels():
    assert set(CH.CHANNEL_LABELS) == set(CH.CHANNELS)

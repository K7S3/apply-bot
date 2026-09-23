"""Profile-aware defaults: library knobs resolve through the active context.

Uses the contexts engine to create/activate a context with distinctive
values, then asserts each wired knob picks the context value up when not
explicitly passed, that explicit args still win, and that defaults are
unchanged with no active context.

Run: python3 -m pytest tests/test_contexts_defaults.py -q
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config
from candid.contexts import get_store

# Distinctive values: nothing like the builtins, so a pass proves the
# value really came from the context.
DISTINCT = {
    "tailor.tone": "warm",
    "tailor.length": "detailed",
    "jobs.sources": ["other"],
    "jobs.days": 45,
    "jobs.remote_only": True,
    "jobs.min_score": 80,
    "nudges.stale_days": 3,
    "nudges.followup_days": 2,
    "salary.location": "Austin, TX",
}

PROF = {
    "name": "Alex Rivera",
    "location": "New York, NY",
    "headline": "Data Scientist",
    "seniority": "senior",
    "years_experience": 6,
    "skills": ["python", "machine learning", "sql"],
    "experience": [{
        "title": "Senior Data Scientist",
        "company": "Meridian",
        "dates": "2020-2024",
        "bullets": [
            "Built python ML models serving 1M users daily.",
            "Led SQL migration cutting warehouse costs 20 percent.",
            "Mentored 3 junior data scientists on statistics.",
            "Shipped dashboards used by product teams weekly.",
            "Automated reporting pipelines saving 10 hours a week.",
            "Presented model results to executives quarterly.",
        ],
    }],
    "education": [],
}
JD = "Requirements:\n- python\n- machine learning\n- sql\n"


@pytest.fixture()
def ctx_env(monkeypatch, tmp_path):
    """Isolated data dirs, no env overrides, no active context."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "TRACKER_PATH", tmp_path / "tracker.json")
    monkeypatch.setattr(config, "SALARY_DB", tmp_path / "salary.db")
    monkeypatch.setattr(config, "TAILOR_DIR", tmp_path / "tailored")
    for var in ("CANDID_CTX", "CANDID_CTX_COMPANY", "CANDID_CTX_FILE"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


@pytest.fixture()
def active_ctx(ctx_env):
    store = get_store()
    store.create("w1", role="tester", settings=dict(DISTINCT))
    store.set_active("w1")
    return store


# --- tailor --------------------------------------------------------------------


def _resume_tone_marker(text: str) -> str:
    if "loves turning messy" in text:
        return "warm"
    if "offering" in text and "demonstrated success" in text:
        return "formal"
    if "track record of shipping" in text:
        return "confident"
    return "?"


class TestTailorDefaults:
    def test_resume_picks_up_ctx_tone(self, active_ctx):
        from candid import tailor as T
        out = T.build_resume(PROF, JD, company="Acme", role="Data Scientist")
        assert _resume_tone_marker(out) == "warm"

    def test_resume_picks_up_ctx_length(self, active_ctx):
        from candid import tailor as T
        out = T.build_resume(PROF, JD, company="Acme", role="Data Scientist")
        assert out.count("\u2022 ") == 6  # detailed: all six bullets kept

    def test_cover_letter_picks_up_ctx_tone(self, active_ctx):
        from candid import tailor as T
        out = T.build_cover_letter(PROF, JD, "Acme", "Data Scientist")
        assert out.startswith("Hi Acme team,")

    def test_explicit_tone_wins(self, active_ctx):
        from candid import tailor as T
        out = T.build_resume(PROF, JD, company="Acme", role="DS", tone="formal")
        assert _resume_tone_marker(out) == "formal"

    def test_explicit_length_wins(self, active_ctx):
        from candid import tailor as T
        out = T.build_resume(PROF, JD, company="Acme", role="DS",
                             length="one-page")
        assert out.count("\u2022 ") == 4  # one-page: trimmed to four

    def test_invalid_tone_still_rejected_with_ctx(self, active_ctx):
        from candid import tailor as T
        with pytest.raises(ValueError):
            T.build_resume(PROF, JD, tone="shouty")
        with pytest.raises(ValueError):
            T.build_cover_letter(PROF, JD, "Acme", "DS", tone="shouty")

    def test_no_ctx_defaults_unchanged(self, ctx_env):
        from candid import tailor as T
        out = T.build_resume(PROF, JD, company="Acme", role="Data Scientist")
        assert _resume_tone_marker(out) == "confident"
        assert out.count("\u2022 ") == 4
        cl = T.build_cover_letter(PROF, JD, "Acme", "Data Scientist")
        assert cl.startswith("Dear Acme Hiring Team,")


# --- jobs ----------------------------------------------------------------------


def _job(sid, title, company, location, remote, posted_at, desc):
    return {"source": "fake", "source_id": sid, "title": title,
            "company": company, "location": location, "remote": remote,
            "url": "https://example.com/" + sid, "posted_at": posted_at,
            "description": desc, "salary_text": ""}


def _iso_days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


@pytest.fixture()
def fake_adapters():
    from candid import jobs as J
    recent = _job("fake:recent", "Senior Data Scientist", "Acme Corp",
                  "New York, NY", False, _iso_days_ago(0),
                  "We need Python and machine learning for our ML platform. SQL required.")
    old = _job("fake:old", "Data Scientist", "OldCo",
               "New York, NY", False, _iso_days_ago(60),
               "Python machine learning role on the data team. SQL a plus.")
    remote = _job("fake:remote", "Data Scientist", "RemoteCo",
                  "Remote", True, _iso_days_ago(0),
                  "Python machine learning role, fully remote. SQL required.")
    with patch.dict(J.ADAPTERS, {"fake": lambda: [recent, old],
                                 "other": lambda: [remote]}, clear=True):
        yield {"recent": recent, "old": old, "remote": remote}


class TestJobsDefaults:
    def test_days_from_ctx(self, ctx_env, active_ctx, fake_adapters):
        from candid import jobs as J
        res = J.curate(PROF, "data scientist", "", sources=["fake"],
                       remote=False, min_score=0)
        assert [j["source_id"] for j in res["added"]] == ["fake:recent"]

    def test_days_no_ctx_means_no_filter(self, ctx_env, fake_adapters):
        from candid import jobs as J
        res = J.curate(PROF, "data scientist", "", sources=["fake"])
        assert sorted(j["source_id"] for j in res["added"]) == \
            ["fake:old", "fake:recent"]

    def test_explicit_days_wins(self, ctx_env, active_ctx, fake_adapters):
        from candid import jobs as J
        res = J.curate(PROF, "data scientist", "", sources=["fake"], days=90,
                       remote=False, min_score=0)
        assert sorted(j["source_id"] for j in res["added"]) == \
            ["fake:old", "fake:recent"]

    def test_refresh_forwards_ctx_days(self, ctx_env, active_ctx, fake_adapters):
        from candid import jobs as J
        res = J.refresh(PROF, "data scientist", "", sources=["fake"],
                        remote=False, min_score=0)
        assert [j["source_id"] for j in res["added"]] == ["fake:recent"]

    def test_remote_only_from_ctx(self, ctx_env, active_ctx, fake_adapters):
        from candid import jobs as J
        res = J.curate(PROF, "data scientist", "", sources=["other"],
                       min_score=0)
        assert [j["source_id"] for j in res["added"]] == ["fake:remote"]

    def test_remote_only_filters_onsite_when_fetched(self, ctx_env, active_ctx,
                                                     fake_adapters):
        from candid import jobs as J
        res = J.curate(PROF, "data scientist", "",
                       sources=["fake", "other"], min_score=0)
        assert [j["source_id"] for j in res["added"]] == ["fake:remote"]

    def test_explicit_remote_wins(self, ctx_env, active_ctx, fake_adapters):
        from candid import jobs as J
        res = J.curate(PROF, "data scientist", "", sources=["fake"],
                       remote=False, days=90, min_score=0)
        assert sorted(j["source_id"] for j in res["added"]) == \
            ["fake:old", "fake:recent"]

    def test_sources_from_ctx(self, ctx_env, active_ctx, fake_adapters):
        from candid import jobs as J
        res = J.curate(PROF, "data scientist", "", min_score=0)
        assert res["fetched"] == 1  # only the "other" source ran
        assert [j["source_id"] for j in res["added"]] == ["fake:remote"]

    def test_explicit_sources_win(self, ctx_env, active_ctx, fake_adapters):
        from candid import jobs as J
        res = J.curate(PROF, "data scientist", "", sources=["fake"],
                       min_score=0)
        assert res["fetched"] == 2

    def test_min_score_from_ctx(self, ctx_env, active_ctx, fake_adapters):
        from candid import jobs as J
        scored = {"score": 50.0, "why": "test double", "salary": None}
        with patch.object(J, "score_job", return_value=scored):
            res = J.curate(PROF, "data scientist", "", sources=["other"])
        assert res["added"] == []
        assert res["skipped_low_score"] == 1

    def test_explicit_min_score_wins(self, ctx_env, active_ctx, fake_adapters):
        from candid import jobs as J
        scored = {"score": 50.0, "why": "test double", "salary": None}
        with patch.object(J, "score_job", return_value=scored):
            res = J.curate(PROF, "data scientist", "", sources=["other"],
                           min_score=0)
        assert len(res["added"]) == 1
        assert res["skipped_low_score"] == 0

    def test_no_ctx_curate_defaults_unchanged(self, ctx_env, fake_adapters):
        from candid import jobs as J
        # no date filter, not remote-only, min_score 0, all patched sources
        res = J.curate(PROF, "data scientist", "")
        assert res["fetched"] == 3
        assert sorted(j["source_id"] for j in res["added"]) == \
            ["fake:old", "fake:recent", "fake:remote"]
        assert res["skipped_low_score"] == 0


# --- nudges --------------------------------------------------------------------


def _app(app_id, status, days_ago):
    return {"id": app_id, "company": "Acme", "role": "Data Scientist",
            "status": status,
            "date_updated": (date.today() - timedelta(days=days_ago)).isoformat(),
            "notes": ""}


def _kinds(ns):
    return [n["kind"] for n in ns]


class TestNudgesDefaults:
    def test_stale_days_from_ctx(self, ctx_env, active_ctx):
        from candid import nudges as N
        ns = N.pending_nudges([_app(1, "saved", 5)], today=date.today())
        assert "stale_saved" in _kinds(ns)

    def test_followup_days_from_ctx(self, ctx_env, active_ctx):
        from candid import nudges as N
        ns = N.pending_nudges([_app(2, "applied", 3)], today=date.today())
        assert "quiet_applied" in _kinds(ns)

    def test_explicit_thresholds_win(self, ctx_env, active_ctx):
        from candid import nudges as N
        ns = N.pending_nudges([_app(1, "saved", 5), _app(2, "applied", 3)],
                              today=date.today(),
                              stale_days=10, followup_days=10)
        assert "stale_saved" not in _kinds(ns)
        assert "quiet_applied" not in _kinds(ns)

    def test_no_ctx_uses_constants(self, ctx_env):
        from candid import nudges as N
        # STALE_SAVED_DAYS=7, QUIET_APPLIED_DAYS=14, FOLLOW_UP_AFTER_DAYS=5
        apps = [_app(1, "saved", 8), _app(2, "applied", 15),
                _app(3, "selected_for_interview", 6)]
        kinds = _kinds(N.pending_nudges(apps, today=date.today()))
        assert "stale_saved" in kinds
        assert "quiet_applied" in kinds
        assert "follow_up_due" in kinds
        # just under the constants: nothing fires
        apps = [_app(1, "saved", 6), _app(2, "applied", 13),
                _app(3, "selected_for_interview", 4)]
        assert N.pending_nudges(apps, today=date.today()) == []


# --- salary --------------------------------------------------------------------


def _seed_ranges(db_path):
    from candid import salary as S
    for i in range(5):
        S.add_range("Acme", "Data Scientist", 120000 + i * 1000,
                    150000 + i * 1000, location="Austin, TX",
                    source="manual", path=db_path)
        S.add_range("Acme", "Data Scientist", 100000 + i * 1000,
                    130000 + i * 1000, location="Boston, MA",
                    source="manual", path=db_path)


class TestSalaryDefaults:
    def test_location_from_ctx(self, ctx_env, active_ctx):
        from candid import salary as S
        db = ctx_env / "salary.db"
        _seed_ranges(db)
        res = S.lookup(company="Acme", title="Data Scientist", path=db)
        assert res["n"] == 5
        assert {m["location"] for m in res["matches"]} == {"Austin, TX"}

    def test_explicit_location_wins(self, ctx_env, active_ctx):
        from candid import salary as S
        db = ctx_env / "salary.db"
        _seed_ranges(db)
        res = S.lookup(company="Acme", title="Data Scientist",
                       location="Boston, MA", path=db)
        assert res["n"] == 5
        assert {m["location"] for m in res["matches"]} == {"Boston, MA"}

    def test_no_ctx_no_location_filter(self, ctx_env):
        from candid import salary as S
        db = ctx_env / "salary.db"
        _seed_ranges(db)
        res = S.lookup(company="Acme", title="Data Scientist", path=db)
        assert res["n"] == 10


# --- per-company overrides -------------------------------------------------------


class TestPerCompanyOverrides:
    def test_tailor_tone_company_override(self, ctx_env):
        store = get_store()
        store.create("w2", settings={"tailor.tone": "warm"},
                     companies={"Acme": {"tailor.tone": "formal"}})
        store.set_active("w2")
        from candid import tailor as T
        out_acme = T.build_resume(PROF, JD, company="Acme", role="DS")
        assert _resume_tone_marker(out_acme) == "formal"
        out_other = T.build_resume(PROF, JD, company="Other", role="DS")
        assert _resume_tone_marker(out_other) == "warm"

    def test_tailor_tone_company_env(self, ctx_env, monkeypatch):
        store = get_store()
        store.create("w3", settings={"tailor.tone": "warm"},
                     companies={"Globex": {"tailor.tone": "concise"}})
        store.set_active("w3")
        monkeypatch.setenv("CANDID_CTX_COMPANY", "Globex")
        from candid import tailor as T
        # no company passed -> env company override applies
        out = T.build_resume(PROF, JD, role="DS")
        assert "Results-driven" in out  # concise summary template
        # explicit company arg beats the env var
        out2 = T.build_resume(PROF, JD, company="Acme", role="DS")
        assert _resume_tone_marker(out2) == "warm"

    def test_salary_location_company_override(self, ctx_env):
        store = get_store()
        store.create("w4", settings={"salary.location": "Austin, TX"},
                     companies={"Acme": {"salary.location": "Boston, MA"}})
        store.set_active("w4")
        from candid import salary as S
        db = ctx_env / "salary.db"
        _seed_ranges(db)
        res = S.lookup(company="Acme", title="Data Scientist", path=db)
        assert res["n"] == 5
        assert {m["location"] for m in res["matches"]} == {"Boston, MA"}
        res = S.lookup(company="Other", title="Data Scientist", path=db)
        assert res["n"] == 5
        assert {m["location"] for m in res["matches"]} == {"Austin, TX"}


# --- dashboard pass-through ------------------------------------------------------


class TestDashboardDefaults:
    def test_run_tailor_picks_up_ctx_tone(self, ctx_env, active_ctx):
        from candid import dashboard as D
        with patch("candid.profile.load_profile", return_value=PROF):
            res = D.run_tailor("cover-letter", "Acme", "Data Scientist", JD)
        assert res["text"].startswith("Hi Acme team,")

    def test_run_tailor_explicit_tone_wins(self, ctx_env, active_ctx):
        from candid import dashboard as D
        with patch("candid.profile.load_profile", return_value=PROF):
            res = D.run_tailor("cover-letter", "Acme", "Data Scientist", JD,
                               tone="formal")
        assert "Please accept my application" in res["text"]

    def test_run_tailor_no_ctx_defaults(self, ctx_env):
        from candid import dashboard as D
        with patch("candid.profile.load_profile", return_value=PROF):
            res = D.run_tailor("cover-letter", "Acme", "Data Scientist", JD)
        assert res["text"].startswith("Dear Acme Hiring Team,")

    def test_salary_lookup_picks_up_ctx_location(self, ctx_env, active_ctx):
        from candid import dashboard as D
        _seed_ranges(config.SALARY_DB)
        res = D.salary_lookup("Acme", "Data Scientist")
        assert res["n"] == 5
        assert {m["location"] for m in res["matches"]} == {"Austin, TX"}

    def test_salary_lookup_no_ctx(self, ctx_env):
        from candid import dashboard as D
        _seed_ranges(config.SALARY_DB)
        res = D.salary_lookup("Acme", "Data Scientist")
        assert res["n"] == 10

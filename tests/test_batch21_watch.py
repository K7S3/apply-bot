"""Batch 21 (W5): startup prep/watch/digest.

Isolates DATA_DIR via a tmp dir: sets CANDID_DATA_DIR and reloads
candid.config so every module that reads C.DATA_DIR at call time sees
the tmp dir. Feature modules are imported lazily inside tests so the
fixture runs first.
"""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture()
def datadir(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    import candid.config as C
    importlib.reload(C)
    return tmp_path


def _iso(days_ago: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(timespec="seconds")


def _write_jobs_state(datadir, entries):
    p = datadir / "jobs.json"
    p.write_text(json.dumps({
        "last_run": _iso(),
        "seen": {},
        "skipped_low_score": entries,
    }), encoding="utf-8")


def _write_alerts(datadir, alerts):
    p = datadir / "startup_alerts.jsonl"
    p.write_text("\n".join(json.dumps(a) for a in alerts) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# startup_watch: add / remove / list
# ---------------------------------------------------------------------------

def test_watch_add_list(datadir):
    from candid import startup_watch as W
    rec = W.add("Acme AI")
    assert rec["name"] == "Acme AI"
    items = W.list_watched()
    assert [i["name"] for i in items] == ["Acme AI"]


def test_watch_add_duplicate(datadir):
    from candid import startup_watch as W
    W.add("Acme AI")
    dup = W.add("  acme ai ")
    assert dup.get("duplicate") is True
    assert len(W.list_watched()) == 1


def test_watch_add_empty_name_errors(datadir):
    from candid import startup_watch as W
    with pytest.raises(W.StartupWatchError):
        W.add("   ")


def test_watch_remove(datadir):
    from candid import startup_watch as W
    W.add("Acme AI")
    removed = W.remove("ACME ai")
    assert removed["name"] == "Acme AI"
    assert W.list_watched() == []
    with pytest.raises(W.StartupWatchError):
        W.remove("Acme AI")


def test_watch_check_empty_watchlist_errors(datadir):
    from candid import startup_watch as W
    with pytest.raises(W.StartupWatchError):
        W.check()


# ---------------------------------------------------------------------------
# startup_watch: check with synthetic jobs.json (fuzzy + no duplicate alerts)
# ---------------------------------------------------------------------------

def _job(company, title="ML Engineer", sid="arbeitnow:1"):
    return {"source_id": sid, "title": title, "company": company,
            "location": "Remote", "url": "https://example.com/j/1",
            "score": 42.0, "skipped_at": _iso()}


def test_watch_check_alerts_then_no_dupes(datadir):
    from candid import startup_watch as W
    _write_jobs_state(datadir, [_job("Acme AI, Inc.")])
    W.add("acme ai")
    first = W.check()
    assert first["checked"] == 1
    assert len(first["new_alerts"]) == 1
    assert first["new_alerts"][0]["name"] == "acme ai"
    # alerts persisted to the jsonl file
    assert (datadir / "startup_alerts.jsonl").exists()
    # second check: no re-alerts
    second = W.check()
    assert second["new_alerts"] == []


def test_watch_check_fuzzy_and_nonmatch(datadir):
    from candid import startup_watch as W
    _write_jobs_state(datadir, [
        _job("Vercel, Inc.", title="DevEx Engineer", sid="arbeitnow:2"),
        _job("Uber", title="Data Scientist", sid="arbeitnow:3"),
    ])
    W.add("Vercel")
    res = W.check()
    assert len(res["new_alerts"]) == 1
    assert res["new_alerts"][0]["company"] == "Vercel, Inc."


def test_watch_check_missing_jobs_json(datadir):
    from candid import startup_watch as W
    W.add("Acme AI")
    res = W.check()  # no jobs.json -> zero jobs, no crash
    assert res == {"checked": 0, "new_alerts": []}


def test_matches_helper():
    from candid import startup_watch as W
    assert W.matches("Acme", "Acme AI Inc.")
    assert W.matches("acme ai", "ACME AI")
    assert not W.matches("Acme", "Uber")
    assert not W.matches("", "Uber")


# ---------------------------------------------------------------------------
# startup_digest: sections with synthetic data
# ---------------------------------------------------------------------------

def test_digest_new_matches_and_watermark(datadir):
    from candid import startup_digest as D
    _write_jobs_state(datadir, [_job("Acme AI, Inc.")])
    _write_alerts(datadir, [{
        "name": "acme ai", "company": "Acme AI, Inc.", "title": "ML Engineer",
        "source_id": "arbeitnow:1", "url": "", "alerted_at": _iso(days_ago=0),
    }])
    d1 = D.build_digest()
    assert len(d1["new_matches"]) == 1
    # second digest: watermark advanced, nothing new
    d2 = D.build_digest()
    assert d2["new_matches"] == []
    text = D.render_text(d1)
    assert "New watchlist matches" in text
    assert "Acme AI" in text
    md = D.render_markdown(d1)
    assert md.startswith("# Startup digest")


def test_digest_signal_movers(datadir):
    from candid import startup_digest as D
    _write_jobs_state(datadir, [_job("Acme AI, Inc."), _job("Acme AI, Inc.", sid="arbeitnow:2")])
    d1 = D.build_digest()  # snapshot: Acme = 2
    assert d1["signal_movers"]  # new company vs empty snapshot
    _write_jobs_state(datadir, [_job("Acme AI, Inc.", sid="arbeitnow:2")])
    d2 = D.build_digest()  # now 1, delta -1
    movers = d2["signal_movers"]
    assert movers and movers[0]["company"] == "Acme AI, Inc."
    assert movers[0]["delta"] == -1


def test_digest_interviews_this_week(datadir):
    from candid import startup_digest as D
    from candid import tracker as T
    _write_jobs_state(datadir, [])
    T.add("Fresh Startup", "ML Engineer", status="selected_for_interview")
    T.add("Old Startup", "Data Scientist", status="applied")
    d = D.build_digest()
    names = [a["company"] for a in d["interviews_this_week"]]
    assert "Fresh Startup" in names
    assert "Old Startup" not in names
    text = D.render_text(d)
    assert "Fresh Startup" in text


def test_digest_signal_fallback_without_w2_module(datadir):
    # W2's module is absent in this branch; signal_movers must not raise.
    from candid import startup_digest as D
    jobs = [{"company": "Acme AI, Inc."}, {"company": "Uber"}]
    rows = D.signal_movers(jobs, {"Acme AI, Inc.": 1})
    by_co = {r["company"]: r for r in rows}
    assert by_co["Uber"]["delta"] == 1
    assert all(r["source"] == "local" for r in rows)


def test_digest_missing_files_degrade_gracefully(datadir):
    from candid import startup_digest as D
    d = D.build_digest()
    assert d["new_matches"] == []
    assert d["signal_movers"] == []
    assert d["interviews_this_week"] == []
    assert "No new matches" in D.render_text(d)


# ---------------------------------------------------------------------------
# startup_prep: --startup section
# ---------------------------------------------------------------------------

def test_startup_section_content():
    from candid import startup_prep as SP
    s = SP.startup_section("Acme AI", "ML Engineer", jd="seed stage, 0 to 1 build")
    assert "## 9. Startup interview loop" in s
    assert "Founder" in s
    assert "Technical deep-dive" in s
    assert "Boundary" in s  # never does the take-home for the user
    assert "Reference-call prep" in s
    assert "0-to-1" in s  # JD-personalized hint


def test_startup_section_needs_company_role():
    from candid import startup_prep as SP
    with pytest.raises(SP.StartupPrepError):
        SP.startup_section("", "ML Engineer")
    with pytest.raises(SP.StartupPrepError):
        SP.startup_section("Acme", "")


def test_append_startup_section():
    from candid import startup_prep as SP
    base = "# Interview Prep - ML Engineer @ Acme AI\n\nsome content\n"
    out = SP.append_startup_section(base, "Acme AI", "ML Engineer")
    assert "some content" in out
    assert "## 9. Startup interview loop" in out
    assert "does not do the take-home work for you" in out


def test_cli_flags_parse():
    from candid.__main__ import build_parser
    p = build_parser()
    a = p.parse_args(["prep", "--company", "X", "--role", "Y", "--startup"])
    assert a.startup is True
    a = p.parse_args(["prep", "--company", "X", "--role", "Y"])
    assert a.startup is False
    a = p.parse_args(["startups", "watch", "add", "--name", "Acme"])
    assert a.what == "watch" and a.watch_what == "add" and a.name == "Acme"
    a = p.parse_args(["startups", "watch", "check", "--json"])
    assert a.watch_what == "check" and a.json is True
    a = p.parse_args(["startups", "digest", "--json"])
    assert a.what == "digest" and a.json is True

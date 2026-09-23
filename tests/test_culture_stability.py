"""Tests for candid.culture_stability (company culture decoder)."""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta

import pytest

from candid import culture_stability as cs

TODAY = date.today()
YEAR_AGO = TODAY - timedelta(days=365)


def _d(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def _warn(days_ago, workers=100, company="Acme Corp"):
    return {"company": company, "notice_date": _d(days_ago),
            "workers": workers}


def _lca(days_ago, wage=150000, company="Acme Corp"):
    return {"employer_name": company, "case_date": _d(days_ago),
            "wage": wage}


def _job(days_ago, company="Acme Corp"):
    return {"company": company, "posted_date": _d(days_ago), "title": "Eng"}


def _by_signal(signals):
    return {s["signal"]: s for s in signals}


# --- empty / missing datasets -------------------------------------------------

def test_stability_empty_dict_all_insufficient():
    sigs = cs.stability("Acme Corp", {})
    assert len(sigs) == 4
    for s in sigs:
        assert s["value"] is None
        assert s["note"] == "insufficient data"


def test_stability_none_datasets_no_crash():
    sigs = cs.stability("Acme Corp", None)
    assert all(s["value"] is None for s in sigs)


def test_stability_none_values_no_crash():
    sigs = cs.stability("Acme Corp", {"warn": None, "lca": None, "jobs": None})
    assert all(s["value"] is None and s["note"] == "insufficient data"
               for s in sigs)


def test_trajectory_empty_dict_all_insufficient():
    sigs = cs.trajectory("Acme Corp", {})
    assert len(sigs) == 4
    for s in sigs:
        assert s["value"] is None
        assert s["note"] == "insufficient data"


def test_trajectory_non_dict_datasets_no_crash():
    sigs = cs.trajectory("Acme Corp", "junk")
    assert all(s["value"] is None for s in sigs)


def test_empty_company_yields_insufficient():
    sigs = cs.stability("", {"warn": [_warn(10)]})
    assert sigs[0]["value"] is None
    assert "no company name" in sigs[0]["note"]
    sigs = cs.trajectory("   ", {"warn": [_warn(10)]})
    assert sigs[0]["value"] is None


# --- signal shape ---------------------------------------------------------------

def test_signal_dict_shape():
    ds = {"warn": [_warn(10)], "lca": [_lca(10)], "jobs": [_job(10)]}
    for s in cs.stability("Acme", ds) + cs.trajectory("Acme", ds):
        assert isinstance(s["signal"], str) and s["signal"]
        assert s["value"] is None or isinstance(s["value"], str)
        assert isinstance(s["source"], str) and s["source"]
        assert s["as_of"] is None or isinstance(s["as_of"], str)


def test_sources_are_labeled():
    ds = {"warn": [_warn(10)], "lca": [_lca(10)], "jobs": [_job(10)]}
    sigs = _by_signal(cs.stability("Acme", ds))
    assert sigs["layoff filings in last 12 months"]["source"] == "WARN filings"
    assert sigs["LCA filing volume (recent vs prior 6mo)"]["source"] == \
        "LCA disclosure data"
    assert sigs["curated job posting volume (recent vs prior 6mo)"]["source"] == \
        "curated job postings"


def test_no_em_dashes_or_causal_claims_in_output():
    ds = {"warn": [_warn(10, workers=500)],
          "lca": [_lca(d) for d in range(30, 400, 30)] + [_lca(d) for d in range(200, 400, 30)],
          "jobs": [_job(d) for d in range(10, 400, 20)]}
    banned = ["failing", "doomed", "dying", "bankrupt", "collaps", "—"]
    for s in cs.stability("Acme", ds) + cs.trajectory("Acme", ds):
        text = " ".join(str(v) for v in s.values() if v)
        for b in banned:
            assert b not in text.lower(), f"banned {b!r} in {text!r}"


# --- WARN / stability -----------------------------------------------------------

def test_stability_warn_detects_recent_filings():
    ds = {"warn": [_warn(30, workers=200), _warn(60, workers=300)]}
    s = _by_signal(cs.stability("Acme Corp", ds))["layoff filings in last 12 months"]
    assert "2 filing(s)" in s["value"]
    assert "500 workers affected" in s["value"]
    assert s["as_of"] == TODAY.isoformat()


def test_stability_warn_old_filings_excluded_from_12mo():
    ds = {"warn": [_warn(400, workers=200)]}
    s = _by_signal(cs.stability("Acme Corp", ds))["layoff filings in last 12 months"]
    assert s["value"] == "0 filings in last 12 months"


def test_stability_warn_most_recent_date():
    ds = {"warn": [_warn(90), _warn(10)]}
    s = _by_signal(cs.stability("Acme Corp", ds))["most recent layoff filing date"]
    assert s["value"] == _d(10)


def test_stability_warn_malformed_rows_skipped():
    ds = {"warn": [
        _warn(10, workers=100),
        "not a dict",
        {"company": "Acme Corp"},                        # no date
        {"company": "Acme Corp", "notice_date": "garbage"},
        {"company": "Other Inc", "notice_date": _d(5)},   # wrong company
        {"company": "Acme Corp", "notice_date": _d(20)},  # no workers, ok
    ]}
    s = _by_signal(cs.stability("Acme", ds))["layoff filings in last 12 months"]
    assert "2 filing(s)" in s["value"]
    assert "100 workers affected" in s["value"]
    assert "malformed" in s["note"]


def test_stability_warn_accepts_alias_keys():
    ds = {"warn": [{"employer": "Acme", "filed_date": "01/15/2026",
                    "affected": "$250"}]}
    s = _by_signal(cs.stability("Acme", ds))["layoff filings in last 12 months"]
    assert "1 filing(s)" in s["value"]
    assert "250 workers affected" in s["value"]


def test_stability_company_name_normalization():
    ds = {"warn": [_warn(10, company="ACME Corporation")]}
    s = _by_signal(cs.stability("acme", ds))["layoff filings in last 12 months"]
    assert "1 filing(s)" in s["value"]


# --- LCA / jobs volume (stability) ----------------------------------------------

def test_stability_lca_volume_counts():
    ds = {"lca": [_lca(30)] * 8 + [_lca(200)] * 4}
    s = _by_signal(cs.stability("Acme", ds))["LCA filing volume (recent vs prior 6mo)"]
    assert s["value"] == "recent 6 months: 8, prior 6 months: 4"


def test_stability_jobs_volume_counts():
    ds = {"jobs": [_job(30)] * 5 + [_job(300)] * 2}
    s = _by_signal(cs.stability("Acme", ds))[
        "curated job posting volume (recent vs prior 6mo)"]
    assert s["value"] == "recent 6 months: 5, prior 6 months: 2"


def test_stability_lca_bad_rows_skipped():
    ds = {"lca": [{"employer_name": "Acme", "case_date": "not-a-date"},
                  None,
                  _lca(30)]}
    s = _by_signal(cs.stability("Acme", ds))["LCA filing volume (recent vs prior 6mo)"]
    assert s["value"] == "recent 6 months: 1, prior 6 months: 0"
    assert "malformed" in s["note"]


# --- trajectory: layoff activity --------------------------------------------------

def test_trajectory_layoff_present():
    s = _by_signal(cs.trajectory("Acme", {"warn": [_warn(100)]}))["layoff activity"]
    assert s["value"] == "layoff filings present in last 12 months"


def test_trajectory_layoff_absent():
    s = _by_signal(cs.trajectory("Acme", {"warn": [_warn(400)]}))["layoff activity"]
    assert s["value"] == "no layoff filings in last 12 months"


def test_trajectory_layoff_insufficient():
    s = _by_signal(cs.trajectory("Acme", {"warn": []}))["layoff activity"]
    assert s["value"] is None
    assert s["note"] == "insufficient data"


# --- trajectory: velocity directions ----------------------------------------------

def _velocity_ds(key, recent_n, prior_n):
    if key == "lca":
        return {key: [_lca(30)] * recent_n + [_lca(200)] * prior_n}
    return {key: [_job(30)] * recent_n + [_job(200)] * prior_n}


def test_trajectory_lca_velocity_increasing():
    s = _by_signal(cs.trajectory("Acme", _velocity_ds("lca", 10, 4)))["LCA filing velocity"]
    assert s["value"] == "LCA filing volume increasing"


def test_trajectory_hiring_velocity_increasing():
    s = _by_signal(cs.trajectory("Acme", _velocity_ds("jobs", 10, 2)))["hiring velocity"]
    assert s["value"] == "hiring velocity increasing"


def test_trajectory_hiring_velocity_decreasing():
    s = _by_signal(cs.trajectory("Acme", _velocity_ds("jobs", 2, 10)))["hiring velocity"]
    assert s["value"] == "hiring velocity decreasing"


def test_trajectory_hiring_velocity_steady():
    s = _by_signal(cs.trajectory("Acme", _velocity_ds("jobs", 6, 6)))["hiring velocity"]
    assert s["value"] == "hiring velocity steady"


def test_trajectory_velocity_insufficient_when_too_thin():
    s = _by_signal(cs.trajectory("Acme", _velocity_ds("jobs", 1, 0)))["hiring velocity"]
    assert s["value"] is None
    assert s["note"] == "insufficient data"


def test_trajectory_velocity_prior_zero_counts_as_increasing():
    s = _by_signal(cs.trajectory("Acme", _velocity_ds("jobs", 4, 0)))["hiring velocity"]
    assert s["value"] == "hiring velocity increasing"


# --- trajectory: wage direction -----------------------------------------------------

def _wage_ds(recent_wages, prior_wages):
    ds = {"lca": []}
    for w in recent_wages:
        ds["lca"].append({"employer_name": "Acme", "case_date": _d(30), "wage": w})
    for w in prior_wages:
        ds["lca"].append({"employer_name": "Acme", "case_date": _d(200), "wage": w})
    return ds


def test_trajectory_wage_stable():
    s = _by_signal(cs.trajectory("Acme", _wage_ds([150000] * 6, [152000] * 6)))[
        "median offered wage"]
    assert s["value"] == "median offered wage stable"
    assert "$150,000" in s["note"]


def test_trajectory_wage_rising():
    s = _by_signal(cs.trajectory("Acme", _wage_ds([180000] * 6, [140000] * 6)))[
        "median offered wage"]
    assert s["value"] == "median offered wage rising"


def test_trajectory_wage_declining():
    s = _by_signal(cs.trajectory("Acme", _wage_ds([120000] * 6, [150000] * 6)))[
        "median offered wage"]
    assert s["value"] == "median offered wage declining"


def test_trajectory_wage_insufficient_no_rows():
    s = _by_signal(cs.trajectory("Acme", {"lca": [{"employer_name": "Acme"}]}))[
        "median offered wage"]
    assert s["value"] is None
    assert "insufficient" in s["note"]


def test_trajectory_wage_insufficient_one_period_missing():
    s = _by_signal(cs.trajectory("Acme", _wage_ds([150000] * 6, [])))[
        "median offered wage"]
    assert s["value"] is None


def test_trajectory_wage_skips_malformed_wages():
    ds = {"lca": [
        {"employer_name": "Acme", "case_date": _d(30), "wage": "n/a"},
        {"employer_name": "Acme", "case_date": _d(30), "wage": -500},
        {"employer_name": "Acme", "case_date": _d(30), "wage": "$150,000"},
        {"employer_name": "Acme", "case_date": _d(200), "wage": 148000},
    ]}
    s = _by_signal(cs.trajectory("Acme", ds))["median offered wage"]
    assert s["value"] == "median offered wage stable"


# --- date parsing -------------------------------------------------------------------

def test_parse_date_formats():
    assert cs._parse_date("2026-01-15") == date(2026, 1, 15)
    assert cs._parse_date("01/15/2026") == date(2026, 1, 15)
    assert cs._parse_date("2026/01/15") == date(2026, 1, 15)
    assert cs._parse_date("FY2024") == date(2024, 1, 1)
    assert cs._parse_date("garbage") is None
    assert cs._parse_date(None) is None
    assert cs._parse_date(123) is None


def test_parse_number_formats():
    assert cs._parse_number("$150,000") == 150000.0
    assert cs._parse_number(100) == 100.0
    assert cs._parse_number("n/a") is None
    assert cs._parse_number(None) is None
    assert cs._parse_number(True) is None


# --- DATA_DIR fallback --------------------------------------------------------------

def test_load_datasets_from_data_dir_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    import importlib
    import candid.config as cfg
    importlib.reload(cfg)
    try:
        out = cs.load_datasets_from_data_dir()
        assert out == {"warn": [], "lca": [], "jobs": []}
    finally:
        monkeypatch.undo()
        importlib.reload(cfg)


def test_load_datasets_from_data_dir_reads_files(tmp_path, monkeypatch):
    import importlib
    import candid.config as cfg
    (tmp_path / "warn_ca.csv").write_text(
        "company,notice_date,workers\nAcme Corp,2026-01-10,100\n")
    (tmp_path / "jobs_board.json").write_text(
        json.dumps([{"company": "Acme", "posted_date": "2026-02-01"}]))
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    importlib.reload(cfg)
    try:
        out = cs.load_datasets_from_data_dir()
        assert len(out["warn"]) == 1 and out["warn"][0]["workers"] == "100"
        assert len(out["jobs"]) == 1
        assert out["lca"] == []
    finally:
        monkeypatch.undo()
        importlib.reload(cfg)

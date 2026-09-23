"""Tests for the lab/PI watchlist (candid.labs) and the academic
hiring-season calendar (candid.academic_calendar).

Zero network. CANDID_DATA_DIR is pointed at a tmp dir per test.
"""

import argparse
import importlib
import json
import os
from datetime import date

import pytest


# ---------------------------------------------------------------------------
# fixture: isolate user data dir before candid.config is consulted
# ---------------------------------------------------------------------------

@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    # Re-import so DATA_DIR picks up the tmp override (modules read it at
    # call time, so the reload is what re-binds the value).
    import candid.config as C
    importlib.reload(C)
    return tmp_path


# lazy imports: after fixture ensures the env var is set
def labs_mod():
    import candid.labs as L
    return L


def cal_mod():
    import candid.academic_calendar as A
    return A


# ---------------------------------------------------------------------------
# watchlist CRUD round-trip
# ---------------------------------------------------------------------------

def test_watchlist_add_list_remove(data_dir):
    L = labs_mod()
    assert L.list_labs() == []
    e = L.add_lab("Geoffrey Hinton", affiliation="U Toronto")
    assert e["name"] == "Geoffrey Hinton"
    assert e["affiliation"] == "U Toronto"
    e2 = L.add_lab("Yoshua Bengio")
    assert e2["affiliation"] == ""
    assert [x["name"] for x in L.list_labs()] == ["Geoffrey Hinton", "Yoshua Bengio"]
    removed = L.remove_lab("geoffrey hinton")  # case-insensitive
    assert removed["name"] == "Geoffrey Hinton"
    assert [x["name"] for x in L.list_labs()] == ["Yoshua Bengio"]
    with pytest.raises(L.LabsError):
        L.remove_lab("Nobody Famous")
    # persisted JSON on disk
    stored = json.loads((data_dir / "watched_labs.json").read_text())
    assert [x["name"] for x in stored] == ["Yoshua Bengio"]


def test_watchlist_add_duplicate_and_empty(data_dir):
    L = labs_mod()
    L.add_lab("Fei-Fei Li")
    with pytest.raises(L.LabsError):
        L.add_lab("fei-fei li")  # duplicate, case-insensitive
    with pytest.raises(L.LabsError):
        L.add_lab("   ")


# ---------------------------------------------------------------------------
# word-aware matching
# ---------------------------------------------------------------------------

def _watch(L, *names):
    for n in names:
        L.add_lab(n)


def test_matching_case_insensitive(data_dir):
    L = labs_mod()
    _watch(L, "Hinton")
    hits = L.check_labs([{
        "title": "Postdoc: machine learning",
        "company": "U Toronto",
        "description": "Join the lab of GEOFFREY HINTON for deep learning research.",
    }])
    assert len(hits) == 1
    assert hits[0]["lab"] == "Hinton"
    assert hits[0]["matched_field"] == "description"
    assert "HINTON" in hits[0]["snippet"] or "hinton" in hits[0]["snippet"].lower()


def test_matching_multiword_whitespace_tolerant(data_dir):
    L = labs_mod()
    _watch(L, "Geoffrey Hinton")
    hits = L.check_labs([{
        "title": "Research Scientist",
        "company": "Vector Institute",
        "description": "Working with Geoffrey\nHinton on neural networks.",
    }])
    assert len(hits) == 1


def test_no_substring_false_positive(data_dir):
    # "lab" must not match inside "collaborate"
    L = labs_mod()
    _watch(L, "AI Lab")
    hits = L.check_labs([{
        "title": "Software Engineer",
        "company": "Acme",
        "description": "You will collaborate with cross-functional teams on AI Lab projects.",
    }])
    # exactly one hit (the real "AI Lab" mention), not one for "collaborate"
    assert len(hits) == 1
    assert hits[0]["matched_field"] == "description"


def test_collaborate_alone_does_not_match(data_dir):
    L = labs_mod()
    _watch(L, "Lab")
    hits = L.check_labs([{
        "title": "Analyst",
        "company": "Acme",
        "description": "Please collaborate with the team.",
    }])
    assert hits == []


def test_match_over_title_company_and_fellowship_fields(data_dir):
    L = labs_mod()
    _watch(L, "Schmidt", "DeepMind")
    jobs = [
        {"title": "Schmidt AI Fellowship", "company": "Acme", "description": ""},
        {"title": "Engineer", "company": "Google DeepMind", "description": ""},
        {"title": "Engineer", "company": "Other", "description": "",
         "fellowship_name": "Schmidt Science Fellowship"},
    ]
    hits = L.check_labs(jobs)
    assert {h["lab"] for h in hits} == {"Schmidt", "DeepMind"}
    assert {h["matched_field"] for h in hits} == {"title", "company", "fellowship_name"}


def test_empty_watchlist_never_hits(data_dir):
    L = labs_mod()
    hits = L.check_labs([{"title": "Geoffrey Hinton postdoc", "company": "x",
                          "description": "Geoffrey Hinton"}])
    assert hits == []


def test_check_labs_empty_watchlist_no_crash(data_dir):
    L = labs_mod()
    assert L.check_labs([]) == []


# ---------------------------------------------------------------------------
# curated-jobs loading, defensive
# ---------------------------------------------------------------------------

def test_load_curated_jobs_missing_file(data_dir):
    L = labs_mod()
    assert L.load_curated_jobs() == []


def test_load_curated_jobs_bad_json(data_dir):
    L = labs_mod()
    (data_dir / "jobs.json").write_text("{not json", encoding="utf-8")
    assert L.load_curated_jobs() == []


def test_load_curated_jobs_top_level_list(data_dir):
    L = labs_mod()
    jobs = [{"title": "Postdoc", "company": "MIT"}]
    (data_dir / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
    assert L.load_curated_jobs() == jobs


def test_load_curated_jobs_dict_with_key(data_dir):
    L = labs_mod()
    jobs = [{"title": "Faculty", "company": "CMU"}]
    (data_dir / "jobs.json").write_text(json.dumps({"curated": jobs, "seen": {}}),
                                         encoding="utf-8")
    assert L.load_curated_jobs() == jobs


def test_load_curated_jobs_unknown_shape_returns_empty(data_dir):
    L = labs_mod()
    (data_dir / "jobs.json").write_text(json.dumps({"last_run": "x", "seen": {}}),
                                        encoding="utf-8")
    assert L.load_curated_jobs() == []


def test_check_text_files(data_dir):
    L = labs_mod()
    _watch(L, "Mila")
    f = data_dir / "ad.txt"
    f.write_text("Postdoc opening at Mila in Montreal.", encoding="utf-8")
    hits = L.check_text_files([str(f)])
    assert len(hits) == 1
    assert hits[0]["lab"] == "Mila"
    with pytest.raises(L.LabsError):
        L.check_text_files([str(data_dir / "missing.txt")])


# ---------------------------------------------------------------------------
# CLI wiring: add_parsers attaches working subparsers
# ---------------------------------------------------------------------------

def _wired_labs_parser():
    L = labs_mod()
    parser = argparse.ArgumentParser(prog="candid")
    sub = parser.add_subparsers(dest="cmd", required=True)
    L.add_parsers(sub)
    return parser


def test_labs_cli_parses(data_dir):
    p = _wired_labs_parser()
    a = p.parse_args(["labs", "add", "Geoffrey Hinton", "--affiliation", "U Toronto"])
    assert a._labs_cmd == "add" and a.name == "Geoffrey Hinton"
    assert a.affiliation == "U Toronto"
    for argv, cmd in [(["labs", "list"], "list"),
                      (["labs", "remove", "x"], "remove"),
                      (["labs", "check"], "check")]:
        assert p.parse_args(argv)._labs_cmd == cmd
    a = p.parse_args(["labs", "check", "--text", "a.txt", "b.txt"])
    assert a.text == ["a.txt", "b.txt"]


def test_labs_cmd_dispatch(capsys, data_dir):
    L = labs_mod()
    p = _wired_labs_parser()
    L.cmd_labs(p.parse_args(["labs", "add", "Geoffrey Hinton"]))
    L.cmd_labs(p.parse_args(["labs", "list"]))
    out = capsys.readouterr().out
    assert "Geoffrey Hinton" in out
    L.cmd_labs(p.parse_args(["labs", "check"]))  # no jobs.json: no crash
    out = capsys.readouterr().out
    assert "No watchlist hits" in out


def _wired_academic_parser():
    A = cal_mod()
    parser = argparse.ArgumentParser(prog="candid")
    sub = parser.add_subparsers(dest="cmd", required=True)
    A.add_parsers(sub)
    return parser


def test_academic_cli_parses():
    p = _wired_academic_parser()
    assert p.parse_args(["academic", "calendar"])._academic_cmd == "calendar"
    a = p.parse_args(["academic", "calendar", "--month", "10"])
    assert a.month == 10
    assert p.parse_args(["academic", "season-status"])._academic_cmd == "season-status"


# ---------------------------------------------------------------------------
# academic calendar: rendering and season logic with injected dates
# ---------------------------------------------------------------------------

def test_calendar_month_rendering():
    A = cal_mod()
    text = A.render_month(10)
    assert "October" in text
    assert "TYPICAL" in text
    assert "Faculty:" in text
    for m in range(1, 13):  # every month renders without error
        assert A.render_month(m)
    with pytest.raises(ValueError):
        A.render_month(13)


def test_season_status_injected_dates():
    A = cal_mod()
    s = A.season_status(date(2026, 10, 15))
    assert any("application peak" in p for p in s["phases"])
    s = A.season_status(date(2026, 1, 15))
    assert any("interview" in p for p in s["phases"])
    s = A.season_status(date(2026, 3, 10))
    assert any("offer season" in p for p in s["phases"])
    s = A.season_status(date(2026, 6, 10))
    assert any("quiet" in p for p in s["phases"])
    assert "typical" in s["disclaimer"].lower() or "Typical" in s["disclaimer"]
    # February overlaps interview + offer: both reported, never a single date claim
    s = A.season_status(date(2026, 2, 10))
    assert len(s["phases"]) >= 2


def test_season_reminders_injected_dates():
    A = cal_mod()
    r = A.season_reminders(date(2026, 8, 20))
    assert isinstance(r, list) and r
    assert any("research" in x.lower() and "statement" in x.lower() for x in r)
    r2 = A.season_reminders(date(2026, 10, 5))
    assert any("application peak" in x.lower() for x in r2)
    # always honest about being approximate
    assert any("typical" in x.lower() for x in r)


def test_academic_cmd_dispatch(capsys):
    A = cal_mod()
    p = _wired_academic_parser()
    A.cmd_academic(p.parse_args(["academic", "calendar", "--month", "9"]))
    out = capsys.readouterr().out
    assert "September" in out and "TYPICAL" in out
    A.cmd_academic(p.parse_args(["academic", "season-status"]))
    out = capsys.readouterr().out
    assert "typically" in out.lower()

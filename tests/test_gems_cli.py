"""Tests for the hidden-gem detector CLI: `jobs gems`, `jobs why-gem`,
and `gems employers` (candid/__main__.py wiring only).

The scoring core (candid.gems) is owned by another worker, so every test
uses a fake gems module injected into sys.modules — no network, no real
gems.py needed. Curated job state is faked on disk under a temp DATA_DIR.
"""
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

APPS = [
    {"id": 1, "company": "Acme Corp", "role": "Senior ML Engineer",
     "jd_link": "https://example.com/1", "status": "saved", "notes": "",
     "date_added": "2026-09-20", "date_updated": "2026-09-20", "prep_pack": ""},
    {"id": 2, "company": "Megacorp Inc", "role": "Data Scientist",
     "jd_link": "https://example.com/2", "status": "saved", "notes": "",
     "date_added": "2026-09-20", "date_updated": "2026-09-20", "prep_pack": ""},
    {"id": 3, "company": "Beta Labs", "role": "ML Engineer (Remote)",
     "jd_link": "https://example.com/3", "status": "saved", "notes": "",
     "date_added": "2026-09-21", "date_updated": "2026-09-21", "prep_pack": ""},
]

META = {
    "1": {"source": "arbeitnow", "source_url": "https://example.com/1",
          "match_score": 78,
          "jd_text": "Senior ML Engineer at Acme Corp. Remote friendly team."},
    "2": {"source": "remoteok", "source_url": "https://example.com/2",
          "match_score": 65,
          "jd_text": "Data Scientist in New York, on-site."},
    "3": {"source": "arbeitnow", "source_url": "https://example.com/3",
          "match_score": 81,
          "jd_text": "ML Engineer remote role at Beta Labs."},
}

SEEN = {"sid-1": 1, "sid-2": 2, "sid-3": 3}


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Redirect all candid data paths into a temp dir with curated state."""
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(C, "DATA_DIR", d)
    monkeypatch.setattr(C, "TRACKER_PATH", d / "tracker.json")
    monkeypatch.setattr(C, "PROFILE_PATH", d / "profile.json")  # absent = no profile
    (d / "tracker.json").write_text(json.dumps(APPS), encoding="utf-8")
    (d / "job_meta.json").write_text(json.dumps(META), encoding="utf-8")
    (d / "jobs.json").write_text(
        json.dumps({"last_run": "2026-09-21T10:00:00", "seen": SEEN}),
        encoding="utf-8")
    return d


def make_fake_gems(record):
    """Build a fake candid.gems module honoring the agreed contract."""
    mod = types.ModuleType("candid.gems")
    mod.GEM_THRESHOLD = 60.0

    def gem_score(job, profile=None, all_jobs=None):
        record["gem_score_calls"].append(
            {"title": job.get("title"), "profile": profile, "all_jobs": all_jobs})
        megacorp = "megacorp" in (job.get("company") or "").lower()
        return {"gem_score": 87.0, "fit_score": 82.0,
                "signals": {"applicant_ratio": 0.12, "obscure_employer": 0.9},
                "reasons": ["Few applicants per opening",
                            "Under-the-radar employer"],
                "sleeper": True, "megacorp": megacorp}

    def top_gems(jobs, profile=None, limit=15, exclude_megacorps=False,
                 min_fit=0.0):
        record["top_gems_calls"].append(
            {"n_jobs": len(jobs), "limit": limit,
             "exclude_megacorps": exclude_megacorps, "min_fit": min_fit})
        ranked = []
        for j in jobs:
            g = gem_score(j, profile=profile)
            if g["fit_score"] < min_fit:
                continue
            if exclude_megacorps and g["megacorp"]:
                continue
            ranked.append({**j, "_gem": g})
        return ranked[:limit]

    def employer_ranking(jobs):
        record["employer_ranking_calls"].append(len(jobs))
        return [
            {"company": "Acme Corp", "postings": 5, "obscurity": 0.85,
             "median_salary_usd": 145000, "velocity": 3,
             "gem_employer_score": 88.0},
            {"company": "Beta Labs", "postings": 2, "obscurity": 0.62,
             "median_salary_usd": 130000, "velocity": 1,
             "gem_employer_score": 71.0},
        ]

    mod.gem_score = gem_score
    mod.top_gems = top_gems
    mod.employer_ranking = employer_ranking
    return mod


@pytest.fixture
def fake_gems(monkeypatch):
    record = {"gem_score_calls": [], "top_gems_calls": [],
              "employer_ranking_calls": []}
    monkeypatch.setitem(sys.modules, "candid.gems", make_fake_gems(record))
    return record


@pytest.fixture
def bare_dir(tmp_path, monkeypatch):
    """Temp data dir with NO curated state (empty-state tests)."""
    d = tmp_path / "empty"
    d.mkdir()
    monkeypatch.setattr(C, "DATA_DIR", d)
    monkeypatch.setattr(C, "TRACKER_PATH", d / "tracker.json")
    monkeypatch.setattr(C, "PROFILE_PATH", d / "profile.json")
    return d


# --------------------------------------------------------------------------
# jobs gems
# --------------------------------------------------------------------------

class TestJobsGems:
    def test_text_table(self, data_dir, fake_gems, capsys):
        CLI.main(["jobs", "gems"])
        out = capsys.readouterr().out
        assert "Gem" in out and "Fit" in out
        assert "Acme Corp" in out and "Senior ML Engineer" in out
        assert "87" in out and "82" in out
        assert "Few applicants per opening" in out
        assert "[sleeper]" in out

    def test_json_output(self, data_dir, fake_gems, capsys):
        CLI.main(["jobs", "gems", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list) and len(data) == 3
        first = data[0]
        assert first["gem_score"] == 87.0
        assert first["fit_score"] == 82.0
        assert first["signals"] == {"applicant_ratio": 0.12,
                                    "obscure_employer": 0.9}
        assert first["reasons"] == ["Few applicants per opening",
                                    "Under-the-radar employer"]
        assert first["sleeper"] is True
        assert first["company"] == "Acme Corp"
        assert first["source_id"] == "sid-1"
        assert first["match_score"] == 78

    def test_limit(self, data_dir, fake_gems, capsys):
        CLI.main(["jobs", "gems", "--limit", "2", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 2
        assert fake_gems["top_gems_calls"][0]["limit"] == 2

    def test_role_filter(self, data_dir, fake_gems, capsys):
        CLI.main(["jobs", "gems", "--role", "data scientist", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert [d["title"] for d in data] == ["Data Scientist"]
        assert fake_gems["top_gems_calls"][0]["n_jobs"] == 1

    def test_role_filter_no_match(self, data_dir, fake_gems, capsys):
        CLI.main(["jobs", "gems", "--role", "astronaut"])
        out = capsys.readouterr().out
        assert "No curated jobs match those filters" in out

    def test_remote_filter(self, data_dir, fake_gems, capsys):
        CLI.main(["jobs", "gems", "--remote", "--json"])
        data = json.loads(capsys.readouterr().out)
        titles = {d["title"] for d in data}
        assert titles == {"Senior ML Engineer", "ML Engineer (Remote)"}

    def test_no_megacorps_flag(self, data_dir, fake_gems, capsys):
        CLI.main(["jobs", "gems", "--no-megacorps", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert all(d["company"] != "Megacorp Inc" for d in data)
        assert fake_gems["top_gems_calls"][0]["exclude_megacorps"] is True

    def test_min_fit_flag(self, data_dir, fake_gems, capsys):
        CLI.main(["jobs", "gems", "--min-fit", "90", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert data == []  # fake fit is 82 < 90
        assert fake_gems["top_gems_calls"][0]["min_fit"] == 90.0

    def test_missing_profile_is_graceful(self, data_dir, fake_gems, capsys):
        assert not Path(data_dir / "profile.json").exists()
        CLI.main(["jobs", "gems", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 3
        assert fake_gems["top_gems_calls"][0] is not None
        # top_gems received profile=None
        # (recorded calls carry kwargs; profile key added below in with-profile test)

    def test_with_profile_passed_through(self, data_dir, fake_gems, capsys,
                                         monkeypatch):
        prof = {"name": "Alex", "skills": ["python", "ml"]}
        Path(data_dir / "profile.json").write_text(json.dumps(prof))
        CLI.main(["jobs", "gems", "--limit", "1"])
        assert fake_gems["top_gems_calls"], "top_gems should have been called"
        # gem_score got the profile object
        assert fake_gems["gem_score_calls"][0]["profile"] == prof

    def test_empty_state_hint(self, bare_dir, fake_gems, capsys):
        CLI.main(["jobs", "gems"])
        out = capsys.readouterr().out
        assert "No curated jobs yet" in out
        assert "jobs curate" in out

    def test_no_jobs_state_file(self, tmp_path, monkeypatch, fake_gems, capsys):
        d = tmp_path / "nodata"
        d.mkdir()
        monkeypatch.setattr(C, "DATA_DIR", d)
        monkeypatch.setattr(C, "TRACKER_PATH", d / "tracker.json")
        monkeypatch.setattr(C, "PROFILE_PATH", d / "profile.json")
        CLI.main(["jobs", "gems"])
        out = capsys.readouterr().out
        assert "No curated jobs yet" in out
        assert "jobs curate" in out

    def test_gems_module_missing_uses_fallback(self, data_dir, capsys,
                                               monkeypatch):
        monkeypatch.setattr(CLI, "_gems_module", lambda: None)
        CLI.main(["jobs", "gems"])  # must not crash
        out = capsys.readouterr().out
        assert "Acme Corp" in out  # fallback still renders the pool

    def test_gems_fn_missing_uses_fallback(self, data_dir, capsys, monkeypatch):
        partial = types.ModuleType("candid.gems")
        partial.GEM_THRESHOLD = 60.0  # no top_gems attribute
        monkeypatch.setitem(sys.modules, "candid.gems", partial)
        CLI.main(["jobs", "gems", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 3 and data[0]["gem_score"] == 0.0

    def test_arg_parsing(self):
        a = CLI.build_parser().parse_args(
            ["jobs", "gems", "--role", "ML", "--location", "NYC", "--remote",
             "--limit", "5", "--no-megacorps", "--min-fit", "50", "--json"])
        assert a.role == "ML" and a.location == "NYC" and a.remote is True
        assert a.limit == 5 and a.no_megacorps is True
        assert a.min_fit == 50.0 and a.json is True


# --------------------------------------------------------------------------
# jobs why-gem
# --------------------------------------------------------------------------

class TestJobsWhyGem:
    def test_text_breakdown_by_index(self, data_dir, fake_gems, capsys):
        CLI.main(["jobs", "why-gem", "1"])
        out = capsys.readouterr().out
        assert "Senior ML Engineer" in out and "Acme Corp" in out
        assert "Gem score: 87/100" in out and "Fit: 82/100" in out
        assert "applicant_ratio" in out and "0.12" in out
        assert "obscure_employer" in out and "0.9" in out
        # plain-English explanations
        assert "applicants per opening" in out
        assert "Few applicants per opening" in out
        assert "Sleeper: yes" in out

    def test_by_source_id(self, data_dir, fake_gems, capsys):
        CLI.main(["jobs", "why-gem", "sid-3"])
        out = capsys.readouterr().out
        assert "ML Engineer (Remote)" in out and "Beta Labs" in out

    def test_json_output(self, data_dir, fake_gems, capsys):
        CLI.main(["jobs", "why-gem", "2", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert data["job"]["title"] == "Data Scientist"
        assert data["job"]["company"] == "Megacorp Inc"
        assert data["job"]["source_id"] == "sid-2"
        assert data["gem"]["gem_score"] == 87.0
        assert data["gem"]["megacorp"] is True
        assert "signals" in data["gem"] and "reasons" in data["gem"]

    def test_gem_score_receives_all_jobs(self, data_dir, fake_gems, capsys):
        CLI.main(["jobs", "why-gem", "1"])
        call = fake_gems["gem_score_calls"][0]
        assert call["title"] == "Senior ML Engineer"
        assert isinstance(call["all_jobs"], list) and len(call["all_jobs"]) == 3

    def test_invalid_index_errors(self, data_dir, fake_gems, capsys):
        with pytest.raises(SystemExit) as exc:
            CLI.main(["jobs", "why-gem", "99"])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "No curated job '99'" in err

    def test_unknown_source_id_errors(self, data_dir, fake_gems, capsys):
        with pytest.raises(SystemExit) as exc:
            CLI.main(["jobs", "why-gem", "nope-123"])
        assert exc.value.code == 1
        assert "No curated job 'nope-123'" in capsys.readouterr().err

    def test_empty_state_hint(self, bare_dir, fake_gems, capsys):
        CLI.main(["jobs", "why-gem", "1"])
        out = capsys.readouterr().out
        assert "No curated jobs yet" in out
        assert "jobs curate" in out

    def test_arg_parsing(self):
        a = CLI.build_parser().parse_args(["jobs", "why-gem", "sid-1", "--json"])
        assert a.target == "sid-1" and a.json is True


# --------------------------------------------------------------------------
# gems employers
# --------------------------------------------------------------------------

class TestGemsEmployers:
    def test_text_table(self, data_dir, fake_gems, capsys):
        CLI.main(["gems", "employers"])
        out = capsys.readouterr().out
        assert "Employer" in out and "Gem score" in out
        assert "Acme Corp" in out and "Beta Labs" in out
        assert "$145,000" in out
        assert "88" in out
        assert fake_gems["employer_ranking_calls"] == [3]

    def test_json_output(self, data_dir, fake_gems, capsys):
        CLI.main(["gems", "employers", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert data[0] == {"company": "Acme Corp", "postings": 5,
                           "obscurity": 0.85, "median_salary_usd": 145000,
                           "velocity": 3, "gem_employer_score": 88.0}

    def test_limit(self, data_dir, fake_gems, capsys):
        CLI.main(["gems", "employers", "--limit", "1"])
        out = capsys.readouterr().out
        assert "Acme Corp" in out and "Beta Labs" not in out

    def test_empty_pool_hint(self, bare_dir, fake_gems, capsys):
        CLI.main(["gems", "employers"])
        out = capsys.readouterr().out
        assert "No curated jobs yet" in out
        assert "jobs curate" in out

    def test_empty_ranking_hint(self, data_dir, fake_gems, capsys,
                                monkeypatch):
        mod = types.ModuleType("candid.gems")
        mod.employer_ranking = lambda jobs: []
        monkeypatch.setitem(sys.modules, "candid.gems", mod)
        CLI.main(["gems", "employers"])
        out = capsys.readouterr().out
        assert "Not enough employer signal" in out

    def test_gems_module_missing_uses_fallback(self, data_dir, capsys,
                                               monkeypatch):
        monkeypatch.setattr(CLI, "_gems_module", lambda: None)
        CLI.main(["gems", "employers"])  # must not crash
        assert "Not enough employer signal" in capsys.readouterr().out

    def test_command_inventory(self):
        assert "gems" in CLI.COMMANDS
        assert CLI.SUBCOMMANDS["gems"] == ["employers"]
        assert "gems" in CLI.SUBCOMMANDS["jobs"]
        assert "why-gem" in CLI.SUBCOMMANDS["jobs"]

    def test_arg_parsing(self):
        a = CLI.build_parser().parse_args(
            ["gems", "employers", "--limit", "7", "--json"])
        assert a.limit == 7 and a.json is True

    def test_curate_exclude_megacorps_flag_threads_through(self, capsys, monkeypatch):
        from candid import jobs as J
        seen = {}
        def fake_curate(profile=None, **kw):
            seen.update(kw)
            return {"fetched": 0, "candidates": 0, "added": [], "errors": [], "skipped": 0}
        monkeypatch.setattr(J, "curate", fake_curate)
        monkeypatch.setattr(CLI, "_profile", lambda: {})
        CLI.main(["jobs", "curate", "--role", "ML Engineer", "--exclude-megacorps"])
        assert seen.get("exclude_megacorps") is True

    def test_curate_exclude_megacorps_defaults_false(self, capsys, monkeypatch):
        from candid import jobs as J
        seen = {}
        def fake_refresh(profile=None, **kw):
            seen.update(kw)
            return {"fetched": 0, "candidates": 0, "added": [], "errors": [], "skipped": 0}
        monkeypatch.setattr(J, "refresh", fake_refresh)
        monkeypatch.setattr(CLI, "_profile", lambda: {})
        CLI.main(["jobs", "refresh", "--role", "ML Engineer"])
        assert seen.get("exclude_megacorps") is False

"""Tests for candid.plugins — discovery isolation, hooks, env-var dirs, CLI."""

import argparse
import os
import sys
import textwrap

import pytest

from candid import plugins
from candid.plugins import (
    PluginInfo,
    discover_plugins,
    get_job_sources,
    get_scorers,
    validate_posting,
)

GOOD_PLUGIN = textwrap.dedent('''\
    def fetch_jobs(name):
        return [{
            "source": name,
            "source_id": f"{name}:1",
            "title": "Data Scientist",
            "company": "ExampleCo",
            "location": "Remote",
            "url": "https://example.com/j/1",
            "description": "Python and SQL for ML.",
            "salary_text": "$120k-$150k",
            "remote": True,
            "posted_at": "2026-09-20",
        }]

    def make_scorer(name):
        def score(profile, jd):
            skills = {s.lower() for s in profile.get("skills", [])}
            text = (jd.get("title", "") + " " + jd.get("description", "")).lower()
            return min(100.0, 50.0 + 10.0 * sum(1 for s in skills if s in text))
        return score

    CANDID_PLUGIN = {
        "name": "good_plugin",
        "version": "1.2.3",
        "hooks": {"job_source": fetch_jobs, "scorer": make_scorer},
    }
''')

BROKEN_PLUGIN = "def oops(:\n  this is not python\n"

NO_DECL_PLUGIN = textwrap.dedent('''\
    def helper():
        return 1
''')

# Wrong hook signatures: job_source needs 2 args, scorer returns a non-callable.
BADSIG_PLUGIN = textwrap.dedent('''\
    def fetch_jobs(name, extra):
        return []

    def make_scorer(name):
        return 42

    CANDID_PLUGIN = {
        "name": "badsig_plugin",
        "version": "0.0.1",
        "hooks": {"job_source": fetch_jobs, "scorer": make_scorer},
    }
''')

EXTRA_PLUGIN = textwrap.dedent('''\
    CANDID_PLUGIN = {"name": "extra_plugin", "version": "0.1.0", "hooks": {}}
''')


@pytest.fixture()
def plugdir(tmp_path, monkeypatch):
    """Isolated CONFIG_DIR/plugins with four plugin files."""
    cfg = tmp_path / "cfg"
    pdir = cfg / "plugins"
    pdir.mkdir(parents=True)
    (pdir / "good_plugin.py").write_text(GOOD_PLUGIN)
    (pdir / "broken_plugin.py").write_text(BROKEN_PLUGIN)
    (pdir / "no_decl_plugin.py").write_text(NO_DECL_PLUGIN)
    (pdir / "badsig_plugin.py").write_text(BADSIG_PLUGIN)
    monkeypatch.setenv("CANDID_CONFIG_DIR", str(cfg))
    monkeypatch.delenv("CANDID_PLUGINS", raising=False)
    return pdir


def _by_name(infos):
    return {i.name: i for i in infos}


def test_discovery_isolates_failures(plugdir):
    infos = discover_plugins()  # must not raise
    by = _by_name(infos)
    assert set(by) == {"good_plugin", "broken_plugin", "no_decl_plugin",
                       "badsig_plugin"}

    good = by["good_plugin"]
    assert good.loaded_ok and not good.errors
    assert good.version == "1.2.3"
    assert set(good.hooks) == {"job_source", "scorer"}

    broken = by["broken_plugin"]
    assert not broken.loaded_ok and broken.errors
    assert "import failed" in broken.errors[0]

    nodecl = by["no_decl_plugin"]
    assert not nodecl.loaded_ok
    assert any("CANDID_PLUGIN" in e for e in nodecl.errors)


def test_wrong_signature_plugin_loads_but_hook_fails(plugdir):
    infos = _by_name(discover_plugins())
    bad = infos["badsig_plugin"]
    # Hooks are callables, so discovery records no error ...
    assert bad.loaded_ok
    # ... but the source hook cannot be called with just the name.
    with pytest.raises(TypeError):
        get_job_sources()["badsig_plugin"]()
    # And a scorer hook returning a non-callable is skipped, not fatal.
    assert "badsig_plugin" not in get_scorers()


def test_job_source_hook_returns_valid_postings(plugdir):
    sources = get_job_sources()
    assert "good_plugin" in sources
    postings = list(sources["good_plugin"]())
    assert len(postings) == 1
    assert validate_posting(postings[0]) == []
    assert postings[0]["source"] == "good_plugin"
    assert postings[0]["remote"] is True


def test_scorer_hook_returns_0_100(plugdir):
    scorers = get_scorers()
    assert "good_plugin" in scorers
    score = scorers["good_plugin"]({"skills": ["python", "sql"]},
                                   {"title": "Data Scientist",
                                    "description": "Python and SQL for ML."})
    assert isinstance(score, (int, float)) and not isinstance(score, bool)
    assert 0 <= score <= 100


def test_validate_posting_flags_problems():
    assert validate_posting("nope") != []
    problems = validate_posting({"source": "x"})
    assert any("source_id" in p for p in problems)
    bad_remote = {"source": "x", "source_id": "x:1", "title": "t",
                  "company": "c", "location": "", "url": "",
                  "description": "", "salary_text": "", "remote": "yes",
                  "posted_at": ""}
    assert any("remote" in p for p in validate_posting(bad_remote))


def test_env_var_extra_dir(plugdir, tmp_path, monkeypatch):
    extra = tmp_path / "extra_plugins"
    extra.mkdir()
    (extra / "extra_plugin.py").write_text(EXTRA_PLUGIN)
    monkeypatch.setenv("CANDID_PLUGINS", str(extra))
    by = _by_name(discover_plugins())
    assert "extra_plugin" in by
    assert by["extra_plugin"].loaded_ok


def test_env_var_colon_separated_and_missing_dir(plugdir, tmp_path, monkeypatch):
    d1 = tmp_path / "p1"
    d1.mkdir()
    (d1 / "one.py").write_text(EXTRA_PLUGIN.replace("extra_plugin", "one"))
    monkeypatch.setenv("CANDID_PLUGINS",
                       f"{d1}{os.pathsep}/does/not/exist{os.pathsep}")
    by = _by_name(discover_plugins())
    assert "one" in by  # missing dir is skipped, not fatal


def _make_parser(monkeypatch_env=None):
    parser = argparse.ArgumentParser(prog="candid")
    sub = parser.add_subparsers(dest="cmd", required=True)
    plugins.register(sub)
    return parser


def test_register_adds_list_and_test(plugdir, capsys):
    parser = _make_parser()
    args = parser.parse_args(["plugins", "list"])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert "good_plugin" in out and "broken_plugin" in out
    assert "import failed" in out


def test_cli_test_good_plugin(plugdir, capsys):
    parser = _make_parser()
    args = parser.parse_args(["plugins", "test", "good_plugin"])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert "OK job_source" in out
    assert "OK scorer" in out


def test_cli_test_broken_plugin_reports_fail(plugdir, capsys):
    parser = _make_parser()
    args = parser.parse_args(["plugins", "test", "broken_plugin"])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert "FAIL" in out


def test_cli_test_unknown_plugin(plugdir, capsys):
    parser = _make_parser()
    args = parser.parse_args(["plugins", "test", "nope"])
    assert args.func(args) == 1
    assert "No plugin named" in capsys.readouterr().out


def test_cli_test_badsig_plugin_reports_hook_fail(plugdir, capsys):
    parser = _make_parser()
    args = parser.parse_args(["plugins", "test", "badsig_plugin"])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert "FAIL job_source" in out
    assert "FAIL scorer" in out


def test_no_plugins_found_message(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "empty_cfg"
    cfg.mkdir()
    monkeypatch.setenv("CANDID_CONFIG_DIR", str(cfg))
    monkeypatch.delenv("CANDID_PLUGINS", raising=False)
    parser = _make_parser()
    args = parser.parse_args(["plugins", "list"])
    assert args.func(args) == 0
    assert "No plugins found" in capsys.readouterr().out


def test_underscore_files_skipped(plugdir):
    (plugdir / "_private.py").write_text(GOOD_PLUGIN)
    (plugdir / "__init__.py").write_text("")
    by = _by_name(discover_plugins())
    assert "_private" not in by and "__init__" not in by

"""Tests for `candid update ...` CLI wiring. No real network access.

The update_check functions are monkeypatched; the data dir is redirected
into a temp dir via CANDID_DATA_DIR (resolved lazily by update_check).
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout

import pytest

from candid import __main__ as CLI
from candid import __version__ as CANDID_VERSION
from candid import dashboard as D
from candid import update_check as UC


@pytest.fixture(autouse=True)
def _no_startup_nudge(monkeypatch):
    """maybe_startup_nudge can hit the network in the real module; keep
    CLI tests offline. The nudge path has its own dedicated test below."""
    monkeypatch.setattr(UC, "maybe_startup_nudge", lambda: None)


@pytest.fixture
def datadir(tmp_path, monkeypatch):
    """Isolated DATA_DIR for settings/cache tests (paths resolve lazily)."""
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    return tmp_path


def run_cli(argv, stdin=""):
    """Run the CLI in-process; returns (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old_stdin = sys.stdin
    if stdin:
        sys.stdin = io.StringIO(stdin)
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                CLI.main(argv)
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
            else:
                code = 0
    finally:
        sys.stdin = old_stdin
    return code, out.getvalue(), err.getvalue()


def _info(**kw):
    base = dict(
        current_version=CANDID_VERSION,
        latest_version="9.9.9",
        update_available=True,
        security=False,
        release_url="https://github.com/K7S3/candid/releases/tag/v9.9.9",
        notes="some notes",
        checked_at="2026-09-22T00:00:00+00:00",
        error=None,
    )
    base.update(kw)
    return UC.UpdateInfo(**base)


def _seed_cache(datadir, **kw):
    UC.save_cache(_info(**kw))


# --- argparse wiring --------------------------------------------------------

class TestParse:
    def test_command_registered(self):
        assert "update" in CLI.COMMANDS
        assert CLI.SUBCOMMANDS["update"] == ["check", "notes", "on", "off", "version"]

    @pytest.mark.parametrize("sub", ["check", "notes", "on", "off", "version"])
    def test_subcommand_parses(self, sub):
        args = CLI.build_parser().parse_args(["update", sub])
        assert args.what == sub
        assert args.func is CLI.cmd_update

    def test_bare_update_parses(self):
        args = CLI.build_parser().parse_args(["update"])
        assert args.what is None
        assert args.apply is False
        assert args.yes is False

    def test_flags_parse(self):
        args = CLI.build_parser().parse_args(["update", "check", "--json"])
        assert args.json is True
        args = CLI.build_parser().parse_args(["update", "--apply", "--yes"])
        assert args.what is None and args.apply and args.yes

    def test_expected_error_registered(self):
        assert "UpdateCheckError" in CLI._EXPECTED_ERRORS
        assert CLI._NEXT_COMMAND["UpdateCheckError"] == "python -m candid update check"


# --- update check ------------------------------------------------------------

class TestCheck:
    def test_check_human_update_available(self, monkeypatch, datadir):
        monkeypatch.setattr(UC, "check_now",
                            lambda timeout=8.0: _info())
        code, out, _ = run_cli(["update", "check"])
        assert code == 0
        assert CANDID_VERSION in out
        assert "9.9.9" in out
        assert "Update available" in out

    def test_check_human_security_flag(self, monkeypatch, datadir):
        monkeypatch.setattr(UC, "check_now",
                            lambda timeout=8.0: _info(security=True))
        _, out, _ = run_cli(["update", "check"])
        assert "security" in out.lower()

    def test_check_human_up_to_date(self, monkeypatch, datadir):
        monkeypatch.setattr(UC, "check_now",
                            lambda timeout=8.0: _info(update_available=False,
                                                     latest_version=CANDID_VERSION))
        code, out, _ = run_cli(["update", "check"])
        assert code == 0
        assert "Up to date" in out

    def test_check_human_unknown(self, monkeypatch, datadir):
        monkeypatch.setattr(UC, "check_now",
                            lambda timeout=8.0: _info(update_available=None,
                                                     latest_version=None,
                                                     error="no network"))
        code, out, _ = run_cli(["update", "check"])
        assert code == 0
        assert "Could not check" in out

    def test_check_json_valid(self, monkeypatch, datadir):
        monkeypatch.setattr(UC, "check_now",
                            lambda timeout=8.0: _info())
        code, out, _ = run_cli(["update", "check", "--json"])
        assert code == 0
        payload = json.loads(out)
        assert payload["update_available"] is True
        assert payload["latest_version"] == "9.9.9"
        assert payload["current_version"] == CANDID_VERSION
        assert payload["security"] is False

    def test_check_saves_cache(self, monkeypatch, datadir):
        monkeypatch.setattr(UC, "check_now",
                            lambda timeout=8.0: _info())
        run_cli(["update", "check"])
        cached = json.loads((datadir / "update_check.json").read_text())
        assert cached["latest_version"] == "9.9.9"
        assert cached["update_available"] is True


# --- update notes ------------------------------------------------------------

FAKE_RELEASES = [
    {"tag_name": "v9.9.9", "name": "Big release", "draft": False,
     "html_url": "https://example.com/r999",
     "body": "Highlights of the big release."},
    {"tag_name": "v" + CANDID_VERSION, "name": "current", "draft": False,
     "html_url": "https://example.com/rcur", "body": "Current release notes."},
    {"tag_name": "v0.1.0", "name": "old", "draft": False,
     "html_url": "https://example.com/r010", "body": "Ancient history."},
    {"tag_name": "v10.0.0", "name": "drafty", "draft": True,
     "html_url": "https://example.com/rdraft", "body": "Not published yet."},
]


class TestNotes:
    def test_notes_human(self, monkeypatch):
        monkeypatch.setattr(CLI, "_update_fetch_releases",
                            lambda timeout=8.0: FAKE_RELEASES)
        code, out, _ = run_cli(["update", "notes"])
        assert code == 0
        assert "GitHub" in out
        assert "v9.9.9" in out
        assert "Highlights of the big release." in out
        assert "Ancient history." not in out
        assert "Not published yet." not in out

    def test_notes_json_valid(self, monkeypatch):
        monkeypatch.setattr(CLI, "_update_fetch_releases",
                            lambda timeout=8.0: FAKE_RELEASES)
        code, out, _ = run_cli(["update", "notes", "--json"])
        assert code == 0
        payload = json.loads(out)
        assert [r["tag"] for r in payload] == ["v9.9.9"]
        assert payload[0]["body"] == "Highlights of the big release."
        assert payload[0]["url"] == "https://example.com/r999"

    def test_notes_fetch_failure_reports_cleanly(self, monkeypatch):
        def boom(timeout=8.0):
            raise OSError("offline")
        monkeypatch.setattr(CLI, "_update_fetch_releases", boom)
        code, out, err = run_cli(["update", "notes"])
        assert code == 1
        assert "Error" in err
        assert "Traceback" not in err


# --- update on/off -----------------------------------------------------------

class TestOnOff:
    def test_off_then_on_roundtrip(self, datadir):
        code, out, _ = run_cli(["update", "off"])
        assert code == 0
        assert UC.get_settings()["check_enabled"] is False
        assert "disabled" in out
        code, out, _ = run_cli(["update", "on"])
        assert code == 0
        assert UC.get_settings()["check_enabled"] is True
        assert "enabled" in out


# --- update version ----------------------------------------------------------

class TestVersion:
    def test_version_with_cache(self, datadir):
        _seed_cache(datadir)
        code, out, _ = run_cli(["update", "version"])
        assert code == 0
        assert CANDID_VERSION in out
        assert "9.9.9" in out
        assert "install mode" in out
        assert str(datadir) in out

    def test_version_unknown_cache(self, datadir):
        code, out, _ = run_cli(["update", "version"])
        assert code == 0
        assert CANDID_VERSION in out
        assert "unknown" in out
        assert "candid update check" in out


# --- bare update (upgrade guidance) ------------------------------------------

class TestBareUpdate:
    def test_prints_steps_and_does_not_execute(self, monkeypatch, datadir):
        monkeypatch.setattr(UC, "upgrade_steps",
                            lambda: ["echo step-one", "echo step-two"])
        calls = []

        def fake_run(*a, **k):
            calls.append(a)
            raise AssertionError("must not execute without --apply")

        monkeypatch.setattr(CLI.subprocess, "run", fake_run)
        code, out, _ = run_cli(["update"])
        assert code == 0
        assert "1. echo step-one" in out
        assert "2. echo step-two" in out
        assert "back up candid_data" in out
        assert calls == []

    def test_apply_yes_executes(self, monkeypatch, datadir):
        monkeypatch.setattr(UC, "upgrade_steps", lambda: ["do the thing"])
        monkeypatch.setattr(UC, "detect_install_mode", lambda: "git")
        calls = []

        def fake_run(cmd, **k):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="pulled", stderr="")

        monkeypatch.setattr(CLI.subprocess, "run", fake_run)
        code, out, _ = run_cli(["update", "--apply", "--yes"])
        assert code == 0
        assert len(calls) == 1
        assert calls[0][0] == "git"
        assert "pull" in calls[0] and "--ff-only" in calls[0]
        assert "Upgrade succeeded" in out

    def test_apply_confirmed_via_prompt(self, monkeypatch, datadir):
        monkeypatch.setattr(UC, "upgrade_steps", lambda: ["do the thing"])
        monkeypatch.setattr(UC, "detect_install_mode", lambda: "pip")
        calls = []

        def fake_run(cmd, **k):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="done", stderr="")

        monkeypatch.setattr(CLI.subprocess, "run", fake_run)
        code, out, _ = run_cli(["update", "--apply"], stdin="y\n")
        assert code == 0
        assert len(calls) == 1
        assert calls[0][0] == "pip"
        assert "Proceed?" in out
        assert "Upgrade succeeded" in out

    def test_apply_declined_aborts_without_executing(self, monkeypatch, datadir):
        monkeypatch.setattr(UC, "upgrade_steps", lambda: ["do the thing"])
        monkeypatch.setattr(UC, "detect_install_mode", lambda: "pip")
        calls = []
        monkeypatch.setattr(
            CLI.subprocess, "run",
            lambda *a, **k: calls.append(a) or
            subprocess.CompletedProcess(a[0], 0, "", ""))
        code, out, _ = run_cli(["update", "--apply"], stdin="n\n")
        assert code == 0
        assert calls == []
        assert "Aborted" in out

    def test_apply_failure_reported_cleanly(self, monkeypatch, datadir):
        monkeypatch.setattr(UC, "upgrade_steps", lambda: ["do the thing"])
        monkeypatch.setattr(UC, "detect_install_mode", lambda: "pip")

        def fake_run(*a, **k):
            return subprocess.CompletedProcess(a[0], 1, "", "boom")

        monkeypatch.setattr(CLI.subprocess, "run", fake_run)
        code, out, err = run_cli(["update", "--apply", "--yes"])
        assert code == 1
        assert "Upgrade failed" in err
        assert "Traceback" not in err

    def test_apply_unknown_mode_exits_cleanly(self, monkeypatch, datadir):
        monkeypatch.setattr(UC, "upgrade_steps", lambda: ["do the thing"])
        monkeypatch.setattr(UC, "detect_install_mode", lambda: "unknown")
        code, out, err = run_cli(["update", "--apply", "--yes"])
        assert code == 1
        assert "not available" in err


# --- startup nudge -----------------------------------------------------------

class TestStartupNudge:
    def test_nudge_printed_to_stderr_for_other_commands(self, monkeypatch):
        monkeypatch.setattr(UC, "maybe_startup_nudge",
                            lambda: "Update available: candid 9.9.9 (you have 0.1.0)")
        code, out, err = run_cli(["gmail", "guide"])
        assert code == 0
        assert "Update available" in err
        assert "Update available" not in out

    def test_no_nudge_for_update_command(self, monkeypatch, datadir):
        def boom():
            raise AssertionError("must not check for updates on `candid update`")

        monkeypatch.setattr(UC, "maybe_startup_nudge", boom)
        monkeypatch.setattr(UC, "detect_install_mode", lambda: "unknown")
        code, out, err = run_cli(["update", "version"])
        assert code == 0
        assert "Update available" not in err

    def test_nudge_never_breaks_cli(self, monkeypatch, datadir):
        def boom():
            raise RuntimeError("nudge exploded")

        monkeypatch.setattr(UC, "maybe_startup_nudge", boom)
        code, out, err = run_cli(["update", "version"])
        assert code == 0
        assert CANDID_VERSION in out


# --- dashboard banner --------------------------------------------------------

class TestDashboardBanner:
    def test_banner_dict(self, datadir):
        _seed_cache(datadir)
        banner = D.update_banner()
        assert banner is not None
        assert banner["version"] == "9.9.9"
        assert banner["url"].endswith("/v9.9.9")
        assert banner["security"] is False

    def test_banner_present_when_update_available(self, datadir):
        _seed_cache(datadir, security=True,
                    release_url="https://example.com/r999")
        html = D.render_dashboard_html().decode("utf-8")
        assert "Update available: v9.9.9" in html
        assert "(security release)" in html
        assert "https://example.com/r999" in html
        assert 'id="updateBanner"' in html
        assert "dismiss" in html

    def test_banner_absent_when_up_to_date(self, datadir):
        _seed_cache(datadir, update_available=False,
                    latest_version=CANDID_VERSION)
        html = D.render_dashboard_html().decode("utf-8")
        assert "updateBanner" not in html
        assert "Update available" not in html

    def test_banner_absent_without_cache(self, datadir):
        html = D.render_dashboard_html().decode("utf-8")
        assert "updateBanner" not in html
        assert "Update available" not in html

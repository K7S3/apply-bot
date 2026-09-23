"""Integration tests for batch-107 CLI wiring in candid.__main__.

Covers: new commands registered, -i/--interactive missing-arg prompting,
wizard -> argv dispatch, track remove confirmation, menu/triage/shell wiring.
"""
import io
import json
import os
from pathlib import Path

import pytest

import candid.__main__ as CM


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    # config paths are bound at import time, so patch both the env vars
    # (honored at call time by prefill/sessions) and the module attributes.
    import candid.config as C
    data = tmp_path / "data"
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("CANDID_DATA_DIR", str(data))
    monkeypatch.setenv("CANDID_CONFIG_DIR", str(cfg))
    monkeypatch.setattr(C, "DATA_DIR", data)
    monkeypatch.setattr(C, "CONFIG_DIR", cfg)
    monkeypatch.setattr(C, "PROFILE_PATH", data / "profile.json")
    monkeypatch.setattr(C, "TRACKER_PATH", data / "tracker.json")
    monkeypatch.setattr(C, "OFFERS_PATH", data / "offers.json")
    monkeypatch.setattr(C, "SALARY_DB", data / "salary.db")
    monkeypatch.setattr(C, "PREP_PACKS_DIR", data / "prep_packs")
    monkeypatch.setattr(C, "TAILOR_DIR", data / "tailored")
    monkeypatch.setattr(C, "GMAIL_PROPOSALS_PATH", data / "gmail_proposals.json")
    # never a real TTY in tests unless a test opts in
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    yield tmp_path


def test_new_commands_registered():
    for cmd in ("shell", "menu", "triage", "wizard"):
        assert cmd in CM.COMMANDS
    assert CM.SUBCOMMANDS["wizard"] == ["onboard", "tailor", "track-add",
                                       "offer-add", "prep"]


def test_interactive_flag_documented():
    parser = CM.build_parser()
    assert parser.parse_args(["-i", "track", "list"]).interactive is True
    assert parser.parse_args(["track", "list"]).interactive is False


def test_strip_interactive():
    assert CM._strip_interactive(["track", "add", "-i"]) == ["track", "add"]
    assert CM._strip_interactive(["--interactive", "menu"]) == ["menu"]
    assert CM._strip_interactive(["match", "--jd", "-"]) == ["match", "--jd", "-"]


def test_maybe_prompt_missing_no_flag_unchanged():
    argv = ["track", "add"]
    assert CM._maybe_prompt_missing(argv) == argv


def test_maybe_prompt_missing_help_passthrough():
    argv = ["track", "add", "--help"]
    assert CM._maybe_prompt_missing(argv) == argv


def test_maybe_prompt_missing_unknown_command():
    assert CM._maybe_prompt_missing(["frobnicate"]) == ["frobnicate"]


def test_maybe_prompt_missing_non_tty_raises():
    from candid import interactive as I
    with pytest.raises(I.InteractiveError):
        CM._maybe_prompt_missing(["track", "add", "-i"])


def _tty(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)


def test_maybe_prompt_missing_track_add(monkeypatch):
    _tty(monkeypatch)
    answers = iter(["Acme", "Data Scientist"])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))
    out = CM._maybe_prompt_missing(["track", "add", "-i"])
    assert out == ["track", "add", "--company", "Acme", "--role", "Data Scientist"]


def test_maybe_prompt_missing_skips_present_flags(monkeypatch):
    _tty(monkeypatch)
    answers = iter(["Data Scientist"])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))
    out = CM._maybe_prompt_missing(["track", "add", "--company", "Acme", "-i"])
    assert out == ["track", "add", "--company", "Acme", "--role", "Data Scientist"]


def test_maybe_prompt_missing_positional_id(monkeypatch):
    _tty(monkeypatch)
    answers = iter(["42"])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))
    out = CM._maybe_prompt_missing(["track", "remove", "-i"])
    assert out == ["track", "remove", "42"]


def test_maybe_prompt_missing_subcommand_choice(monkeypatch):
    _tty(monkeypatch)
    # "1" picks track->add, then company/role are still prompted
    seq = iter(["1", "Acme", "Engineer"])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(seq))
    out = CM._maybe_prompt_missing(["track", "-i"])
    assert out[0:2] == ["track", "add"]
    assert "--company" in out and "--role" in out


def test_maybe_prompt_missing_tailor_what(monkeypatch):
    _tty(monkeypatch)
    seq = iter(["1", "/tmp/jd.txt"])  # resume, then jd path
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(seq))
    out = CM._maybe_prompt_missing(["tailor", "-i"])
    assert out[0:2] == ["tailor", "resume"]
    assert "--jd" in out


def test_wizard_argv_mappings():
    assert CM._wizard_argv("onboard", {"resume": "r.pdf", "linkedin": ""}) == \
        ["onboard", "--resume", "r.pdf"]
    assert CM._wizard_argv("tailor", {"jd": "j.txt", "company": "Acme",
                                     "role": "DS", "tone": "warm",
                                     "length": "one-page"}) == \
        ["tailor", "resume", "--jd", "j.txt", "--company", "Acme",
         "--role", "DS", "--tone", "warm", "--length", "one-page"]
    assert CM._wizard_argv("track-add", {"company": "Acme", "role": "DS",
                                        "source": "Referral",
                                        "status": "applied"}) == \
        ["track", "add", "--company", "Acme", "--role", "DS",
         "--status", "applied", "--notes", "source: Referral"]
    assert CM._wizard_argv("offer-add", {"company": "Acme", "role": "DS",
                                        "base": "180000", "bonus": "0",
                                        "sign_on": "", "equity": "50000",
                                        "notes": ""}) == \
        ["offer", "add", "--company", "Acme", "--role", "DS",
         "--base", "180000", "--equity", "50000"]
    assert CM._wizard_argv("prep", {"company": "Acme", "role": "DS",
                                   "jd": ""}) == \
        ["prep", "--company", "Acme", "--role", "DS"]
    with pytest.raises(ValueError):
        CM._wizard_argv("nope", {})


def test_cmd_wizard_unknown_name(capsys):
    with pytest.raises(SystemExit):
        CM.main(["wizard", "nope"])
    assert "Unknown wizard" in capsys.readouterr().err


def test_cmd_wizard_track_add_end_to_end(monkeypatch, capsys):
    _tty(monkeypatch)
    # company, role, source (default), status (default), review confirm
    seq = iter(["Acme", "Engineer", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(seq))
    CM.main(["wizard", "track-add"])
    out = capsys.readouterr().out
    assert "Added application #1" in out
    from candid import tracker as T
    apps = T.list_apps()
    assert len(apps) == 1 and apps[0]["company"] == "Acme"
    assert "source: LinkedIn" in apps[0]["notes"]


def test_cmd_wizard_abort_saves_partial(monkeypatch, capsys):
    _tty(monkeypatch)
    seq = iter(["Acme", "quit"])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(seq))
    CM.main(["wizard", "track-add"])
    out = capsys.readouterr().out
    assert "track-add-partial" in out
    from candid import sessions as SE
    saved = SE.load_session("track-add-partial")
    assert saved and saved.get("company") == "Acme"


def test_cmd_wizard_resume_from(monkeypatch, capsys):
    _tty(monkeypatch)
    from candid import sessions as SE
    SE.save_session("acme", {"company": "Acme", "role": "Engineer"})
    # role pre-seeded -> skipped; answer source, status, review
    seq = iter(["", "", ""])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(seq))
    CM.main(["wizard", "track-add", "--resume-from", "acme"])
    out = capsys.readouterr().out
    assert "Resumed session 'acme'" in out
    assert "Added application #1" in out


def test_track_remove_no_prompt_off_tty(monkeypatch, capsys):
    from candid import tracker as T
    T.add("Acme", "Engineer")
    CM.main(["track", "remove", "1"])  # no --yes, but no TTY -> proceeds
    assert capsys.readouterr().out.strip() == "Removed application #1."
    assert T.list_apps() == []


def test_track_remove_yes_flag(monkeypatch, capsys):
    _tty(monkeypatch)
    from candid import tracker as T
    T.add("Acme", "Engineer")
    CM.main(["track", "remove", "1", "--yes"])
    assert "Removed application #1." in capsys.readouterr().out


def test_track_remove_cancel_on_tty(monkeypatch, capsys):
    _tty(monkeypatch)
    from candid import tracker as T
    T.add("Acme", "Engineer")
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")
    CM.main(["track", "remove", "1"])
    assert "Cancelled." in capsys.readouterr().out
    assert len(T.list_apps()) == 1  # still there


def test_cmd_menu_dispatch(monkeypatch, capsys):
    from candid import menu as M
    monkeypatch.setattr(M, "show_menu", lambda: "See my applications")
    CM.main(["menu"])
    out = capsys.readouterr().out
    assert "Running: python -m candid track list" in out
    assert "application(s) tracked" in out


def test_cmd_menu_cancel(monkeypatch, capsys):
    from candid import menu as M
    monkeypatch.setattr(M, "show_menu", lambda: None)
    CM.main(["menu"])
    assert "Cancelled" in capsys.readouterr().out


def test_cmd_triage_empty(monkeypatch, capsys):
    _tty(monkeypatch)
    CM.main(["triage"])
    out = capsys.readouterr().out
    assert "No applications to review." in out
    assert "Triaged 0 application(s)" in out


def test_cmd_shell_lines(monkeypatch, capsys):
    from candid import shell as S
    # feed via run_shell lines directly (unit level)
    code = S.run_shell(lines=["track list", "quit"])
    assert code == 0
    assert "application(s) tracked" in capsys.readouterr().out


def test_bare_main_off_tty_errors():
    with pytest.raises(SystemExit) as e:
        CM.main([])
    assert e.value.code == 2


def test_jsonable_answers_path():
    out = CM._jsonable_answers({"resume": Path("/tmp/r.pdf"), "n": 3})
    assert out == {"resume": "/tmp/r.pdf", "n": 3}
    json.dumps(out)  # must be JSON-serializable

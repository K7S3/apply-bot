"""Tests for candid.wizards: framework + 5 concrete wizards.

Input is scripted by patching builtins.input (the wizards read via input()).
Each scripted list is consumed in order: step prompts first, then the final
review-screen prompt.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402
from candid.wizards import (  # noqa: E402
    WIZARDS,
    Wizard,
    WizardAborted,
    onboard_wizard,
    offer_add_wizard,
    prep_wizard,
    run_wizard,
    tailor_wizard,
    track_add_wizard,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def script(monkeypatch, answers):
    """Feed scripted answers to input(); fail loudly if input runs dry.

    Also pretends stdin is a TTY: candid.interactive.ask refuses to call
    input() on a non-TTY (it takes the default / raises InteractiveError),
    so scripted tests must look interactive.
    """
    it = iter(answers)

    def _fake(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise AssertionError(f"input() called with no scripted answer left (prompt={prompt!r})")

    monkeypatch.setattr("builtins.input", _fake)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)


@pytest.fixture()
def resume(tmp_path):
    p = tmp_path / "resume.pdf"
    p.write_text("fake resume")
    return str(p)


@pytest.fixture()
def jd(tmp_path):
    p = tmp_path / "jd.txt"
    p.write_text("fake jd")
    return str(p)


@pytest.fixture()
def linkedin_zip(tmp_path):
    p = tmp_path / "linkedin.zip"
    p.write_bytes(b"PK fake zip")
    return str(p)


# ---------------------------------------------------------------------------
# happy paths
# ---------------------------------------------------------------------------


def test_onboard_happy_path(monkeypatch, resume, linkedin_zip):
    script(monkeypatch, [resume, linkedin_zip, ""])  # linkedin, then confirm
    out = run_wizard("onboard")
    assert out == {"resume": resume, "linkedin": linkedin_zip}


def test_onboard_linkedin_optional_skip(monkeypatch, resume):
    script(monkeypatch, [resume, "", ""])
    out = run_wizard("onboard")
    assert out == {"resume": resume, "linkedin": ""}


def test_tailor_happy_path(monkeypatch, jd):
    script(monkeypatch, [jd, "Acme", "Data Scientist", "2", "1", ""])
    out = run_wizard("tailor")
    assert out == {"jd": jd, "company": "Acme", "role": "Data Scientist",
                   "tone": "warm", "length": "one-page"}


def test_track_add_happy_path(monkeypatch):
    script(monkeypatch, ["Acme", "Data Scientist", "4", "2", ""])
    out = run_wizard("track-add")
    assert out == {"company": "Acme", "role": "Data Scientist",
                   "source": "Referral", "status": "applied"}


def test_offer_add_happy_path(monkeypatch):
    script(monkeypatch, ["Acme", "DS", "180000", "20000", "15000", "200000",
                         "4yr vest", ""])
    out = run_wizard("offer-add")
    assert out == {"company": "Acme", "role": "DS", "base": 180000,
                   "bonus": 20000, "sign_on": 15000, "equity": 200000,
                   "notes": "4yr vest"}


def test_prep_happy_path(monkeypatch, jd):
    script(monkeypatch, ["Acme", "DS", jd, ""])
    out = run_wizard("prep")
    assert out == {"company": "Acme", "role": "DS", "jd": jd}


# ---------------------------------------------------------------------------
# navigation: back / quit / exit
# ---------------------------------------------------------------------------


def test_back_navigation_returns_to_previous_step(monkeypatch, jd):
    # answer company, then type 'back' at the role prompt -> re-answer company
    script(monkeypatch, [jd, "Acme", "back", "Initech", "Engineer",
                         "1", "1", ""])
    out = run_wizard("tailor")
    assert out["company"] == "Initech"
    assert out["role"] == "Engineer"
    assert out["tone"] == "confident"


def test_back_at_first_step_stays_put(monkeypatch, jd):
    script(monkeypatch, ["back", jd, "Acme", "Eng", "1", "1", ""])
    out = run_wizard("tailor")
    assert out["jd"] == jd
    assert out["company"] == "Acme"


def test_quit_aborts(monkeypatch, jd):
    script(monkeypatch, [jd, "quit"])
    with pytest.raises(WizardAborted):
        run_wizard("tailor")


def test_exit_also_aborts(monkeypatch):
    script(monkeypatch, ["exit"])
    with pytest.raises(WizardAborted):
        run_wizard("onboard")


def test_quit_at_review_aborts(monkeypatch, resume):
    script(monkeypatch, [resume, "", "quit"])
    with pytest.raises(WizardAborted):
        run_wizard("onboard")


def test_review_back_redoes_last_step(monkeypatch):
    script(monkeypatch, ["Acme", "DS", "1", "2", "back", "", ""])
    out = run_wizard("track-add")
    assert out["status"] == "applied"  # kept default via Enter


# ---------------------------------------------------------------------------
# validation re-prompts
# ---------------------------------------------------------------------------


def test_path_must_exist_reprompts(monkeypatch, resume):
    script(monkeypatch, ["/no/such/file.pdf", resume, "", ""])
    out = run_wizard("onboard")
    assert out["resume"] == resume


def test_required_text_reprompts(monkeypatch):
    script(monkeypatch, ["", "Acme", "DS", "1", "1", ""])
    out = run_wizard("track-add")
    assert out["company"] == "Acme"


def test_int_validation_reprompts(monkeypatch):
    # base: 'abc' invalid -> 180000; bonus: blank -> 0;
    # sign_on: -5 invalid -> 10000; equity/notes blank
    script(monkeypatch, ["Acme", "DS", "abc", "180000", "",
                         "-5", "10000", "", "", ""])
    out = run_wizard("offer-add")
    assert out["base"] == 180000
    assert out["bonus"] == 0
    assert out["sign_on"] == 10000
    assert out["equity"] == 0


def test_offer_money_fields_default_to_zero(monkeypatch):
    script(monkeypatch, ["Acme", "DS", "", "", "", "", "", ""])
    out = run_wizard("offer-add")
    assert out["base"] == 0 and out["bonus"] == 0
    assert out["sign_on"] == 0 and out["equity"] == 0


# ---------------------------------------------------------------------------
# review screen edit + pre-seeded resume
# ---------------------------------------------------------------------------


def test_review_screen_edit_step_number(monkeypatch):
    # type '1' at review -> re-answer company, keep the rest via Enter
    script(monkeypatch, ["Acme", "DS", "1", "2", "1", "Initech",
                         "", "", "", ""])
    out = run_wizard("track-add")
    assert out["company"] == "Initech"
    assert out["role"] == "DS"
    assert out["source"] == "LinkedIn"
    assert out["status"] == "applied"


def test_preseeded_answers_are_skipped_but_reviewed(monkeypatch, resume):
    # resume pre-seeded: only linkedin + review prompts are consumed
    script(monkeypatch, ["", ""])
    out = run_wizard("onboard", {"resume": resume})
    assert out == {"resume": resume, "linkedin": ""}


def test_fully_preseeded_still_shows_review(monkeypatch, jd):
    seed = {"jd": jd, "company": "Acme", "role": "DS",
            "tone": "bold-nope", "length": "one-page"}
    script(monkeypatch, [""])  # review confirm only
    out = run_wizard("tailor", seed)
    assert out == seed


# ---------------------------------------------------------------------------
# choice incl. custom text + confirm-kind framework coverage
# ---------------------------------------------------------------------------


def test_source_custom_text(monkeypatch):
    # 7th option is "Other (type your own)" -> free text
    script(monkeypatch, ["Acme", "DS", "7", "Hacker News", "1", ""])
    out = run_wizard("track-add")
    assert out["source"] == "Hacker News"
    assert out["status"] == "saved"


def test_confirm_kind(monkeypatch):
    w = Wizard("demo", [{"key": "ok", "prompt": "Proceed?",
                         "kind": "confirm"}])
    script(monkeypatch, ["y", ""])
    assert w.run() == {"ok": True}
    script(monkeypatch, ["n", ""])
    assert w.run() == {"ok": False}


def test_choice_accepts_name_or_number(monkeypatch, jd):
    script(monkeypatch, [jd, "Acme", "Eng", "warm", "detailed", ""])
    out = run_wizard("tailor")
    assert out["tone"] == "warm"
    assert out["length"] == "detailed"


# ---------------------------------------------------------------------------
# answer keys match the real CLI flags
# ---------------------------------------------------------------------------


def _parse(argv):
    return CLI.build_parser().parse_args(argv)


def test_onboard_keys_match_cli_flags(monkeypatch, resume, linkedin_zip):
    script(monkeypatch, [resume, linkedin_zip, ""])
    out = run_wizard("onboard")
    ns = _parse(["onboard", "--resume", out["resume"],
                 "--linkedin", out["linkedin"]])
    assert set(out) <= set(vars(ns))


def test_tailor_keys_match_cli_flags(monkeypatch, jd):
    script(monkeypatch, [jd, "Acme", "DS", "1", "2", ""])
    out = run_wizard("tailor")
    ns = _parse(["tailor", "resume", "--jd", out["jd"],
                 "--company", out["company"], "--role", out["role"],
                 "--tone", out["tone"], "--length", out["length"]])
    assert set(out) <= set(vars(ns))  # argparse validates tone/length choices


def test_track_add_keys_match_cli_flags(monkeypatch):
    script(monkeypatch, ["Acme", "DS", "1", "2", ""])
    out = run_wizard("track-add")
    assert out["status"] in C.STATUSES
    ns = _parse(["track", "add", "--company", out["company"],
                 "--role", out["role"], "--status", out["status"]])
    # 'source' has no --source flag on track add (fold into --notes by caller)
    assert set(out) - {"source"} <= set(vars(ns))


def test_offer_add_keys_match_cli_flags(monkeypatch):
    script(monkeypatch, ["Acme", "DS", "180000", "20000", "15000",
                         "200000", "", ""])
    out = run_wizard("offer-add")
    ns = _parse(["offer", "add", "--company", out["company"],
                 "--role", out["role"], "--base", str(out["base"]),
                 "--bonus-first", str(out["bonus"]),
                 "--sign-on", str(out["sign_on"]),
                 "--equity", str(out["equity"])])
    parsed = vars(ns)
    assert parsed["base"] == out["base"]
    assert parsed["bonus_first_year_guaranteed"] == out["bonus"]
    assert parsed["sign_on"] == out["sign_on"]
    assert parsed["equity_total"] == out["equity"]


def test_prep_keys_match_cli_flags(monkeypatch, jd):
    script(monkeypatch, ["Acme", "DS", jd, ""])
    out = run_wizard("prep")
    ns = _parse(["prep", "--company", out["company"],
                 "--role", out["role"], "--jd", out["jd"]])
    assert set(out) <= set(vars(ns))


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


def test_wizards_registry_complete():
    assert set(WIZARDS) == {"onboard", "tailor", "track-add",
                            "offer-add", "prep"}
    for name, factory in WIZARDS.items():
        w = factory()
        assert isinstance(w, Wizard)
        assert w.steps, name


def test_run_wizard_unknown_name():
    with pytest.raises(ValueError, match="Unknown wizard"):
        run_wizard("nope")


def test_factories_do_not_share_step_state():
    a, b = tailor_wizard(), tailor_wizard()
    assert a is not b and a.steps is not b.steps

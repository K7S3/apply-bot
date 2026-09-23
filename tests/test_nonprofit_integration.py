"""Integration tests for batch 18 (nonprofit / mission-driven jobs).

Covers the coordinator's wiring, not the per-module units (those live in
test_nonprofit_*.py / test_mission_*.py):
- jobs.ADAPTERS includes the nonprofit feeds
- `match` output carries mission_fit (JSON key + conditional text block)
- prep packs for nonprofit-looking orgs include mission-alignment questions
- the `nonprofit` CLI group dispatches every subcommand
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_tmp = tempfile.mkdtemp(prefix="candid-test-npo-int-")
os.environ["CANDID_DATA_DIR"] = _tmp

import candid.config as _C  # noqa: E402
# Re-point every data path at our temp dir. Other test modules may have
# imported candid.config first with their own CANDID_DATA_DIR, so the env
# var alone is not enough when the whole suite runs together.
_C.DATA_DIR = Path(_tmp)
_C.PROFILE_PATH = _C.DATA_DIR / "profile.json"
_C.TRACKER_PATH = _C.DATA_DIR / "tracker.json"
_C.OFFERS_PATH = _C.DATA_DIR / "offers.json"
_C.PREP_PACKS_DIR = _C.DATA_DIR / "prep_packs"
_C.TAILOR_DIR = _C.DATA_DIR / "tailored"
_C.GMAIL_PROPOSALS_PATH = _C.DATA_DIR / "gmail_proposals.json"

from candid import jobs as J  # noqa: E402
from candid import prep as P  # noqa: E402
from candid.__main__ import main as cli_main  # noqa: E402

EDU_JD = (
    "We are a nonprofit education organization seeking a Program Manager to "
    "expand literacy programs in underserved schools. You will lead "
    "curriculum development, teacher training workshops, and student "
    "mentorship initiatives. Requirements: 5+ years in education programs, "
    "passion for social impact."
)
SAAS_JD = (
    "We are a B2B SaaS company hiring a Backend Engineer to build our "
    "billing platform. Requirements: 5+ years Python, distributed systems, "
    "Postgres. Competitive salary and equity."
)


def _write_profile(extra=None):
    prof = {"name": "Test User", "skills": ["python", "program management"],
            "seniority": "senior", "years_experience": 6.0}
    if extra:
        prof.update(extra)
    path = Path(_tmp) / "profile.json"
    path.write_text(json.dumps(prof), encoding="utf-8")
    return path


def _write_jd(text):
    p = Path(_tmp) / "jd.txt"
    p.write_text(text, encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# adapter registry
# ---------------------------------------------------------------------------

def test_adapters_include_nonprofit_feeds():
    assert "reliefweb" in J.ADAPTERS
    assert "reliefweb_volunteer" in J.ADAPTERS
    assert "arbeitnow" in J.ADAPTERS and "remoteok" in J.ADAPTERS
    for name in ("reliefweb", "reliefweb_volunteer"):
        assert callable(J.ADAPTERS[name])


def test_unknown_source_check_still_rejects_bogus():
    try:
        J.curate({}, role="Engineer", sources=["nope"])
    except J.JobsError as exc:
        assert "Unknown source(s)" in str(exc)
    else:
        raise AssertionError("expected JobsError for unknown source")


# ---------------------------------------------------------------------------
# match + mission fit
# ---------------------------------------------------------------------------

def test_match_json_carries_mission_fit(capsys):
    _write_profile({"cause_interests": ["education"]})
    cli_main(["match", "--jd", _write_jd(EDU_JD), "--json"])
    out = capsys.readouterr().out
    result = json.loads(out)
    assert "mission_fit" in result
    assert result["mission_fit"]["score"] is not None
    assert "education" in result["mission_fit"]["matched_causes"]


def test_match_text_shows_mission_fit_when_relevant(capsys):
    _write_profile({"cause_interests": ["education"]})
    cli_main(["match", "--jd", _write_jd(EDU_JD)])
    out = capsys.readouterr().out
    assert "Mission fit" in out


def test_match_text_hides_mission_fit_for_plain_saas(capsys):
    _write_profile()  # no cause_interests
    cli_main(["match", "--jd", _write_jd(SAAS_JD)])
    out = capsys.readouterr().out
    assert "Mission fit" not in out


# ---------------------------------------------------------------------------
# prep pack nonprofit section
# ---------------------------------------------------------------------------

def test_prep_pack_adds_nonprofit_questions():
    prof = {"name": "T", "skills": ["python"], "experience": []}
    markdown, _ = P.build_pack(prof, "Ford Foundation", "Program Manager")
    assert "## Nonprofit interview questions" in markdown
    assert "Describe your passion for our mission." in markdown


def test_prep_pack_skips_nonprofit_section_for_corp():
    prof = {"name": "T", "skills": ["python"], "experience": []}
    markdown, _ = P.build_pack(prof, "Goldman Sachs", "Engineer")
    assert "## Nonprofit interview questions" not in markdown


# ---------------------------------------------------------------------------
# nonprofit CLI group
# ---------------------------------------------------------------------------

def _run(args, capsys):
    cli_main(["nonprofit"] + args)
    return capsys.readouterr().out


def test_cli_sources(capsys):
    out = _run(["sources"], capsys)
    assert "reliefweb" in out


def test_cli_mission_fit(capsys):
    _write_profile({"cause_interests": ["education"]})
    out = _run(["mission-fit", "--jd", _write_jd(EDU_JD)], capsys)
    assert "Mission fit" in out
    assert "score:" in out


def test_cli_questions(capsys):
    out = _run(["questions", "--category", "mission", "--limit", "1"], capsys)
    assert "Describe your passion for our mission." in out


def test_cli_org_status(capsys):
    out = _run(["org-status", "--company", "Ford Foundation"], capsys)
    assert "looks like a nonprofit" in out
    assert "studentaid.gov" in out


def test_cli_comp_note(capsys):
    out = _run(["comp-note", "--title", "Program Manager",
                "--company", "Khan Academy"], capsys)
    assert "Nonprofit comp note" in out


def test_cli_negotiate_guide(capsys):
    out = _run(["negotiate-guide", "--role", "Program Manager"], capsys)
    assert "Negotiating a nonprofit offer" in out


def test_cli_pitch(capsys):
    out = _run(["pitch", "--mission", "literacy for all",
                "--background", "I taught for three years"], capsys)
    assert "literacy for all" in out
    assert "I taught for three years" in out


def test_cli_employers(capsys):
    out = _run(["employers", "--query", "education"], capsys)
    assert "Khan Academy" in out


def test_cli_digest_runs_empty(capsys):
    _write_profile()
    out = _run(["digest"], capsys)
    assert "Summary" in out

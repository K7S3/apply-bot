"""Tests for candid.drafting.threads.summarize_thread.

Deterministic, template-based summaries. No network, no LLM. Uses tmp_path
fixtures and passes an explicit tracker path so the real user data dir is
never touched.
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid.drafting import threads as th  # noqa: E402

TODAY = date.today()
D = lambda n: (TODAY - timedelta(days=n)).isoformat()  # noqa: E731


def _write(path: Path, records: list) -> Path:
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


def _rec(**overrides) -> dict:
    rec = {
        "id": 1,
        "company": "Acme Corp",
        "role": "ML Engineer",
        "status": "applied",
        "notes": "Referral from Priya.",
        "date_added": D(10),
        "date_updated": D(5),
        "interviewers": ["Dana Lee"],
        "status_history": [
            {"date": D(8), "from": "", "to": "applied",
             "note": "Recruiter confirmed receipt."},
            {"date": D(10), "from": "saved", "to": "applied"},
            "Phone screen scheduled for next week.",
        ],
        "open_questions": ["Ask about team size?"],
    }
    rec.update(overrides)
    return rec


# ---------------------------------------------------------------------------
# missing company -> empty-but-valid summary
# ---------------------------------------------------------------------------

def test_missing_company_empty_summary(tmp_path):
    p = _write(tmp_path / "tracker.json", [])
    out = th.summarize_thread("Nobody Inc", tracker=p)
    assert out == {
        "company": "Nobody Inc",
        "bullets": [],
        "last_contact": "",
        "open_questions": [],
    }


# ---------------------------------------------------------------------------
# bullet ordering: chronological, undated last
# ---------------------------------------------------------------------------

def test_bullets_chronological(tmp_path):
    p = _write(tmp_path / "tracker.json", [_rec()])
    out = th.summarize_thread("Acme Corp", tracker=p)
    bullets = out["bullets"]
    assert bullets[0].startswith(D(10) + ":")
    assert bullets[1].startswith(D(10) + ":")
    assert bullets[2].startswith(D(8) + ":")
    # undated entries come after all dated ones
    undated = [b for b in bullets if not b[:10].replace("-", "").isdigit()]
    assert len(undated) == 3
    assert bullets[-3:] == undated
    assert any("Interviewers: Dana Lee." in b for b in undated)
    assert any(b.startswith("Notes: Referral from Priya.") for b in undated)
    assert any(b == "Phone screen scheduled for next week." for b in undated)


def test_bullets_are_deterministic(tmp_path):
    p = _write(tmp_path / "tracker.json", [_rec()])
    first = th.summarize_thread("Acme Corp", tracker=p)["bullets"]
    second = th.summarize_thread("Acme Corp", tracker=p)["bullets"]
    assert first == second


# ---------------------------------------------------------------------------
# last contact picks the latest date
# ---------------------------------------------------------------------------

def test_last_contact_latest_date(tmp_path):
    rec = _rec(date_updated=D(2),
               status_history=[{"date": D(1), "from": "applied",
                                "to": "selected_for_interview"}])
    p = _write(tmp_path / "tracker.json", [rec])
    out = th.summarize_thread("Acme Corp", tracker=p)
    assert out["last_contact"] == D(1)


def test_last_contact_empty_when_no_dates(tmp_path):
    rec = _rec(date_added="", date_updated="", status_history=[])
    p = _write(tmp_path / "tracker.json", [rec])
    out = th.summarize_thread("Acme Corp", tracker=p)
    assert out["last_contact"] == ""


# ---------------------------------------------------------------------------
# open questions
# ---------------------------------------------------------------------------

def test_open_questions_from_record(tmp_path):
    p = _write(tmp_path / "tracker.json", [_rec()])
    out = th.summarize_thread("Acme Corp", tracker=p)
    assert "Ask about team size?" in out["open_questions"]


def test_quiet_applied_app_gets_followup_question(tmp_path):
    rec = _rec(date_updated=D(20), date_added=D(25),
               status_history=[], open_questions=[])
    p = _write(tmp_path / "tracker.json", [rec])
    out = th.summarize_thread("Acme Corp", tracker=p)
    assert any("follow-up" in q for q in out["open_questions"])


def test_recent_app_gets_no_followup_question(tmp_path):
    rec = _rec(date_updated=D(3), date_added=D(10),
               status_history=[], open_questions=[])
    p = _write(tmp_path / "tracker.json", [rec])
    out = th.summarize_thread("Acme Corp", tracker=p)
    assert out["open_questions"] == []


def test_prep_pack_bullet(tmp_path):
    rec = _rec(prep_pack="prep_packs/acme.md")
    p = _write(tmp_path / "tracker.json", [rec])
    out = th.summarize_thread("Acme Corp", tracker=p)
    assert any("Prep pack: prep_packs/acme.md" in b for b in out["bullets"])

"""Tests for candid.sprint_schedule. Run: python -m pytest tests/test_sprint_schedule.py -q"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from candid import sprint_schedule as S


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    return tmp_path


def _seed_sprint(data_dir: Path, **overrides) -> dict:
    sprint = {
        "id": 1,
        "week_start": "2026-09-21",  # a Monday
        "title": "Week 1",
        "target_apps": 5,
        "hours_budget": 6.0,
        "targets": [
            {"company": "Acme", "role": "ML Engineer", "jd_link": "",
             "priority": "high", "status": "todo", "batch": "b1",
             "tracker_id": None, "done_at": None},
            {"company": "Beta", "role": "Data Scientist", "jd_link": "",
             "priority": "low", "status": "todo", "batch": "b1",
             "tracker_id": None, "done_at": None},
            {"company": "Gamma", "role": "SWE", "jd_link": "",
             "priority": "medium", "status": "todo", "batch": "b1",
             "tracker_id": None, "done_at": None},
        ],
        "time_blocks": [
            {"day": "mon", "start": "18:00", "end": "19:30", "kind": "research",
             "label": "Evening research"},
            {"day": "mon", "start": "19:30", "end": "21:00", "kind": "tailor",
             "label": "Evening tailoring"},
            {"day": "tue", "start": "18:00", "end": "19:30", "kind": "apply",
             "label": "Evening applications"},
        ],
        "notes": [],
        "status": "active",
        "created_at": "2026-09-21T09:00:00",
        "review": {},
        "template": "",
    }
    sprint.update(overrides)
    (data_dir / "sprints.json").write_text(json.dumps([sprint]), encoding="utf-8")
    return sprint


# --- templates ---------------------------------------------------------------
def test_builtins_present_and_marked(data_dir):
    templates = S.list_templates()
    for name, apps, hours in (("steady-5", 5, 6.0), ("aggressive-10", 10, 10.0),
                             ("light-3", 3, 3.0)):
        assert name in templates
        assert templates[name]["target_apps"] == apps
        assert templates[name]["hours_budget"] == hours
        assert templates[name]["source"] == "builtin"
        assert templates[name]["default_blocks"]  # sensible evening blocks


def test_save_and_list_user_template(data_dir):
    tpl = S.save_template("mine", 7, 8.0, [
        {"day": "wed", "start": "18:00", "end": "19:00", "kind": "research",
         "label": "Research"},
    ])
    assert tpl["target_apps"] == 7
    assert tpl["hours_budget"] == 8.0
    templates = S.list_templates()
    assert templates["mine"]["source"] == "user"
    assert templates["mine"]["default_blocks"][0]["day"] == "wed"
    assert templates["mine"]["default_blocks"][0]["kind"] == "research"


def test_save_template_without_blocks(data_dir):
    tpl = S.save_template("bare", 2, 2.5)
    assert tpl["default_blocks"] == []


def test_save_template_validates_blocks(data_dir):
    with pytest.raises(S.SprintScheduleError):
        S.save_template("bad", 2, 2.0, [
            {"day": "funday", "start": "18:00", "end": "19:00", "kind": "research",
             "label": "x"},
        ])


def test_user_template_overrides_builtin(data_dir):
    S.save_template("steady-5", 9, 9.0)
    templates = S.list_templates()
    assert templates["steady-5"]["target_apps"] == 9
    assert templates["steady-5"]["source"] == "user"


def test_delete_template(data_dir):
    S.save_template("temp", 1, 1.0)
    S.delete_template("temp")
    assert "temp" not in S.list_templates()


def test_delete_unknown_template_raises(data_dir):
    with pytest.raises(S.SprintScheduleError):
        S.delete_template("nope")


def test_delete_builtin_template_raises(data_dir):
    with pytest.raises(S.SprintScheduleError):
        S.delete_template("steady-5")
    assert "steady-5" in S.list_templates()


def test_apply_template_sets_fields(data_dir):
    _seed_sprint(data_dir)
    sp = S.apply_template(1, "aggressive-10")
    assert sp["target_apps"] == 10
    assert sp["hours_budget"] == 10.0
    assert sp["template"] == "aggressive-10"
    assert sp["time_blocks"]  # default blocks installed
    kinds = [b["kind"] for b in sp["time_blocks"]]
    assert "research" in kinds and "apply" in kinds
    # persisted
    stored = json.loads((data_dir / "sprints.json").read_text())[0]
    assert stored["template"] == "aggressive-10"
    assert stored["target_apps"] == 10


def test_apply_user_template(data_dir):
    _seed_sprint(data_dir)
    S.save_template("mine", 7, 8.0, [
        {"day": "wed", "start": "18:00", "end": "19:00", "kind": "research",
         "label": "Research"},
    ])
    sp = S.apply_template(1, "mine")
    assert sp["target_apps"] == 7
    assert sp["time_blocks"] == [
        {"day": "wed", "start": "18:00", "end": "19:00", "kind": "research",
         "label": "Research"},
    ]


def test_apply_template_without_default_blocks_keeps_blocks(data_dir):
    _seed_sprint(data_dir)
    S.save_template("bare", 2, 2.5)
    sp = S.apply_template(1, "bare")
    assert sp["target_apps"] == 2
    assert len(sp["time_blocks"]) == 3  # original blocks untouched
    assert sp["template"] == "bare"


def test_apply_unknown_template_raises(data_dir):
    _seed_sprint(data_dir)
    with pytest.raises(S.SprintScheduleError):
        S.apply_template(1, "nope")


def test_apply_template_unknown_sprint_raises(data_dir):
    _seed_sprint(data_dir)
    with pytest.raises(S.SprintScheduleError):
        S.apply_template(999, "steady-5")


# --- ICS export ----------------------------------------------------------------
def test_export_ics_structure(data_dir):
    _seed_sprint(data_dir)
    ics = S.export_ics(1)
    assert "BEGIN:VCALENDAR" in ics
    assert "END:VCALENDAR" in ics
    assert ics.count("BEGIN:VEVENT") == 3
    assert "UID:" in ics
    assert "DTSTAMP:" in ics
    assert "VERSION:2.0" in ics


def test_export_ics_dates_from_monday_week_start(data_dir):
    _seed_sprint(data_dir)
    ics = S.export_ics(1)
    # week_start 2026-09-21 is a Monday: mon blocks land on 20260921.
    assert "DTSTART:20260921T180000" in ics
    assert "DTEND:20260921T193000" in ics
    # tue block lands on 20260922.
    assert "DTSTART:20260922T180000" in ics
    assert "SUMMARY:Research: Evening research" in ics
    assert "SUMMARY:Apply: Evening applications" in ics


def test_export_ics_unknown_sprint_raises(data_dir):
    _seed_sprint(data_dir)
    with pytest.raises(S.SprintScheduleError):
        S.export_ics(999)


def test_write_ics(data_dir):
    _seed_sprint(data_dir)
    out = data_dir / "sprint.ics"
    result = S.write_ics(1, out)
    assert result == out
    assert out.exists()
    with out.open(encoding="utf-8", newline="") as f:
        file_lines = [ln for ln in f.read().splitlines()
                      if not ln.startswith("DTSTAMP:")]
    export_lines = [ln for ln in S.export_ics(1).splitlines()
                    if not ln.startswith("DTSTAMP:")]
    assert file_lines == export_lines


# --- daily suggestions -----------------------------------------------------------
def test_suggest_day_assigns_high_priority_first(data_dir):
    _seed_sprint(data_dir)
    suggestions = S.suggest_day(1, "mon")
    assert len(suggestions) == 2
    assert suggestions[0]["task"] == "Research: Acme ML Engineer"
    assert suggestions[1]["task"] == "Tailor resume for Gamma"
    assert suggestions[0]["block"]["kind"] == "research"


def test_suggest_day_skips_done_targets(data_dir):
    sprint = _seed_sprint(data_dir)
    sprint["targets"][0]["status"] = "done"  # Acme (high) done
    (data_dir / "sprints.json").write_text(json.dumps([sprint]), encoding="utf-8")
    suggestions = S.suggest_day(1, "mon")
    assert suggestions[0]["task"] == "Research: Gamma SWE"
    assert suggestions[1]["task"] == "Tailor resume for Beta"


def test_suggest_day_round_robin_wraps(data_dir):
    _seed_sprint(data_dir)
    # tue has a single apply block: highest-priority (Acme) gets it.
    suggestions = S.suggest_day(1, "tue")
    assert len(suggestions) == 1
    assert suggestions[0]["task"] == "Apply to Acme ML Engineer"


def test_suggest_day_no_blocks_returns_empty(data_dir):
    _seed_sprint(data_dir)
    assert S.suggest_day(1, "wed") == []


def test_suggest_day_accepts_full_day_name(data_dir):
    _seed_sprint(data_dir)
    assert len(S.suggest_day(1, "monday")) == 2


def test_suggest_day_today_runs(data_dir):
    _seed_sprint(data_dir)
    result = S.suggest_day(1, "today")
    assert isinstance(result, list)


def test_suggest_day_unknown_day_raises(data_dir):
    _seed_sprint(data_dir)
    with pytest.raises(S.SprintScheduleError):
        S.suggest_day(1, "funday")


def test_suggest_day_unknown_sprint_raises(data_dir):
    _seed_sprint(data_dir)
    with pytest.raises(S.SprintScheduleError):
        S.suggest_day(999, "mon")


# --- validation ------------------------------------------------------------------
def test_validate_blocks_accepts_valid():
    blocks = [{"day": "mon", "start": "18:00", "end": "19:30",
               "kind": "research", "label": "x"}]
    assert S.validate_blocks(blocks) == blocks


def test_validate_blocks_rejects_bad_time_format():
    for bad in ("6pm", "25:00", "18:60", "18:0", ""):
        with pytest.raises(S.SprintScheduleError):
            S.validate_blocks([{"day": "mon", "start": bad, "end": "19:00",
                                "kind": "research", "label": "x"}])


def test_validate_blocks_rejects_end_before_start():
    with pytest.raises(S.SprintScheduleError):
        S.validate_blocks([{"day": "mon", "start": "19:00", "end": "18:00",
                            "kind": "research", "label": "x"}])
    with pytest.raises(S.SprintScheduleError):
        S.validate_blocks([{"day": "mon", "start": "19:00", "end": "19:00",
                            "kind": "research", "label": "x"}])


def test_validate_blocks_rejects_bad_day():
    with pytest.raises(S.SprintScheduleError):
        S.validate_blocks([{"day": "funday", "start": "18:00", "end": "19:00",
                            "kind": "research", "label": "x"}])


def test_validate_blocks_rejects_non_dict():
    with pytest.raises(S.SprintScheduleError):
        S.validate_blocks(["not-a-block"])

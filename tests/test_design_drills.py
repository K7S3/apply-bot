"""Tests for candid.design_drills (Designer track).

Run: cd <repo> && python -m pytest tests/test_design_drills.py -q
Data paths are redirected into a temp dir by monkeypatching
candid.config.DATA_DIR (same approach as tests/test_dashboard.py).
"""
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import design_drills as DD  # noqa: E402


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "DATA_DIR", tmp_path)
    return tmp_path


# --- style rule: no em dashes anywhere in this track --------------------------
def test_no_em_dashes_in_module():
    src = Path(DD.__file__).read_text(encoding="utf-8")
    assert "\u2014" not in src


# --- critique drills -----------------------------------------------------------
SCENARIO_FIELDS = {
    "id", "title", "product_context", "design_decision",
    "visual_description", "stakeholder_constraints", "model_critique",
}


def test_scenario_bank_nonempty_with_required_fields():
    assert len(DD.SCENARIOS) >= 4
    for s in DD.SCENARIOS:
        assert SCENARIO_FIELDS <= set(s), f"scenario {s.get('id')} missing fields"
        assert s["stakeholder_constraints"], "constraints must be non-empty"
        assert len(s["model_critique"]) >= 3, "model critique should have substance"


def test_scenario_ids_unique():
    ids = [s["id"] for s in DD.SCENARIOS]
    assert len(ids) == len(set(ids))


def test_get_scenario_roundtrip():
    s = DD.get_scenario(DD.SCENARIOS[0]["id"])
    assert s["title"] == DD.SCENARIOS[0]["title"]


def test_get_scenario_unknown_raises():
    with pytest.raises(DD.DesignDrillError):
        DD.get_scenario("nope-not-real")


def test_list_scenarios_summaries():
    summaries = DD.list_scenarios()
    assert len(summaries) == len(DD.SCENARIOS)
    assert all(set(x) == {"id", "title", "product_context"} for x in summaries)


def _full_marks(overrides=None):
    d = {dim: 3 for dim, _, _ in DD.RUBRIC_DIMENSIONS}
    d.update(overrides or {})
    return d


def test_score_critique_math():
    answers = {
        "observation_quality": 3,
        "rationale": 2,
        "prioritization": 1,
        "constructive_suggestions": 0,
    }
    r = DD.score_critique(answers)
    assert r["total"] == 6
    assert r["max_total"] == 12
    assert r["percent"] == 50
    assert r["band"] == "Developing"
    assert set(r["feedback"]) == set(answers)
    assert all(isinstance(v, str) and v for v in r["feedback"].values())


def test_score_critique_bands():
    assert DD.score_critique(_full_marks())["band"] == "Interview-ready"
    assert DD.score_critique(_full_marks())["total"] == 12
    low = {dim: 0 for dim, _, _ in DD.RUBRIC_DIMENSIONS}
    assert DD.score_critique(low)["band"] == "Building"
    assert DD.score_critique(low)["percent"] == 0
    mid = _full_marks({"observation_quality": 0})
    assert DD.score_critique(mid)["total"] == 9
    assert DD.score_critique(mid)["band"] == "Interview-ready"


def test_score_critique_rejects_bad_input():
    dims = [d for d, _, _ in DD.RUBRIC_DIMENSIONS]
    with pytest.raises(DD.DesignDrillError):
        DD.score_critique({dims[0]: 3})  # missing dims
    bad = _full_marks()
    bad["rationale"] = 4  # out of range
    with pytest.raises(DD.DesignDrillError):
        DD.score_critique(bad)
    bad = _full_marks()
    bad["rationale"] = True  # bool is not a valid score
    with pytest.raises(DD.DesignDrillError):
        DD.score_critique(bad)
    bad = _full_marks()
    bad["mystery_dim"] = 2  # unknown dim
    with pytest.raises(DD.DesignDrillError):
        DD.score_critique(bad)


def test_critique_drill_interactive(capsys):
    inputs = ["First observation about hierarchy", "Second line on copy", "",
              "3", "2", "1", "2"]
    with mock.patch("builtins.input", side_effect=inputs):
        result = DD.critique_drill(scenario_id=DD.SCENARIOS[1]["id"])
    assert result["scenario"] == DD.SCENARIOS[1]["id"]
    assert "First observation" in result["critique"]
    assert result["score"]["total"] == 8
    out = capsys.readouterr().out
    assert "Model critique" in out
    assert "Self-score rubric" in out


def test_critique_drill_default_scenario(capsys):
    with mock.patch("builtins.input", side_effect=["", "2", "2", "2", "2"]):
        result = DD.critique_drill()
    assert result["scenario"] == DD.SCENARIOS[0]["id"]
    assert result["score"]["total"] == 8


# --- whiteboard drills ----------------------------------------------------------
EXERCISE_FIELDS = {
    "id", "title", "prompt", "context", "constraints",
    "expected_artifacts",
}


def test_exercise_bank_nonempty_with_required_fields():
    assert len(DD.EXERCISES) >= 4
    for e in DD.EXERCISES:
        assert EXERCISE_FIELDS <= set(e), f"exercise {e.get('id')} missing fields"
        assert e["constraints"] and e["expected_artifacts"]


def test_exercise_ids_unique():
    ids = [e["id"] for e in DD.EXERCISES]
    assert len(ids) == len(set(ids))


def test_get_exercise_unknown_raises():
    with pytest.raises(DD.DesignDrillError):
        DD.get_exercise("nope")


def test_whiteboard_rubric_covers_brief():
    dims = [d for d, _, _ in DD.WHITEBOARD_RUBRIC]
    assert dims == ["problem_framing", "user_empathy", "ideation_breadth",
                    "prioritization", "communication"]


def test_format_time_left():
    assert DD.format_time_left(90) == "01:30"
    assert DD.format_time_left(0) == "00:00"
    assert DD.format_time_left(5) == "00:05"
    with pytest.raises(DD.DesignDrillError):
        DD.format_time_left(-1)


def test_countdown_injected():
    slept, said = [], []
    DD.countdown(90, tick_interval=60,
                 sleep_fn=slept.append, out_fn=said.append)
    assert slept == [60, 30]
    assert said[0].startswith("Timer started: 01:30")
    assert "Time left: 00:30" in said
    assert "Time left: 00:00" in said
    assert said[-1] == "Time's up! Pens down."


def test_countdown_rejects_bad_args():
    with pytest.raises(DD.DesignDrillError):
        DD.countdown(-5, sleep_fn=lambda s: None, out_fn=lambda s: None)
    with pytest.raises(DD.DesignDrillError):
        DD.countdown(10, tick_interval=0, sleep_fn=lambda s: None,
                     out_fn=lambda s: None)


def test_review_checklist_and_evaluate():
    qs = DD.review_checklist()
    assert len(qs) >= 6
    assert all(isinstance(q, str) and q for q in qs)
    r = DD.evaluate_review([True] * len(qs))
    assert r["yes"] == len(qs) and r["percent"] == 100
    assert r["verdict"] == "Strong whiteboard run"
    r = DD.evaluate_review([True, False] * (len(qs) // 2))
    assert r["verdict"] == "Solid, tighten the gaps"
    r = DD.evaluate_review([False] * len(qs))
    assert r["verdict"] == "Re-run with the checklist in hand"
    with pytest.raises(DD.DesignDrillError):
        DD.evaluate_review([])
    with pytest.raises(DD.DesignDrillError):
        DD.evaluate_review([1, 0])


def test_whiteboard_drill_interactive(capsys):
    n = len(DD.review_checklist())
    with mock.patch("builtins.input", side_effect=[""] + ["y"] * n), \
         mock.patch.object(DD, "countdown") as cd:
        result = DD.whiteboard_drill(exercise_id="split-bill", minutes=30)
    cd.assert_called_once_with(30 * 60)
    assert result["exercise"] == "split-bill"
    assert result["minutes"] == 30
    assert result["review"]["percent"] == 100
    out = capsys.readouterr().out
    assert "split" in out.lower() or "Splitting" in out


def test_whiteboard_drill_rejects_bad_minutes():
    with pytest.raises(DD.DesignDrillError):
        DD.whiteboard_drill(minutes=0)


# --- rapid-fire ------------------------------------------------------------------
def test_rapid_question_bank_fields():
    assert len(DD.RAPID_QUESTIONS) >= 8
    for q in DD.RAPID_QUESTIONS:
        assert {"id", "question", "strong_pointers", "weak_signals"} <= set(q)
        assert q["strong_pointers"] and q["weak_signals"]


def test_get_rapid_questions_deterministic():
    a = DD.get_rapid_questions(5)
    b = DD.get_rapid_questions(5)
    assert [q["id"] for q in a] == [q["id"] for q in b]
    assert len(a) == 5
    # n larger than the bank clamps instead of raising
    assert len(DD.get_rapid_questions(999)) == len(DD.RAPID_QUESTIONS)
    assert len(DD.get_rapid_questions(1)) == 1
    with pytest.raises(DD.DesignDrillError):
        DD.get_rapid_questions(0)
    with pytest.raises(DD.DesignDrillError):
        DD.get_rapid_questions(-2)


def test_rapid_fire_interactive(capsys):
    with mock.patch("builtins.input", side_effect=["my answer", "", "second", ""]):
        result = DD.rapid_fire(n=2)
    assert result["answered"] == 2
    assert len(result["question_ids"]) == 2
    out = capsys.readouterr().out
    assert "Strong-answer pointers" in out
    assert "Weak signals" in out


# --- presentation plan -------------------------------------------------------------
def test_presentation_plan_timing_sums():
    for total in (5, 10, 15, 30, 45):
        plan = DD.build_presentation_plan(total_minutes=total)
        cps = plan["checkpoints"]
        assert sum(c["minutes"] for c in cps) == total, f"total={total}"
        assert all(c["minutes"] >= 1 for c in cps)
        assert [c["id"] for c in cps] == [c[0] for c in DD.CHECKPOINTS]
        # offsets are contiguous
        assert cps[0]["starts_at_minute"] == 0
        for prev, cur in zip(cps, cps[1:]):
            assert cur["starts_at_minute"] == prev["ends_at_minute"]
        assert cps[-1]["ends_at_minute"] == total
        assert all(c["speaker_prompts"] for c in cps)


def test_build_presentation_plan_rejects_small_or_bad():
    with pytest.raises(DD.DesignDrillError):
        DD.build_presentation_plan(total_minutes=4)
    with pytest.raises(DD.DesignDrillError):
        DD.build_presentation_plan(total_minutes="ten")


def test_render_plan_markdown():
    plan = DD.build_presentation_plan(total_minutes=10)
    md = DD.render_plan_markdown(plan)
    assert "# Portfolio presentation plan (10 minutes)" in md
    for _cid, name, _frac, _prompts in DD.CHECKPOINTS:
        assert name in md
    assert "Speaker prompts" in md


def test_save_presentation_plan_writes_file(data_dir):
    plan = DD.build_presentation_plan(total_minutes=10)
    path = DD.save_presentation_plan(plan)
    assert path.parent == data_dir / "design_packs"
    assert path.suffix == ".md"
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "Portfolio presentation plan" in content


def test_presentation_plan_end_to_end(data_dir, capsys):
    path = DD.presentation_plan(total_minutes=10)
    assert path.exists()
    assert (data_dir / "design_packs") in path.parents
    out = capsys.readouterr().out
    assert "Saved to" in out
    md = path.read_text(encoding="utf-8")
    assert "Q&A buffer" in md

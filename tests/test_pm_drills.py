"""Tests for candid.pm_drills — no network, no LLM, tmp CANDID_DATA_DIR."""

import json
import os
import sys

import pytest

# tmp data dir MUST be set before candid.config is imported
TMP = None


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    global TMP
    d = tmp_path / "candid_data"
    monkeypatch.setenv("CANDID_DATA_DIR", str(d))
    TMP = d
    # force re-import with the patched env
    for mod in [m for m in list(sys.modules) if m == "candid.pm_drills"
                or m.startswith("candid.pm_drills.")]:
        del sys.modules[mod]
    yield
    for mod in [m for m in list(sys.modules) if m == "candid.pm_drills"
                or m.startswith("candid.pm_drills.")]:
        del sys.modules[mod]


def _mod():
    import importlib
    return importlib.import_module("candid.pm_drills")


# ---------------------------------------------------------------------------
# bank retrieval
# ---------------------------------------------------------------------------

def test_product_sense_bank_nonempty():
    M = _mod()
    prompts = M.list_product_sense()
    assert len(prompts) >= 3
    assert all("id" in p and "title" in p and "prompt" in p for p in prompts)


def test_get_product_sense_by_id():
    M = _mod()
    p = M.get_product_sense(0)
    assert p["id"] == 0
    assert p["framework"] == "CIRCLES"
    assert len(p["framework_steps"]) >= 5
    assert "outline" in p["example_outline"].lower() or len(p["example_outline"]) > 50
    assert set(p["rubric"]) == {"user_clarity", "structure", "user_empathy",
                                "creativity", "prioritization"}


def test_get_product_sense_unknown_id():
    M = _mod()
    with pytest.raises(M.DrillsError):
        M.get_product_sense(999)


def test_metrics_bank_nonempty():
    M = _mod()
    scenarios = M.list_metrics()
    assert len(scenarios) >= 2
    assert all("id" in s and "scenario" in s for s in scenarios)


def test_get_metrics_scenario_by_id():
    M = _mod()
    s = M.get_metrics_scenario(1)
    assert s["id"] == 1
    assert set(s["expected"]) == {"north_star", "guardrails",
                                  "supporting_metrics", "segmentation"}


def test_get_metrics_unknown_id():
    M = _mod()
    with pytest.raises(M.DrillsError):
        M.get_metrics_scenario(12345)


def test_estimation_bank_nonempty():
    M = _mod()
    qs = M.list_estimation()
    assert len(qs) >= 2
    assert all("id" in q and "question" in q for q in qs)


def test_get_estimation_by_id():
    M = _mod()
    q = M.get_estimation(0)
    assert q["id"] == 0
    assert q["low"] < q["high"]
    assert len(q["framework_steps"]) >= 3
    assert len(q["worked"]) > 20


def test_get_estimation_unknown_id():
    M = _mod()
    with pytest.raises(M.DrillsError):
        M.get_estimation(77)


# ---------------------------------------------------------------------------
# rubric / score parsing and validation
# ---------------------------------------------------------------------------

def test_parse_scores_valid():
    M = _mod()
    s = M.parse_scores("user_clarity=4,structure=3,user_empathy=5,creativity=2,prioritization=4")
    assert s == {"user_clarity": 4, "structure": 3, "user_empathy": 5,
                 "creativity": 2, "prioritization": 4}


def test_parse_scores_aliases():
    M = _mod()
    s = M.parse_scores("clarity=4,empathy=3,priority=5")
    assert s == {"user_clarity": 4, "user_empathy": 3, "prioritization": 5}


def test_parse_scores_rejects_out_of_range():
    M = _mod()
    for bad in ("user_clarity=0", "structure=6", "creativity=-1"):
        with pytest.raises(M.DrillsError):
            M.parse_scores(bad)


def test_parse_scores_rejects_unknown_dim():
    M = _mod()
    with pytest.raises(M.DrillsError):
        M.parse_scores("vibes=4")


def test_parse_scores_rejects_non_integer():
    M = _mod()
    with pytest.raises(M.DrillsError):
        M.parse_scores("structure=high")


def test_submit_product_sense_rejects_bad_scores():
    M = _mod()
    with pytest.raises(M.DrillsError):
        M.submit_product_sense(0, "some answer", {"structure": 9})
    with pytest.raises(M.DrillsError):
        M.submit_product_sense(0, "some answer", {"nope": 3})


def test_submit_product_sense_rejects_empty_answer():
    M = _mod()
    with pytest.raises(M.DrillsError):
        M.submit_product_sense(0, "   ")
    with pytest.raises(M.DrillsError):
        M.submit_metrics(0, "")
    with pytest.raises(M.DrillsError):
        M.submit_metrics(0, "")


# ---------------------------------------------------------------------------
# estimation checking
# ---------------------------------------------------------------------------

def test_estimate_in_range():
    M = _mod()
    q = M.get_estimation(0)
    mid = (q["low"] + q["high"]) / 2
    r = M.check_estimate(0, mid)
    assert r["in_range"] is True
    assert r["low"] == q["low"] and r["high"] == q["high"]
    assert "worked" in r and len(r["worked"]) > 0


def test_estimate_out_of_range_low():
    M = _mod()
    r = M.check_estimate(0, 1)
    assert r["in_range"] is False


def test_estimate_out_of_range_high():
    M = _mod()
    q = M.get_estimation(0)
    r = M.check_estimate(0, q["high"] * 100)
    assert r["in_range"] is False


def test_estimate_boundary_inclusive():
    M = _mod()
    q = M.get_estimation(1)
    assert M.check_estimate(1, q["low"])["in_range"] is True
    assert M.check_estimate(1, q["high"])["in_range"] is True


@pytest.mark.parametrize("raw,expected", [
    ("50000", 50000.0),
    ("50,000", 50000.0),
    ("50k", 50000.0),
    ("1.2M", 1200000.0),
    ("2b", 2000000000.0),
    (75000, 75000.0),
])
def test_parse_estimate_formats(raw, expected):
    M = _mod()
    assert M.parse_estimate(raw) == expected


def test_parse_estimate_rejects_garbage():
    M = _mod()
    with pytest.raises(M.DrillsError):
        M.parse_estimate("a lot")


def test_estimate_unknown_qid():
    M = _mod()
    with pytest.raises(M.DrillsError):
        M.check_estimate(999, 100)


# ---------------------------------------------------------------------------
# storage round-trip
# ---------------------------------------------------------------------------

def test_storage_round_trip_product_sense():
    M = _mod()
    a = M.submit_product_sense(0, "my answer text",
                               {"user_clarity": 4, "structure": 3})
    assert a["type"] == "product-sense"
    assert a["item_id"] == 0
    assert a["scores"] == {"user_clarity": 4, "structure": 3}
    assert a["rubric_avg"] == 3.5
    loaded = M.load_attempts()
    assert len(loaded) == 1
    assert loaded[0]["answer"] == "my answer text"
    # file actually written under the tmp dir
    assert (TMP / "pm_drills.json").exists()


def test_storage_round_trip_metrics_and_estimate():
    M = _mod()
    M.submit_metrics(1, "north star is conversion")
    M.submit_estimate(0, 300000)
    loaded = M.load_attempts()
    assert [a["type"] for a in loaded] == ["metrics", "estimate"]
    assert loaded[1]["in_range"] is True
    raw = json.loads((TMP / "pm_drills.json").read_text())
    assert len(raw) == 2


def test_load_attempts_missing_file():
    M = _mod()
    assert M.load_attempts() == []


def test_reveal_metrics_content():
    M = _mod()
    text = M.reveal_metrics(0)
    assert "north_star" in text
    assert "guardrails" in text
    # reveal must not store an attempt
    assert M.load_attempts() == []


# ---------------------------------------------------------------------------
# stats aggregation
# ---------------------------------------------------------------------------

def _seed(M):
    M.submit_product_sense(0, "ans1", {"user_clarity": 4, "structure": 2})
    M.submit_product_sense(1, "ans2", {"user_clarity": 2, "structure": 4})
    M.submit_metrics(0, "metrics answer")
    q = M.get_estimation(0)
    M.submit_estimate(0, (q["low"] + q["high"]) / 2)  # correct
    M.submit_estimate(0, 1)  # wrong


def test_stats_aggregation():
    M = _mod()
    _seed(M)
    s = M.drill_stats()
    assert s["total_attempts"] == 5
    assert s["by_type"] == {"product-sense": 2, "metrics": 1, "estimate": 2}
    assert s["estimate_correct"] == 1
    assert s["estimate_total"] == 2
    assert s["estimate_accuracy"] == 0.5
    assert s["rubric_avgs"]["user_clarity"] == 3.0
    assert s["rubric_avgs"]["structure"] == 3.0
    assert s["current_streak_days"] >= 1
    assert s["best_streak_days"] >= 1
    assert s["last_attempt"] is not None


def test_stats_empty():
    M = _mod()
    s = M.drill_stats()
    assert s["total_attempts"] == 0
    assert s["estimate_accuracy"] is None
    assert s["current_streak_days"] == 0
    assert s["best_streak_days"] == 0
    assert s["last_attempt"] is None


def test_streak_helpers():
    M = _mod()
    from datetime import date, timedelta
    today = date.today()
    days = [(today - timedelta(days=i)).isoformat() for i in (2, 1, 0)]
    assert M._best_streak(sorted(days)) == 3
    assert M._current_streak(sorted(days)) == 3
    assert M._best_streak([]) == 0
    assert M._current_streak([]) == 0
    # gap breaks the run
    gapped = [today.isoformat(), (today - timedelta(days=5)).isoformat()]
    assert M._best_streak(sorted(gapped)) == 1


def test_render_functions_smoke():
    M = _mod()
    assert "CIRCLES" in M.render_product_sense(M.get_product_sense(0))
    assert "north_star" in M.render_metrics_scenario(M.get_metrics_scenario(0))
    assert "Framework" in M.render_estimation(M.get_estimation(0))
    r = M.check_estimate(0, 1)
    assert "OUT OF RANGE" in M.render_estimate_result(r)
    s = M.drill_stats()
    assert "Total attempts" in M.render_stats(s)


# ---------------------------------------------------------------------------
# CLI wiring: register_pm
# ---------------------------------------------------------------------------

def test_register_pm_parses_subactions(capsys):
    import argparse
    M = _mod()
    parser = argparse.ArgumentParser(prog="candid")
    sub = parser.add_subparsers(dest="cmd", required=True)
    pm = sub.add_parser("pm")
    pm_sub = pm.add_subparsers(dest="pm_cmd", required=True)
    M.register_pm(pm_sub)

    a = parser.parse_args(["pm", "drill", "product-sense", "--prompt-id", "1"])
    assert a.action == "product-sense" and a.prompt_id == 1

    a = parser.parse_args(["pm", "drill", "metrics", "--scenario-id", "2", "--reveal"])
    assert a.action == "metrics" and a.reveal is True

    a = parser.parse_args(["pm", "drill", "estimate", "--qid", "0", "--answer", "50k"])
    assert a.action == "estimate" and a.answer == "50k"

    a = parser.parse_args(["pm", "drill", "stats", "--json"])
    assert a.action == "stats" and a.json is True


def test_cmd_drill_product_sense_submit_json(capsys):
    import argparse
    M = _mod()
    parser = argparse.ArgumentParser(prog="candid")
    sub = parser.add_subparsers(dest="cmd", required=True)
    pm = sub.add_parser("pm")
    pm_sub = pm.add_subparsers(dest="pm_cmd", required=True)
    M.register_pm(pm_sub)

    a = parser.parse_args(["pm", "drill", "product-sense", "--prompt-id", "0",
                           "--answer", "test answer",
                           "--score", "user_clarity=4,structure=3", "--json"])
    a.func(a)
    out = json.loads(capsys.readouterr().out)
    assert out["type"] == "product-sense"
    assert out["scores"] == {"user_clarity": 4, "structure": 3}
    assert len(M.load_attempts()) == 1


def test_cmd_drill_estimate_and_stats(capsys):
    import argparse
    M = _mod()
    parser = argparse.ArgumentParser(prog="candid")
    sub = parser.add_subparsers(dest="cmd", required=True)
    pm = sub.add_parser("pm")
    pm_sub = pm.add_subparsers(dest="pm_cmd", required=True)
    M.register_pm(pm_sub)

    q = M.get_estimation(0)
    a = parser.parse_args(["pm", "drill", "estimate", "--qid", "0",
                           "--answer", str(int((q["low"] + q["high"]) / 2))])
    a.func(a)
    out = capsys.readouterr().out
    assert "IN RANGE" in out

    a = parser.parse_args(["pm", "drill", "stats", "--json"])
    a.func(a)
    s = json.loads(capsys.readouterr().out)
    assert s["total_attempts"] == 1
    assert s["estimate_accuracy"] == 1.0


def test_cmd_drill_metrics_answer_and_reveal(capsys):
    import argparse
    M = _mod()
    parser = argparse.ArgumentParser(prog="candid")
    sub = parser.add_subparsers(dest="cmd", required=True)
    pm = sub.add_parser("pm")
    pm_sub = pm.add_subparsers(dest="pm_cmd", required=True)
    M.register_pm(pm_sub)

    a = parser.parse_args(["pm", "drill", "metrics", "--scenario-id", "0",
                           "--answer", "my metrics answer"])
    a.func(a)
    assert "Recorded" in capsys.readouterr().out
    assert len(M.load_attempts()) == 1

    a = parser.parse_args(["pm", "drill", "metrics", "--scenario-id", "0", "--reveal"])
    a.func(a)
    assert "north_star" in capsys.readouterr().out
    # reveal did not add another attempt
    assert len(M.load_attempts()) == 1

"""Tests for the batch-35 coding patterns curriculum (candid.patterns)."""

from __future__ import annotations

import json
from datetime import date

import pytest

from candid import patterns as P


@pytest.fixture()
def pdir(tmp_path, monkeypatch):
    """Isolate patterns user state per test."""
    d = tmp_path / "candid_data"
    monkeypatch.setenv("CANDID_DATA_DIR", str(d))
    return d


# ---------------------------------------------------------------------------
# 1. taxonomy
# ---------------------------------------------------------------------------

def test_taxonomy_has_twenty_unique_ids():
    assert len(P.PATTERNS) == 20
    assert len(set(P.PATTERN_IDS)) == 20


def test_taxonomy_structure_valid():
    assert P._taxonomy_report()["errors"] == []


def test_get_pattern_known_and_unknown():
    p = P.get_pattern("sliding-window")
    assert p["name"] == "Sliding Window"
    assert len(p["cues"]) >= 3 and p["template"]
    with pytest.raises(P.PatternsError):
        P.get_pattern("nope")


# ---------------------------------------------------------------------------
# 2. problem tagging
# ---------------------------------------------------------------------------

def test_load_bank_all_tagged():
    bank = P.load_bank()
    assert len(bank) == 15
    for prob in bank:
        assert prob.get("patterns"), prob["id"]
        for t in prob["patterns"]:
            assert t in P.PATTERN_IDS


def test_validate_bank_clean():
    r = P.validate_bank()
    assert r["errors"] == []
    assert r["problems"] == 15
    assert "hashmap" in r["patterns_used"]


def test_problems_for_pattern_sorted_easy_first():
    got = P.problems_for_pattern("hashmap")
    ids = [p["id"] for p in got]
    assert "two-sum" in ids and "valid-anagram" in ids
    ranks = [P.DIFFICULTY_RANK[p["difficulty"]] for p in got]
    assert ranks == sorted(ranks)


def test_problems_for_pattern_unknown_raises():
    with pytest.raises(P.PatternsError):
        P.problems_for_pattern("nope")


def test_coverage_maps_pattern_to_problems():
    cov = P.coverage()
    assert set(cov["two-pointers"]) == {"container-water", "two-sum"}
    assert "backtracking" not in cov  # no bank problems yet


# ---------------------------------------------------------------------------
# 6. attempt logging
# ---------------------------------------------------------------------------

def test_log_attempt_round_trip(pdir):
    rec = P.log_attempt("two-sum", solved=True, quality=4, minutes=12,
                        at="2026-09-20")
    assert rec["problem_id"] == "two-sum"
    assert rec["solved"] is True and rec["quality"] == 4
    assert rec["minutes"] == 12 and rec["date"] == "2026-09-20"
    assert set(rec["patterns"]) == {"hashmap", "two-pointers"}
    attempts = P.read_attempts()
    assert len(attempts) == 1 and attempts[0]["problem_id"] == "two-sum"


def test_log_attempt_defaults_quality(pdir):
    assert P.log_attempt("two-sum", True, at="2026-09-20")["quality"] == 4
    assert P.log_attempt("coin-change", False, at="2026-09-20")["quality"] == 2


def test_log_attempt_unknown_problem(pdir):
    with pytest.raises(P.PatternsError):
        P.log_attempt("fizz-buzz", True)


def test_log_attempt_bad_quality(pdir):
    with pytest.raises(P.PatternsError):
        P.log_attempt("two-sum", True, quality=9)
    with pytest.raises(P.PatternsError):
        P.log_attempt("two-sum", True, quality="high")


def test_log_attempt_bad_minutes(pdir):
    with pytest.raises(P.PatternsError):
        P.log_attempt("two-sum", True, minutes=-5)


def test_log_attempt_bad_date(pdir):
    with pytest.raises(P.PatternsError):
        P.log_attempt("two-sum", True, at="yesterday")


# ---------------------------------------------------------------------------
# 3. skill-gap detection / mastery
# ---------------------------------------------------------------------------

def test_pattern_mastery_math(pdir):
    P.log_attempt("two-sum", True, quality=4, at="2026-09-20")
    m = P.pattern_mastery()
    # solve_rate 1.0, avg_q 4 -> 100*(0.6 + 0.4*0.8) = 92
    assert m["hashmap"]["mastery"] == 92
    assert m["hashmap"]["attempts"] == 1
    assert m["hashmap"]["solve_rate"] == 1.0
    assert m["hashmap"]["avg_quality"] == 4.0
    assert m["two-pointers"]["mastery"] == 92  # attempt counts for all tags
    assert m["stack"]["mastery"] is None  # untested, not zero


def test_pattern_mastery_failed_attempt(pdir):
    P.log_attempt("coin-change", False, quality=2, at="2026-09-20")
    m = P.pattern_mastery()
    # 100*(0 + 0.4*0.4) = 16
    assert m["dp-2d"]["mastery"] == 16


def test_weak_patterns_ordering(pdir):
    P.log_attempt("coin-change", False, quality=2, at="2026-09-20")  # dp-2d: 16
    P.log_attempt("two-sum", True, quality=4, at="2026-09-20")  # hashmap: 92
    weak = P.weak_patterns()
    assert weak[0]["pattern"] == "dp-2d"  # known-weak first
    assert weak[0]["mastery"] == 16
    # then untested patterns that have bank problems, then empty ones
    rest = [w["pattern"] for w in weak[1:]]
    assert "dp-1d" in rest  # untested, has bank problems
    assert "backtracking" in rest  # untested, no bank problems
    assert rest.index("dp-1d") < rest.index("backtracking")


def test_weak_patterns_threshold(pdir):
    P.log_attempt("two-sum", True, quality=4, at="2026-09-20")  # 92
    assert all(w["pattern"] != "hashmap" for w in P.weak_patterns(threshold=60))
    assert any(w["pattern"] == "hashmap" for w in P.weak_patterns(threshold=95))


# ---------------------------------------------------------------------------
# 5. spaced repetition
# ---------------------------------------------------------------------------

def test_review_first_success(pdir):
    card = P.review("two-sum", 4, today="2026-09-20")
    assert card["interval"] == 1
    assert card["repetitions"] == 1
    assert card["next_due"] == "2026-09-21"
    assert card["reviews"] == 1


def test_review_failure_resets(pdir):
    P.review("two-sum", 5, today="2026-09-20")
    card = P.review("two-sum", 2, today="2026-09-21")
    assert card["repetitions"] == 0
    assert card["interval"] == 1
    assert card["next_due"] == "2026-09-22"


def test_review_sm2_progression(pdir):
    P.review("two-sum", 4, today="2026-09-20")  # reps=1, int=1
    c2 = P.review("two-sum", 4, today="2026-09-21")  # reps=2, int=6
    assert c2["interval"] == 6
    assert c2["next_due"] == "2026-09-27"
    c3 = P.review("two-sum", 5, today="2026-09-27")  # reps=3, int=round(6*e)
    assert c3["interval"] == round(6 * c2["easiness"])
    assert c3["easiness"] >= 1.3


def test_review_easiness_floor(pdir):
    card = None
    for i in range(6):
        card = P.review("two-sum", 3, today=f"2026-09-{20 + i:02d}")
    assert card["easiness"] >= 1.3


def test_review_bad_quality_and_unknown(pdir):
    with pytest.raises(P.PatternsError):
        P.review("two-sum", 7)
    with pytest.raises(P.PatternsError):
        P.review("nope", 4)


def test_due_cards(pdir):
    assert P.due_cards(as_of="2026-09-20") == []
    P.review("two-sum", 4, today="2026-09-20")  # due 2026-09-21
    assert P.due_cards(as_of="2026-09-20") == []
    due = P.due_cards(as_of="2026-09-21")
    assert [c["problem_id"] for c in due] == ["two-sum"]


def test_due_cards_sorted(pdir):
    P.review("two-sum", 4, today="2026-09-18")  # due 09-19
    P.review("coin-change", 4, today="2026-09-20")  # due 09-21
    due = P.due_cards(as_of="2026-09-25")
    assert [c["problem_id"] for c in due] == ["two-sum", "coin-change"]


def test_get_card_creates(pdir):
    card = P.get_card("two-sum", today="2026-09-20")
    assert card["next_due"] == "2026-09-20"
    assert card["reviews"] == 0


# ---------------------------------------------------------------------------
# 4. Blind-75-style plans
# ---------------------------------------------------------------------------

def test_build_plan_weakest_first(pdir):
    P.log_attempt("coin-change", False, quality=1, at="2026-09-20")  # dp-2d weak
    plan = P.build_plan()
    assert plan["gap_order"][0] == "dp-2d"
    assert plan["weeks"][0]["items"][0]["focus_pattern"] == "dp-2d"


def test_build_plan_explicit_gaps_order(pdir):
    plan = P.build_plan(gaps=["sliding-window", "dp-1d"], total=10)
    assert plan["gap_order"] == ["sliding-window", "dp-1d"]
    firsts = [w["items"][0]["focus_pattern"] for w in plan["weeks"] if w["items"]]
    assert firsts[0] == "sliding-window"


def test_build_plan_caps_and_weeks(pdir):
    plan = P.build_plan(gaps=["hashmap"], total=3, per_pattern_cap=2, weeks=2)
    assert plan["total"] == 2  # per_pattern_cap binds (hashmap has 5)
    assert len(plan["weeks"]) == 2
    # easy ramp: first hashmap problem should be easy
    first = plan["weeks"][0]["items"][0]
    assert P.DIFFICULTY_RANK[first["difficulty"]] == 0


def test_build_plan_total_cap(pdir):
    plan = P.build_plan(total=200)
    assert plan["total"] <= 15  # bank size binds
    assert plan["cap"] == 75


def test_build_plan_items_shape(pdir):
    plan = P.build_plan(gaps=["stack"], total=5)
    for w in plan["weeks"]:
        for it in w["items"]:
            assert set(it) >= {"problem_id", "title", "difficulty",
                               "focus_pattern", "patterns"}


def test_build_plan_bad_input(pdir):
    with pytest.raises(P.PatternsError):
        P.build_plan(total=0)
    with pytest.raises(P.PatternsError):
        P.build_plan(gaps=["nope"])
    with pytest.raises(P.PatternsError):
        P.build_plan(weeks=0)


def test_render_and_export_plan(pdir, tmp_path):
    plan = P.build_plan(gaps=["stack", "merge-intervals"], total=4, weeks=2)
    text = P.render_plan(plan)
    assert "# Coding patterns study plan" in text
    assert "## Week 1" in text and "## Week 2" in text
    assert "- [ ] `valid-parentheses`" in text
    fp = P.export_plan(plan, tmp_path / "plan.md")
    assert fp.read_text(encoding="utf-8") == text


# ---------------------------------------------------------------------------
# 7. weekly drills
# ---------------------------------------------------------------------------

def test_build_drill_structure(pdir):
    P.log_attempt("coin-change", False, quality=1, at="2026-09-20")
    drill = P.build_drill(minutes_per_day=45, days=3, seed=0,
                          start="2026-09-22")
    assert len(drill["days"]) == 3
    for d in drill["days"]:
        assert d["total_minutes"] <= 45
        for it in d["items"]:
            assert it["kind"] in ("new", "review")
            assert it["est_minutes"] > 0


def test_build_drill_deterministic(pdir):
    kw = dict(minutes_per_day=45, days=5, seed=7, start="2026-09-22")
    assert P.build_drill(**kw) == P.build_drill(**kw)


def test_build_drill_targets_weak_patterns(pdir):
    P.log_attempt("coin-change", False, quality=1, at="2026-09-20")  # dp-2d weak
    drill = P.build_drill(minutes_per_day=45, days=2, seed=0,
                          start="2026-09-22")
    new_items = [it for d in drill["days"] for it in d["items"]
                 if it["kind"] == "new"]
    assert new_items, "expected new problems from weak patterns"
    # dp-2d's only problem was attempted, so next-weakest banked pattern wins
    assert new_items[0]["focus_pattern"] != "dp-2d"


def test_build_drill_includes_due_reviews(pdir):
    P.review("two-sum", 4, today="2026-09-20")  # due 2026-09-21
    drill = P.build_drill(minutes_per_day=60, days=3, seed=0,
                          start="2026-09-21")
    reviews = [it for d in drill["days"] for it in d["items"]
               if it["kind"] == "review"]
    assert any(it["problem_id"] == "two-sum" for it in reviews)


def test_build_drill_bad_input(pdir):
    with pytest.raises(P.PatternsError):
        P.build_drill(minutes_per_day=5)
    with pytest.raises(P.PatternsError):
        P.build_drill(days=0)


def test_render_drill(pdir):
    drill = P.build_drill(minutes_per_day=30, days=2, start="2026-09-22")
    text = P.render_drill(drill)
    assert "Weekly drill" in text and "2026-09-22" in text


# ---------------------------------------------------------------------------
# 8. mastery dashboard
# ---------------------------------------------------------------------------

def test_mastery_report(pdir):
    P.log_attempt("two-sum", True, quality=4, at="2026-09-20")
    P.log_attempt("coin-change", False, quality=2, at="2026-09-21")
    r = P.mastery_report(as_of="2026-09-21")
    assert r["total_attempts"] == 2
    assert r["problems_attempted"] == 2
    assert r["problems_solved"] == 1
    assert r["bank_problems"] == 15
    assert r["overall_mastery"] == round((92 + 16 + 92) / 3)  # hashmap, dp-2d, two-pointers
    assert len(r["patterns"]) == 20
    row = next(x for x in r["patterns"] if x["pattern"] == "hashmap")
    assert row["mastery"] == 92 and row["bank_problems"] == 5


def test_mastery_report_empty(pdir):
    r = P.mastery_report(as_of="2026-09-21")
    assert r["overall_mastery"] is None
    assert r["streak_days"] == 0
    assert r["total_attempts"] == 0


def test_streak_days(pdir, monkeypatch):
    class FakeDate(date):
        @classmethod
        def today(cls):
            return date(2026, 9, 22)

    monkeypatch.setattr(P, "date", FakeDate)
    P.log_attempt("two-sum", True, at="2026-09-22")
    P.log_attempt("two-sum", True, at="2026-09-21")
    P.log_attempt("two-sum", True, at="2026-09-19")  # gap breaks streak
    assert P.mastery_report()["streak_days"] == 2


def test_render_mastery(pdir):
    P.log_attempt("two-sum", True, quality=4, at="2026-09-20")
    text = P.render_mastery(P.mastery_report(as_of="2026-09-20"))
    assert "Coding patterns mastery" in text
    assert "Pattern" in text and "Mastery" in text
    assert "untested" in text


# ---------------------------------------------------------------------------
# 9. cheat sheets
# ---------------------------------------------------------------------------

def test_cheatsheet_content():
    text = P.cheatsheet("sliding-window")
    assert "# Sliding Window" in text
    assert "## Recognize it" in text
    assert "## Template" in text
    assert "```python" in text
    assert "`longest-substring`" in text  # banked problem listed


def test_cheatsheet_empty_pattern():
    text = P.cheatsheet("backtracking")
    assert "No bank problems tagged" in text


def test_cheatsheet_unknown():
    with pytest.raises(P.PatternsError):
        P.cheatsheet("nope")


def test_export_cheatsheets(tmp_path):
    paths = P.export_cheatsheets(tmp_path / "sheets")
    assert len(paths) == 20
    assert all(p.suffix == ".md" and p.exists() for p in paths)


# ---------------------------------------------------------------------------
# reset + CLI smoke
# ---------------------------------------------------------------------------

def test_reset_progress(pdir):
    P.log_attempt("two-sum", True, at="2026-09-20")
    removed = P.reset_progress()
    assert removed == {"attempts": 1, "cards": 1}
    assert P.read_attempts() == []
    assert P.due_cards() == []


def test_cli_patterns_list(capsys):
    from candid.__main__ import main
    main(["patterns", "list"])
    out = capsys.readouterr().out
    assert "sliding-window" in out


def test_cli_patterns_tags(capsys):
    from candid.__main__ import main
    main(["patterns", "tags"])
    out = capsys.readouterr().out
    assert "15 problems tagged" in out


def test_cli_patterns_plan_json(pdir, capsys):
    from candid.__main__ import main
    main(["patterns", "plan", "--gaps", "stack", "--total", "2", "--json"])
    plan = json.loads(capsys.readouterr().out)
    assert plan["total"] >= 1


def test_cli_patterns_log_and_due(pdir, capsys):
    from candid.__main__ import main
    main(["patterns", "log", "--problem", "two-sum", "--solved",
          "--quality", "5", "--date", "2026-09-20"])
    assert "Logged two-sum" in capsys.readouterr().out
    main(["patterns", "due", "--as-of", "2026-09-21"])
    assert "two-sum" in capsys.readouterr().out


def test_cli_patterns_mastery_and_cheatsheet(pdir, capsys):
    from candid.__main__ import main
    main(["patterns", "mastery"])
    assert "Coding patterns mastery" in capsys.readouterr().out
    main(["patterns", "cheatsheet", "stack"])
    assert "# Stack" in capsys.readouterr().out


def test_cli_patterns_unknown_problem_fails_cleanly(pdir, capsys):
    from candid.__main__ import main
    with pytest.raises(SystemExit) as e:
        main(["patterns", "log", "--problem", "nope", "--solved"])
    assert e.value.code == 1
    assert "Unknown problem" in capsys.readouterr().err

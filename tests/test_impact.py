"""Tests for candid.impact: typed impact metrics on ledger wins.

Isolates the wins store with a per-test CANDID_DATA_DIR so no real user
data is touched. candid.wins resolves its data dir from the environment
at call time, so monkeypatching the env var is enough for isolation.

Run: cd ~/workspace/candid-batch60 && python -m pytest tests/test_impact.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    yield


def _seed(wins):
    from candid.wins import save_wins

    save_wins(wins)


def _win(win_id, title="T", date="2026-01-01", impacts=None):
    from candid.wins import new_win

    win = new_win(id=win_id, title=title, date=date)
    win["impacts"] = list(impacts or [])
    return win


def _imp(metric, before=None, after=None, unit="", category=""):
    return {
        "metric": metric,
        "before": before,
        "after": after,
        "unit": unit,
        "category": category,
    }


class TestAddImpact:
    def test_add_impact_happy_path(self):
        from candid.impact import add_impact
        from candid.wins import load_wins

        _seed([_win("w1")])
        updated = add_impact(
            "w1",
            metric="latency",
            before=200,
            after=100,
            unit="ms",
            category="performance",
        )
        assert updated["impacts"] == [
            _imp("latency", 200, 100, "ms", "performance")
        ]
        # persisted through the wins store
        stored = [w for w in load_wins() if w["id"] == "w1"][0]
        assert stored["impacts"][0]["metric"] == "latency"

    def test_add_impact_defaults(self):
        from candid.impact import add_impact

        _seed([_win("w1")])
        updated = add_impact("w1", metric="mentored juniors")
        assert updated["impacts"][0] == _imp("mentored juniors")

    def test_add_impact_unknown_win(self):
        from candid.impact import add_impact

        _seed([_win("w1")])
        with pytest.raises(ValueError):
            add_impact("nope", metric="x")

    def test_add_impact_bad_category(self):
        from candid.impact import add_impact

        _seed([_win("w1")])
        with pytest.raises(ValueError):
            add_impact("w1", metric="x", category="magic")

    def test_add_impact_rejects_bad_inputs(self):
        from candid.impact import add_impact

        _seed([_win("w1")])
        with pytest.raises(ValueError):
            add_impact("w1", metric="   ")
        with pytest.raises(ValueError):
            add_impact("w1", metric="x", before="lots")
        with pytest.raises(ValueError):
            add_impact("w1", metric="x", after=[1])


class TestRemoveImpact:
    def test_remove_impact_happy_path(self):
        from candid.impact import add_impact, remove_impact
        from candid.wins import load_wins

        _seed([_win("w1")])
        add_impact("w1", metric="a", category="cost")
        add_impact("w1", metric="b", category="time")
        updated = remove_impact("w1", 0)
        assert [i["metric"] for i in updated["impacts"]] == ["b"]
        stored = [w for w in load_wins() if w["id"] == "w1"][0]
        assert [i["metric"] for i in stored["impacts"]] == ["b"]

    def test_remove_impact_bad_index(self):
        from candid.impact import remove_impact

        _seed([_win("w1")])
        with pytest.raises(ValueError):
            remove_impact("w1", 0)  # no impacts yet
        with pytest.raises(ValueError):
            remove_impact("w1", -1)

    def test_remove_impact_unknown_win(self):
        from candid.impact import remove_impact

        _seed([_win("w1")])
        with pytest.raises(ValueError):
            remove_impact("ghost", 0)


class TestRollup:
    def test_rollup_math(self):
        from candid.impact import IMPACT_CATEGORIES, impact_rollup

        _seed(
            [
                _win("w1", impacts=[
                    _imp("mrr", 1, 2, "$", "revenue"),
                    _imp("churn", 5, 3, "%", "revenue"),
                ]),
                _win("w2", impacts=[
                    _imp("p99", 9, 4, "s", "performance"),
                ]),
                _win("w3"),  # no impacts
            ]
        )
        rollup = impact_rollup()
        assert rollup["total_wins"] == 3
        assert rollup["wins_with_impact"] == 2
        rev = rollup["by_category"]["revenue"]
        assert rev["count"] == 2
        assert rev["metrics"] == ["churn", "mrr"]
        perf = rollup["by_category"]["performance"]
        assert perf["count"] == 1
        assert perf["metrics"] == ["p99"]
        # every known category is present in the rollup
        assert set(rollup["by_category"]) == IMPACT_CATEGORIES

    def test_rollup_accepts_explicit_wins(self):
        from candid.impact import impact_rollup

        wins = [_win("w9", impacts=[_imp("x", 1, 2, "", "scale")])]
        rollup = impact_rollup(wins)
        assert rollup["total_wins"] == 1
        assert rollup["by_category"]["scale"]["count"] == 1


class TestTimeline:
    def test_timeline_orders_by_date_asc(self):
        from candid.impact import impact_timeline

        _seed(
            [
                _win("late", title="Late", date="2026-03-01",
                     impacts=[_imp("m1", 1, 2, "", "cost")]),
                _win("early", title="Early", date="2026-01-15",
                     impacts=[_imp("m2", 4, 8, "", "time")]),
            ]
        )
        rows = impact_timeline()
        assert [r["win_id"] for r in rows] == ["early", "late"]
        assert rows[0]["date"] == "2026-01-15"
        assert rows[0]["title"] == "Early"
        assert rows[0]["delta_pct"] == pytest.approx(100.0)

    def test_timeline_category_filter(self):
        from candid.impact import impact_timeline

        _seed([_win("w1", impacts=[
            _imp("a", 1, 2, "", "cost"),
            _imp("b", 1, 2, "", "time"),
        ])])
        rows = impact_timeline(category="time")
        assert [r["metric"] for r in rows] == ["b"]

    def test_timeline_bad_category(self):
        from candid.impact import impact_timeline

        with pytest.raises(ValueError):
            impact_timeline(category="nope")


class TestDeltaPct:
    @pytest.mark.parametrize(
        "before,after,expected",
        [
            (100, 150, 50.0),
            (200, 100, -50.0),
            (4, 8, 100.0),
            (0, 5, None),          # before == 0 -> undefined
            (None, 5, None),       # missing side
            (5, None, None),
            ("lots", 5, None),     # non-numeric
            (5, "lots", None),
            (True, 5, None),       # bools are not metrics
        ],
    )
    def test_delta_pct_edge_cases(self, before, after, expected):
        from candid.impact import delta_pct

        got = delta_pct(before, after)
        if expected is None:
            assert got is None
        else:
            assert got == pytest.approx(expected)


class TestBiggestWins:
    def test_ranked_by_quantified_count_then_recency(self):
        from candid.impact import biggest_wins

        def imp(n):
            return [_imp(f"m{i}", 1, 2, "", "quality") for i in range(n)]

        _seed(
            [
                _win("old3", date="2026-01-01", impacts=imp(3)),
                _win("new3", date="2026-06-01", impacts=imp(3)),
                _win("one", date="2026-05-01", impacts=imp(1)),
                _win("unquant", date="2026-07-01",
                     impacts=[_imp("vibes")]),
            ]
        )
        ranked = biggest_wins()
        assert [w["id"] for w in ranked] == ["new3", "old3", "one", "unquant"]

    def test_limit(self):
        from candid.impact import biggest_wins

        _seed([_win(f"w{i}", date=f"2026-01-{i + 1:02d}") for i in range(8)])
        assert len(biggest_wins(limit=3)) == 3
        assert len(biggest_wins()) == 5

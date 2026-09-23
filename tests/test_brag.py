"""Tests for candid.brag (brag sheet + competency coverage/gap) and the
win-logging nudge appended to candid.nudges.

Run: cd ~/workspace/candid-batch60 && python -m pytest tests/test_brag.py -q
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """CANDID_DATA_DIR override so the wins ledger stays out of real data."""
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture()
def sample_wins():
    return [
        dict(id="w1", title="Shipped recsys reranker", date="2026-08-10",
            role="ML Engineer",
            description="Built and launched a two-tower reranker.",
            star={"situation": "stale ranking", "task": "improve CTR",
                  "action": "built a two-tower model",
                  "result": "launched to prod"},
            competencies=["ml-modeling", "customer-focus"],
            impacts=[{"metric": "CTR", "before": 3.1, "after": 4.4,
                      "unit": "%", "category": "revenue"}],
            quotes=[{"text": "Crisp execution.", "author": "Teammate",
                     "source": "peer review"}],
            tags=["recsys"]),
        dict(id="w2", title="Airflow DAG refactor", date="2026-09-05",
            role="ML Engineer",
            description="Rewrote the flaky training pipelines.",
            star={},
            competencies=["data-analysis"],
            impacts=[{"metric": "pipeline failures", "before": 12, "after": 1,
                      "unit": "/month", "category": "reliability"}],
            quotes=[], tags=[]),
    ]


class TestBragSheet:
    def test_structure(self, sample_wins):
        from candid import brag as B
        md = B.brag_sheet(sample_wins)
        assert md.startswith("# Brag sheet")
        assert "all time" in md
        # grouped by competency with counts
        assert "## Ml Modeling (1)" in md
        assert "## Data Analysis (1)" in md
        # title/date/role line
        assert "### Shipped recsys reranker" in md
        assert "2026-08-10" in md and "ML Engineer" in md
        # quantified impacts inline
        assert "CTR: 3.1 -> 4.4 %" in md
        # peer quotes blockquoted with attribution
        assert "> Crisp execution. - Teammate, peer review" in md
        # STAR narrative
        assert "**Situation:** stale ranking" in md

    def test_win_appears_under_each_competency(self, sample_wins):
        from candid import brag as B
        md = B.brag_sheet(sample_wins)
        assert md.count("### Shipped recsys reranker") == 2  # ml + business

    def test_date_range_filter(self, sample_wins):
        from candid import brag as B
        md = B.brag_sheet(sample_wins, since="2026-09-01", until="2026-09-30")
        assert "2026-09-01 to 2026-09-30" in md
        assert "Airflow DAG refactor" in md
        assert "Shipped recsys reranker" not in md
        assert "## Ml Modeling (0)" in md
        assert "_No wins logged yet._" in md

    def test_export_round_trip(self, sample_wins, tmp_path):
        from candid import brag as B
        out = tmp_path / "brag.md"
        ret = B.export_brag_sheet(out, wins=sample_wins)
        assert ret == out
        assert out.read_text() == B.brag_sheet(sample_wins)

    def test_empty_sheet(self):
        from candid import brag as B
        md = B.brag_sheet([])
        assert "0 wins logged" in md


class TestCoverage:
    def test_counts_include_zero_seed(self, sample_wins):
        from candid import brag as B
        from candid.wins import COMPETENCIES
        cov = B.competency_coverage(sample_wins)
        assert cov["ml-modeling"] == 1
        assert cov["data-analysis"] == 1
        assert cov["customer-focus"] == 1
        assert cov["mentoring"] == 0
        assert set(cov) >= set(COMPETENCIES)


class TestCompetencyGap:
    JD = ("Requirements: 3+ years of machine learning experience, "
          "hands-on with data pipelines (Airflow). Kubernetes a plus.")

    def test_covered_vs_missing(self, sample_wins):
        from candid import brag as B
        # w1 tagged ml-modeling, w2 tagged data-analysis; both in JD.
        # kubernetes maps to no seeded competency -> not flagged either way.
        r = B.competency_gap(self.JD, sample_wins)
        assert "ml-modeling" in r["covered"]
        assert "data-analysis" in r["covered"]
        assert r["missing"] == []
        assert r["coverage_pct"] == 100.0

    def test_missing_when_no_tagged_win(self):
        from candid import brag as B
        r = B.competency_gap(self.JD, [dict(id="x", title="T", date="2026-01-01")])
        assert "ml-modeling" in r["missing"]
        assert "data-analysis" in r["missing"]
        assert r["covered"] == []
        assert r["coverage_pct"] == 0.0

    def test_partial_coverage_pct(self, sample_wins):
        from candid import brag as B
        # only the ml-modeling win: data-engineering is requested but untagged
        r = B.competency_gap(self.JD, [sample_wins[0]])
        assert "ml-modeling" in r["covered"]
        assert "data-analysis" in r["missing"]
        assert r["coverage_pct"] == 50.0

    def test_empty_jd(self, sample_wins):
        from candid import brag as B
        r = B.competency_gap("", sample_wins)
        assert r == {"covered": [], "missing": [], "coverage_pct": 0.0}


class TestWinNudges:
    def _seed(self, data_dir, days_ago_list):
        from candid.wins import save_wins
        wins = [dict(id=f"w{i}", title=f"win {i}",
                    date=(date.today() - timedelta(days=d)).isoformat())
                for i, d in enumerate(days_ago_list)]
        save_wins(wins)

    def test_no_nudge_when_recent_win(self, data_dir):
        from candid.nudges import win_nudges
        self._seed(data_dir, [0])
        assert win_nudges() == []

    def test_nudge_when_stale(self, data_dir):
        from candid import nudges as N
        self._seed(data_dir, [10])
        n = N.win_nudges()
        assert len(n) == 1
        assert n[0]["kind"] == "log_win"
        assert "7 days" in n[0]["message"]
        assert "candid wins add" in n[0]["action"]

    def test_nudge_on_empty_ledger(self, data_dir):
        from candid.nudges import win_nudges
        n = win_nudges()
        assert len(n) == 1 and n[0]["kind"] == "log_win"

    def test_boundary_day_counts_as_fresh(self, data_dir):
        from candid.nudges import win_nudges
        self._seed(data_dir, [7])
        assert win_nudges() == []

    def test_today_param(self, data_dir):
        from candid.nudges import win_nudges
        self._seed(data_dir, [10])
        assert win_nudges(today=date.today() - timedelta(days=5)) == []

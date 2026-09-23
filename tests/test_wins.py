"""Tests for candid.wins (career-capital ledger core).

Run: cd ~/workspace/candid-batch60 && python -m pytest tests/test_wins.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    return tmp_path


def _add(**kw):
    from candid import wins as W
    kw.setdefault("title", "Did a thing")
    return W.add_win(**kw)


class TestAdd:
    def test_add_assigns_id_and_date(self, data_dir):
        w = _add()
        assert w["id"].startswith("w-")
        assert len(w["date"]) == 10

    def test_add_requires_title(self, data_dir):
        from candid import wins as W
        with pytest.raises(ValueError):
            W.add_win(title="  ")

    def test_add_bad_date(self, data_dir):
        with pytest.raises(ValueError):
            _add(date="not-a-date")

    def test_add_bad_competency(self, data_dir):
        from candid import wins as W
        with pytest.raises(ValueError):
            W.add_win(title="x", competencies=["flying"])
        with pytest.raises(ValueError) as exc:
            W.add_win(title="x", competencies=["nope"])
        assert "leadership" in str(exc.value)

    def test_add_persists(self, data_dir):
        from candid import wins as W
        w = _add(title="Shipped X", competencies=["ownership"])
        assert W.get_win(w["id"])["title"] == "Shipped X"


class TestGetUpdateDelete:
    def test_get_missing(self, data_dir):
        from candid import wins as W
        assert W.get_win("w-9999") is None

    def test_update(self, data_dir):
        from candid import wins as W
        w = _add(title="Old")
        out = W.update_win(w["id"], title="New", tags=["promo"])
        assert out["title"] == "New"
        assert out["tags"] == ["promo"]
        assert W.get_win(w["id"])["title"] == "New"

    def test_update_missing_raises(self, data_dir):
        from candid import wins as W
        with pytest.raises(KeyError):
            W.update_win("w-9999", title="x")

    def test_update_star_merges(self, data_dir):
        from candid import wins as W
        w = _add(star={"situation": "s"})
        out = W.update_win(w["id"], star={"result": "r"})
        assert out["star"]["situation"] == "s"
        assert out["star"]["result"] == "r"

    def test_delete(self, data_dir):
        from candid import wins as W
        w = _add()
        assert W.delete_win(w["id"]) is True
        assert W.get_win(w["id"]) is None
        assert W.delete_win(w["id"]) is False


class TestListFilters:
    def _seed(self):
        _add(title="Latency win", date="2026-01-10",
             competencies=["system-design"], tags=["perf"],
             description="cut p99", role="SWE")
        _add(title="Mentor win", date="2026-03-05",
             competencies=["mentoring"], tags=["team"],
             description="onboarded intern", role="SWE")
        _add(title="Old win", date="2025-06-01",
             competencies=["system-design"], tags=["perf"],
             description="migrated db", role="Intern")

    def test_newest_first(self, data_dir):
        from candid import wins as W
        self._seed()
        got = W.list_wins()
        assert [w["title"] for w in got] == ["Mentor win", "Latency win", "Old win"]

    def test_competency_filter(self, data_dir):
        from candid import wins as W
        self._seed()
        assert {w["title"] for w in W.list_wins(competency="mentoring")} == {"Mentor win"}

    def test_tag_filter(self, data_dir):
        from candid import wins as W
        self._seed()
        assert len(W.list_wins(tag="perf")) == 2

    def test_date_window(self, data_dir):
        from candid import wins as W
        self._seed()
        got = W.list_wins(since="2026-01-01", until="2026-12-31")
        assert {w["title"] for w in got} == {"Latency win", "Mentor win"}

    def test_query(self, data_dir):
        from candid import wins as W
        self._seed()
        assert [w["title"] for w in W.list_wins(query="p99")] == ["Latency win"]

    def test_role_filter(self, data_dir):
        from candid import wins as W
        self._seed()
        assert [w["title"] for w in W.list_wins(role="intern")] == ["Old win"]


class TestTaxonomy:
    def test_register_competency(self, data_dir):
        from candid import wins as W
        W.register_competency("public-speaking", "Talks and presentations")
        assert W.normalize_competency("public-speaking") == "public-speaking"
        w = _add(title="Gave a talk", competencies=["public-speaking"])
        assert w["competencies"] == ["public-speaking"]

    def test_register_duplicate_builtin(self, data_dir):
        from candid import wins as W
        with pytest.raises(ValueError):
            W.register_competency("leadership", "x")

    def test_normalize_case(self, data_dir):
        from candid import wins as W
        assert W.normalize_competency("System Design") == "system-design"

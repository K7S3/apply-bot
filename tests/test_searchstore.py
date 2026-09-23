"""Hermetic tests for candid.searchstore: monkeypatch path constants to tmp_path."""

from __future__ import annotations

import json

import pytest

import candid.searchstore as ss
from candid.searchstore import SearchStoreError


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "SAVED_PATH", tmp_path / "saved_searches.json")
    monkeypatch.setattr(ss, "HISTORY_PATH", tmp_path / "search_history.jsonl")
    monkeypatch.setattr(ss, "WATCH_PATH", tmp_path / "search_watch.json")
    return tmp_path


# --- saved searches ----------------------------------------------------------


def test_save_get_list(store):
    ss.save_search("backend-nyc", "backend engineer NYC")
    ss.save_search("rust-remote", "rust remote")
    assert ss.get_saved("backend-nyc") == "backend engineer NYC"
    assert ss.list_saved() == {
        "backend-nyc": "backend engineer NYC",
        "rust-remote": "rust remote",
    }


def test_save_overwrites(store):
    ss.save_search("x", "one")
    ss.save_search("x", "two")
    assert ss.get_saved("x") == "two"


def test_delete(store):
    ss.save_search("x", "one")
    ss.delete_search("x")
    assert ss.list_saved() == {}
    with pytest.raises(SearchStoreError):
        ss.get_saved("x")


def test_get_missing(store):
    with pytest.raises(SearchStoreError):
        ss.get_saved("nope")


def test_delete_missing(store):
    with pytest.raises(SearchStoreError):
        ss.delete_search("nope")


@pytest.mark.parametrize(
    "name",
    ["", "   ", "has space", "bang!", "a" * 65, "dot.name", "slash/name"],
)
def test_name_validation(store, name):
    with pytest.raises(SearchStoreError):
        ss.save_search(name, "q")


@pytest.mark.parametrize("name", ["abc", "a", "A1-_", "x" * 64])
def test_name_validation_ok(store, name):
    ss.save_search(name, "q")
    assert ss.get_saved(name) == "q"


def test_blank_query(store):
    for q in ["", "   ", "\n\t"]:
        with pytest.raises(SearchStoreError):
            ss.save_search("ok-name", q)


def test_list_saved_empty(store):
    assert ss.list_saved() == {}


# --- history -----------------------------------------------------------------


def test_history_newest_first(store):
    ss.log_query("one")
    ss.log_query("two")
    ss.log_query("three")
    hist = ss.get_history()
    assert [e["query"] for e in hist] == ["three", "two", "one"]
    assert all("ts" in e for e in hist)


def test_history_limit(store):
    for i in range(10):
        ss.log_query(f"q{i}")
    hist = ss.get_history(limit=3)
    assert [e["query"] for e in hist] == ["q9", "q8", "q7"]
    assert ss.get_history(limit=0) == []


def test_history_skips_blank(store):
    ss.log_query("")
    ss.log_query("   ")
    assert ss.get_history() == []


def test_history_dedupe_consecutive(store):
    ss.log_query("same")
    ss.log_query("same")
    ss.log_query("same")
    assert [e["query"] for e in ss.get_history()] == ["same"]


def test_history_dedupe_only_most_recent(store):
    ss.log_query("a")
    ss.log_query("b")
    ss.log_query("a")
    assert [e["query"] for e in ss.get_history()] == ["a", "b", "a"]


def test_history_cap_500(store):
    for i in range(600):
        ss.log_query(f"q{i}")
    hist = ss.get_history(limit=1000)
    assert len(hist) == 500
    assert hist[0]["query"] == "q599"
    assert hist[-1]["query"] == "q100"


def test_clear_history(store, tmp_path):
    ss.log_query("one")
    ss.clear_history()
    assert ss.get_history() == []
    assert not (tmp_path / "search_history.jsonl").exists()
    ss.clear_history()  # idempotent


# --- watches -----------------------------------------------------------------


def test_record_watch(store):
    ss.record_watch("jobs", "python nyc", ["b", "a", "b"])
    entry = ss.get_watch("jobs")
    assert entry["query"] == "python nyc"
    assert entry["seen"] == ["a", "b"]
    assert entry["last_run"]


def test_get_watch_none(store):
    assert ss.get_watch("never") is None


def test_watch_new_first_run_all_new(store):
    new = ss.watch_new("w1", "q", ["a", "b", "c"])
    assert new == ["a", "b", "c"]
    entry = ss.get_watch("w1")
    assert entry["seen"] == ["a", "b", "c"]
    assert entry["query"] == "q"


def test_watch_new_second_run_empty(store):
    ss.watch_new("w1", "q", ["a", "b"])
    assert ss.watch_new("w1", "q", ["a", "b"]) == []


def test_watch_new_partial(store):
    ss.watch_new("w1", "q", ["a", "b"])
    new = ss.watch_new("w1", "q", ["b", "c", "d"])
    assert new == ["c", "d"]
    assert ss.get_watch("w1")["seen"] == ["a", "b", "c", "d"]
    assert ss.watch_new("w1", "q", ["a", "b", "c", "d"]) == []


def test_watch_new_first_run_empty_refs(store):
    assert ss.watch_new("w1", "q", []) == []
    assert ss.get_watch("w1")["seen"] == []


def test_watch_new_updates_query(store):
    ss.record_watch("w1", "old", ["a"])
    ss.watch_new("w1", "new", ["a"])
    assert ss.get_watch("w1")["query"] == "new"


def test_watch_name_validation(store):
    with pytest.raises(SearchStoreError):
        ss.record_watch("bad name!", "q", [])
    with pytest.raises(SearchStoreError):
        ss.watch_new("bad name!", "q", [])
    with pytest.raises(SearchStoreError):
        ss.record_watch("ok", "  ", [])


def test_list_watches(store):
    ss.record_watch("w1", "q1", ["a", "b"])
    ss.record_watch("w2", "q2", [])
    watches = ss.list_watches()
    assert set(watches) == {"w1", "w2"}
    assert watches["w1"]["query"] == "q1"
    assert watches["w1"]["seen_count"] == 2
    assert watches["w2"]["seen_count"] == 0
    assert watches["w1"]["last_run"]


def test_list_watches_empty(store):
    assert ss.list_watches() == {}


# --- corruption & atomicity ---------------------------------------------------


def test_corrupt_saved_raises(store, tmp_path):
    (tmp_path / "saved_searches.json").write_text("{not json")
    with pytest.raises(SearchStoreError) as exc:
        ss.list_saved()
    msg = str(exc.value)
    assert "saved_searches.json" in msg
    assert "delete" in msg.lower()


def test_corrupt_watch_raises(store, tmp_path):
    (tmp_path / "search_watch.json").write_text("[1,2]")
    with pytest.raises(SearchStoreError) as exc:
        ss.get_watch("x")
    assert "search_watch.json" in str(exc.value)


def test_corrupt_history_raises(store, tmp_path):
    (tmp_path / "search_history.jsonl").write_text('{"query": "ok"}\n{bad}\n')
    with pytest.raises(SearchStoreError) as exc:
        ss.get_history()
    assert "search_history.jsonl" in str(exc.value)


def test_atomic_write_no_temp_files(store, tmp_path):
    ss.save_search("a", "q")
    ss.log_query("q")
    ss.record_watch("w", "q", ["a"])
    temps = list(tmp_path.glob("*.tmp"))
    assert temps == []

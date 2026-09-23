"""Tests for candid.apply_state."""

import json
import re
from pathlib import Path

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    # apply_state reads config.DATA_DIR via the config module at call time,
    # so patching the attribute is enough; never evict candid modules from
    # sys.modules (that would permanently repoint DATA_DIR for later tests).
    from candid import apply_state, config

    data_dir = Path(tmp_path) / "candid_data"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    return apply_state.Store()


def test_transition_history_ordering(store, tmp_path):
    from candid import apply_state

    store.transition("job-1", "filling", note="started")
    store.transition("job-1", "ready_for_review", note="form done")
    data = store.load("job-1")

    assert data["state"] == "ready_for_review"
    hist = data["history"]
    assert len(hist) == 2
    assert [(h["from"], h["to"], h["note"]) for h in hist] == [
        ("new", "filling", "started"),
        ("filling", "ready_for_review", "form done"),
    ]
    assert "updated_at" in data
    assert all("at" in h for h in hist)

    # persisted on disk where the spec says: <root>/state/<job_id>.json
    p = store.root / "state" / "job-1.json"
    assert p.exists()
    assert json.loads(p.read_text())["state"] == "ready_for_review"
    assert apply_state.STATES == (
        "new", "filling", "needs_input", "ready_for_review", "approved",
        "submitting", "submitted", "blocked", "failed",
    )


def test_load_unknown_job_returns_new(store):
    data = store.load("never-seen")
    assert data == {"job_id": "never-seen", "state": "new", "history": []}


def test_invalid_state_raises(store):
    with pytest.raises(ValueError, match="unknown state"):
        store.transition("job-1", "launched")


def test_run_dir_path_shape(store, tmp_path):
    d = store.run_dir("job-2")
    assert d.is_dir()
    rel = d.relative_to(tmp_path / "candid_data")
    assert rel.parts[0] == "runs"
    assert rel.parts[1] == "job-2"
    assert re.fullmatch(r"\d{8}_\d{6}", rel.parts[2]), rel.parts[2]


def test_job_id_sanitization(store):
    from candid import apply_state

    nasty = "weird/job:id?x"
    store.transition(nasty, "filling")
    assert apply_state.sanitize_job_id(nasty) == "weird_job_id_x"
    assert (store.root / "state" / "weird_job_id_x.json").exists()
    # sanitized job id must not create nested directories
    assert not (store.root / "state" / "weird").exists()

    d = store.run_dir(nasty)
    assert d.parent.name == "weird_job_id_x"

"""Tests for sync history and status: candid.sync.history.

Hermetic: DATA_DIR/CONFIG_DIR are pointed at throwaway tmp dirs before
candid is imported, and each test rebinds DATA_DIR to its own tmp_path.
"""

from __future__ import annotations

import json
import os

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-sync-d"
os.environ["CANDID_CONFIG_DIR"] = "/tmp/candid-test-sync-d-config"

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

import candid.config  # noqa: E402

candid.config.DATA_DIR = Path(os.environ["CANDID_DATA_DIR"])
candid.config.CONFIG_DIR = Path(os.environ["CANDID_CONFIG_DIR"])

from candid.sync import base, history  # noqa: E402
from candid.sync.errors import SyncError  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_config():
    """Save/restore config dirs around each test (other fixtures rebind)."""
    old_data, old_cfg = candid.config.DATA_DIR, candid.config.CONFIG_DIR
    yield
    candid.config.DATA_DIR, candid.config.CONFIG_DIR = old_data, old_cfg


@pytest.fixture()
def data_dir(tmp_path):
    """Fresh per-test data dir."""
    d = tmp_path / "data"
    d.mkdir()
    candid.config.DATA_DIR = d
    return d


def _sync_dir(data_dir: Path) -> Path:
    d = data_dir / "sync"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_log_sync_appends_entry(data_dir):
    """log_sync writes one JSON line and returns the entry."""
    entry = history.log_sync(
        "export",
        "m-peer",
        "candid-sync-delta-m-1.zip",
        {"applied": ["a", "b"], "deleted": ["c"], "note": "ok", "big": [1] * 500},
    )

    assert entry["direction"] == "export"
    assert entry["peer_id"] == "m-peer"
    assert entry["bundle_name"] == "candid-sync-delta-m-1.zip"
    assert entry["machine_id"]
    assert entry["timestamp"]
    # result reduced to a small summary: lists become counts, scalars kept,
    # and anything else is dropped
    assert entry["result"] == {"applied": 2, "deleted": 1, "note": "ok"}

    lines = (data_dir / "sync" / "history.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["bundle_name"] == "candid-sync-delta-m-1.zip"


def test_log_sync_rejects_bad_direction(data_dir):
    """Directions outside {"export", "import"} raise SyncError."""
    with pytest.raises(SyncError):
        history.log_sync("sideways", None, "b.zip", {})
    assert not (data_dir / "sync" / "history.jsonl").exists()


def test_get_log_newest_first_and_limit(data_dir):
    """get_log returns most-recent-first and honors limit."""
    for i in range(3):
        history.log_sync("export", None, f"b{i}.zip", {})

    log = history.get_log()
    assert [e["bundle_name"] for e in log] == ["b2.zip", "b1.zip", "b0.zip"]
    assert [e["bundle_name"] for e in history.get_log(limit=2)] == [
        "b2.zip",
        "b1.zip",
    ]
    assert history.get_log(limit=0) == []


def test_get_log_empty(data_dir):
    """No history file yet means an empty log."""
    assert history.get_log() == []


def test_get_status_shape_defaults(data_dir):
    """Status has every required key with sane empty-state defaults."""
    status = history.get_status()

    assert set(status) == {
        "machine_id",
        "last_export",
        "last_import",
        "pending_conflicts",
        "bases",
        "peers",
    }
    assert isinstance(status["machine_id"], str) and status["machine_id"]
    assert status["last_export"] is None
    assert status["last_import"] is None
    assert status["pending_conflicts"] == 0
    assert status["bases"] == []
    assert status["peers"] == {}


def test_get_status_last_export_and_import(data_dir):
    """Status surfaces the newest export and import entries."""
    history.log_sync("export", "m-a", "e1.zip", {})
    history.log_sync("import", "m-a", "i1.zip", {})
    history.log_sync("export", "m-b", "e2.zip", {})

    status = history.get_status()

    assert status["last_export"]["bundle_name"] == "e2.zip"
    assert status["last_export"]["peer_id"] == "m-b"
    assert status["last_import"]["bundle_name"] == "i1.zip"


def test_get_status_pending_conflicts_list_and_dict(data_dir):
    """Conflict count reads sync/conflicts.json as list or dict."""
    sync = _sync_dir(data_dir)

    (sync / "conflicts.json").write_text(
        json.dumps([{"rel": "a"}, {"rel": "b"}]), encoding="utf-8"
    )
    assert history.get_status()["pending_conflicts"] == 2

    (sync / "conflicts.json").write_text(
        json.dumps({"conflicts": [{"rel": "a"}]}), encoding="utf-8"
    )
    assert history.get_status()["pending_conflicts"] == 1


def test_get_status_bases_and_peers(data_dir):
    """Status lists base snapshots and passes the peer registry through."""
    base.update_last({"tracker.json": "abc"})
    sync = _sync_dir(data_dir)
    peers = {"m-peer": {"name": "laptop", "last_seen": "2026-09-22"}}
    (sync / "peers.json").write_text(json.dumps(peers), encoding="utf-8")

    status = history.get_status()

    assert "last" in status["bases"]
    assert status["peers"] == peers

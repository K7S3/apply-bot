"""Tests for candid.sync.merge (three-way merge engine)."""

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-sync-c"
os.environ["CANDID_CONFIG_DIR"] = "/tmp/candid-test-sync-c-config"

import pytest

from candid import config
from candid.sync import base as base_mod
from candid.sync import conflicts as conflicts_mod
from candid.sync import manifest as manifest_mod
from candid.sync import merge as merge_mod
from candid.sync.errors import SyncError


@pytest.fixture(autouse=True)
def clean_dirs():
    for var in ("CANDID_DATA_DIR", "CANDID_CONFIG_DIR"):
        root = Path(os.environ[var])
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
    yield


def data_path(rel: str) -> Path:
    return Path(config.DATA_DIR) / rel


def write_data(rel: str, content: bytes) -> Path:
    p = data_path(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def make_bundle(files: dict[str, bytes], machine_id: str = "m-remote") -> Path:
    tmpdir = Path(tempfile.mkdtemp(prefix="candid-test-bundle-"))
    metas = {
        rel: {"sha256": sha(data), "size": len(data)} for rel, data in files.items()
    }
    man = manifest_mod.build_manifest(
        machine_id=machine_id, files=metas, categories=["tracker"]
    )
    zpath = tmpdir / "test-bundle.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        for rel, data in files.items():
            zf.writestr(rel, data)
        zf.writestr(manifest_mod.MANIFEST_NAME, manifest_mod.write_manifest(man))
    return zpath


def set_last_base(files: dict[str, bytes]) -> None:
    base_mod.save_base("last", {rel: sha(data) for rel, data in files.items()})


def test_classify_file_all_outcomes():
    h0, h1, h2 = "a" * 64, "b" * 64, "c" * 64
    assert merge_mod.classify_file("f", h0, h0, h0) == "unchanged"
    assert merge_mod.classify_file("f", None, None, None) == "unchanged"
    assert merge_mod.classify_file("f", h0, h1, h0) == "local-only"
    assert merge_mod.classify_file("f", None, h1, None) == "local-only"
    assert merge_mod.classify_file("f", h0, h0, h1) == "remote-only"
    assert merge_mod.classify_file("f", None, None, h1) == "remote-only"
    assert merge_mod.classify_file("f", h0, h1, h1) == "both-same"
    assert merge_mod.classify_file("f", h0, None, None) == "both-same"
    assert merge_mod.classify_file("f", h0, h1, h2) == "conflict"
    assert merge_mod.classify_file("f", h0, None, h1) == "conflict"
    assert merge_mod.classify_file("f", None, h1, h2) == "conflict"


def test_remote_only_is_applied():
    base_bytes = b'{"stage": "base"}'
    remote_bytes = b'{"stage": "remote"}'
    write_data("profile.json", base_bytes)
    set_last_base({"profile.json": base_bytes})
    bundle = make_bundle({"profile.json": remote_bytes})

    result = merge_mod.merge_bundle(bundle)

    assert result["conflicts"] == []
    assert result["applied"] == ["profile.json"]
    assert data_path("profile.json").read_bytes() == remote_bytes


def test_local_only_is_preserved():
    base_bytes = b'{"stage": "base"}'
    local_bytes = b'{"stage": "local"}'
    write_data("profile.json", local_bytes)
    set_last_base({"profile.json": base_bytes})
    bundle = make_bundle({"profile.json": base_bytes})

    result = merge_mod.merge_bundle(bundle)

    assert result["conflicts"] == []
    assert result["applied"] == []
    assert data_path("profile.json").read_bytes() == local_bytes


def test_disjoint_record_changes_merge():
    base_records = [
        {"id": "a", "company": "Acme", "status": "applied"},
        {"id": "b", "company": "Beta", "status": "applied"},
    ]
    base_bytes = json.dumps(base_records).encode()
    local_records = base_records + [{"id": "c", "company": "Gamma", "status": "applied"}]
    remote_records = base_records + [{"id": "d", "company": "Delta", "status": "applied"}]
    write_data("tracker.json", json.dumps(local_records).encode())
    set_last_base({"tracker.json": base_bytes})
    bundle = make_bundle({"tracker.json": json.dumps(remote_records).encode()})

    result = merge_mod.merge_bundle(bundle)

    assert result["conflicts"] == []
    assert result["applied"] == ["tracker.json"]
    merged = json.loads(data_path("tracker.json").read_text())
    assert [r["id"] for r in merged] == ["a", "b", "c", "d"]


def test_disjoint_record_changes_merge_with_wrapper():
    base_doc = {"applications": [{"id": "a", "status": "applied"}]}
    base_bytes = json.dumps(base_doc).encode()
    local_doc = {"applications": [{"id": "a", "status": "interview"}]}
    remote_doc = {
        "applications": [
            {"id": "a", "status": "applied"},
            {"id": "b", "status": "applied"},
        ]
    }
    # NOTE: record "a" differs between local and remote here, so this is a
    # same-record conflict; the remote-only addition "b" still merges in.
    write_data("tracker.json", json.dumps(local_doc).encode())
    set_last_base({"tracker.json": base_bytes})
    bundle = make_bundle({"tracker.json": json.dumps(remote_doc).encode()})

    result = merge_mod.merge_bundle(bundle)

    assert len(result["conflicts"]) == 1
    assert result["conflicts"][0]["record_id"] == "a"
    merged = json.loads(data_path("tracker.json").read_text())
    assert isinstance(merged, dict) and "applications" in merged
    by_id = {r["id"]: r for r in merged["applications"]}
    assert by_id["b"]["status"] == "applied"  # remote addition merged in
    assert by_id["a"]["status"] == "interview"  # local version kept pending


def test_same_record_change_becomes_conflict():
    base_records = [{"id": "a", "company": "Acme", "status": "applied"}]
    base_bytes = json.dumps(base_records).encode()
    local_records = [{"id": "a", "company": "Acme", "status": "interview"}]
    remote_records = [{"id": "a", "company": "Acme", "status": "offer"}]
    write_data("tracker.json", json.dumps(local_records).encode())
    set_last_base({"tracker.json": base_bytes})
    bundle = make_bundle({"tracker.json": json.dumps(remote_records).encode()})

    result = merge_mod.merge_bundle(bundle)

    assert result["applied"] == []
    assert len(result["conflicts"]) == 1
    c = result["conflicts"][0]
    assert c["kind"] == "record"
    assert c["path"] == "tracker.json"
    assert c["record_id"] == "a"
    assert c["local"]["status"] == "interview"
    assert c["remote"]["status"] == "offer"
    # persisted to the pending list
    pending = conflicts_mod.list_conflicts()
    assert len(pending) == 1
    assert pending[0]["record_id"] == "a"
    # local version stays in the file until resolved
    kept = json.loads(data_path("tracker.json").read_text())
    assert kept[0]["status"] == "interview"


def test_binary_file_conflict_stores_hashes():
    base_bytes, local_bytes, remote_bytes = b"base-db", b"local-db", b"remote-db"
    write_data("salary.db", local_bytes)
    set_last_base({"salary.db": base_bytes})
    bundle = make_bundle({"salary.db": remote_bytes})

    result = merge_mod.merge_bundle(bundle)

    assert len(result["conflicts"]) == 1
    c = result["conflicts"][0]
    assert c["kind"] == "file"
    assert c["path"] == "salary.db"
    assert c["local"]["sha256"] == sha(local_bytes)
    assert c["remote"]["sha256"] == sha(remote_bytes)
    assert c["base"] == sha(base_bytes)
    assert c["remote_stash"]
    # raw bytes are stashed, not embedded in the JSON
    raw = json.dumps(conflicts_mod.list_conflicts())
    assert "remote-db" not in raw


def test_missing_base_raises_sync_error():
    write_data("profile.json", b"{}")
    bundle = make_bundle({"profile.json": b'{"a": 1}'})
    with pytest.raises(SyncError):
        merge_mod.merge_bundle(bundle, base_id="no-such-base")


def test_unknown_strategy_raises_sync_error():
    write_data("profile.json", b"{}")
    set_last_base({"profile.json": b"{}"})
    bundle = make_bundle({"profile.json": b"{}"})
    with pytest.raises(SyncError):
        merge_mod.merge_bundle(bundle, strategy="theirs")


def test_clean_merge_updates_last_base():
    base_bytes = b'{"stage": "base"}'
    remote_bytes = b'{"stage": "remote"}'
    write_data("profile.json", base_bytes)
    set_last_base({"profile.json": base_bytes})
    bundle = make_bundle({"profile.json": remote_bytes})

    result = merge_mod.merge_bundle(bundle)

    assert result["conflicts"] == []
    assert result["new_base_id"]
    assert base_mod.load_base("last")["profile.json"] == sha(remote_bytes)


def test_conflicted_merge_does_not_update_last_base():
    base_bytes = b"base-db"
    write_data("salary.db", b"local-db")
    set_last_base({"salary.db": base_bytes})
    old_last = base_mod.load_base("last")
    bundle = make_bundle({"salary.db": b"remote-db"})

    result = merge_mod.merge_bundle(bundle)

    assert result["conflicts"]
    assert result["new_base_id"] is None
    assert base_mod.load_base("last") == old_last

"""Tests for candid.sync.conflicts (conflict listing and resolution)."""

import hashlib
import json
import os
import shutil
import tempfile
import time
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


def seed_record_conflicts():
    """Two conflicting tracker records with usable updated_at timestamps."""
    base_records = [
        {"id": "a", "company": "Acme", "status": "applied",
         "updated_at": "2026-09-18T10:00:00"},
        {"id": "b", "company": "Beta", "status": "applied",
         "updated_at": "2026-09-18T10:00:00"},
    ]
    write_data(
        "tracker.json",
        json.dumps(
            [
                {"id": "a", "company": "Acme", "status": "interview",
                 "updated_at": "2026-09-20T10:00:00"},
                {"id": "b", "company": "Beta", "status": "offer",
                 "updated_at": "2026-09-22T10:00:00"},
            ]
        ).encode(),
    )
    base_mod.save_base("last", {"tracker.json": sha(json.dumps(base_records).encode())})
    bundle = make_bundle(
        {
            "tracker.json": json.dumps(
                [
                    {"id": "a", "company": "Acme", "status": "offer",
                     "updated_at": "2026-09-22T10:00:00"},
                    {"id": "b", "company": "Beta", "status": "rejected",
                     "updated_at": "2026-09-20T10:00:00"},
                ]
            ).encode()
        }
    )
    return merge_mod.merge_bundle(bundle)


def tracker_by_id():
    return {r["id"]: r for r in json.loads(data_path("tracker.json").read_text())}


def test_list_and_get_conflicts():
    result = seed_record_conflicts()
    assert len(result["conflicts"]) == 2

    pending = conflicts_mod.list_conflicts()
    assert len(pending) == 2
    assert pending[0]["kind"] == "record"

    by_index = conflicts_mod.get_conflict(0)
    assert by_index["record_id"] == pending[0]["record_id"]

    by_record_id = conflicts_mod.get_conflict("b")
    assert by_record_id["record_id"] == "b"

    by_id = conflicts_mod.get_conflict(pending[1]["id"])
    assert by_id["record_id"] == "b"


def test_get_unknown_ref_raises():
    seed_record_conflicts()
    with pytest.raises(SyncError):
        conflicts_mod.get_conflict(99)
    with pytest.raises(SyncError):
        conflicts_mod.get_conflict("no-such-record")


def test_resolve_record_conflict_remote():
    seed_record_conflicts()

    done = conflicts_mod.resolve_conflict("a", "remote")

    assert done["winner"] == "remote"
    assert done["choice"] == "remote"
    assert tracker_by_id()["a"]["status"] == "offer"
    assert len(conflicts_mod.list_conflicts()) == 1


def test_resolve_record_conflict_local():
    seed_record_conflicts()

    done = conflicts_mod.resolve_conflict("a", "local")

    assert done["winner"] == "local"
    assert tracker_by_id()["a"]["status"] == "interview"
    assert len(conflicts_mod.list_conflicts()) == 1


def test_resolve_newer_picks_later_timestamp():
    seed_record_conflicts()
    # record a: remote (09-22) is newer than local (09-20)
    done = conflicts_mod.resolve_conflict("a", "newer")
    assert done["winner"] == "remote"
    assert tracker_by_id()["a"]["status"] == "offer"


def test_resolve_newer_can_pick_local():
    seed_record_conflicts()
    # record b: local (09-22) is newer than remote (09-20)
    done = conflicts_mod.resolve_conflict("b", "newer")
    assert done["winner"] == "local"
    assert tracker_by_id()["b"]["status"] == "offer"


def test_resolve_older():
    seed_record_conflicts()
    # record a: local (09-20) is older than remote (09-22)
    done = conflicts_mod.resolve_conflict("a", "older")
    assert done["winner"] == "local"
    assert tracker_by_id()["a"]["status"] == "interview"


def test_resolve_unknown_choice_raises():
    seed_record_conflicts()
    with pytest.raises(SyncError):
        conflicts_mod.resolve_conflict("a", "theirs")
    assert len(conflicts_mod.list_conflicts()) == 2  # untouched


def test_resolve_binary_file_conflict_remote_copies_whole_file():
    local_bytes, remote_bytes = b"local-db-bytes", b"remote-db-bytes"
    write_data("salary.db", local_bytes)
    base_mod.save_base("last", {"salary.db": sha(b"base-db-bytes")})
    bundle = make_bundle({"salary.db": remote_bytes})

    result = merge_mod.merge_bundle(bundle)
    assert len(result["conflicts"]) == 1

    done = conflicts_mod.resolve_conflict(0, "remote")

    assert done["winner"] == "remote"
    assert done["kind"] == "file"
    assert data_path("salary.db").read_bytes() == remote_bytes
    assert conflicts_mod.list_conflicts() == []


def test_resolve_binary_file_conflict_local_keeps_file():
    local_bytes = b"local-db-bytes"
    write_data("salary.db", local_bytes)
    base_mod.save_base("last", {"salary.db": sha(b"base-db-bytes")})
    bundle = make_bundle({"salary.db": b"remote-db-bytes"})
    merge_mod.merge_bundle(bundle)

    done = conflicts_mod.resolve_conflict(0, "local")

    assert done["winner"] == "local"
    assert data_path("salary.db").read_bytes() == local_bytes
    assert conflicts_mod.list_conflicts() == []


def test_resolve_newer_falls_back_to_bundle_created_at_vs_mtime():
    local_doc = {"name": "Keshavan"}  # no timestamp fields
    remote_doc = {"name": "Sree"}
    local_path = write_data("profile.json", json.dumps(local_doc).encode())
    base_mod.save_base("last", {"profile.json": sha(b'{"name": "base"}')})
    bundle = make_bundle({"profile.json": json.dumps(remote_doc).encode()})
    # make the local file clearly older than the just-created bundle
    old = time.time() - 86400 * 30
    os.utime(local_path, (old, old))

    result = merge_mod.merge_bundle(bundle)
    assert len(result["conflicts"]) == 1
    assert result["conflicts"][0]["kind"] == "file"

    done = conflicts_mod.resolve_conflict(0, "newer")

    assert done["winner"] == "remote"
    assert json.loads(data_path("profile.json").read_text()) == remote_doc
    assert conflicts_mod.list_conflicts() == []


def test_conflicts_are_json_serializable():
    seed_record_conflicts()
    write_data("salary.db", b"local-db")
    base_mod.save_base("last", {"salary.db": sha(b"base-db")})
    merge_mod.merge_bundle(make_bundle({"salary.db": b"remote-db"}))
    # must not raise
    json.dumps(conflicts_mod.list_conflicts())

"""Tests for candid.sync.importer (batch-74 worker B).

Env is set BEFORE importing candid, since candid.config reads it at import.
Bundles are built by hand with zipfile + manifest.build_manifest so the
tests do not depend on worker A's exporter module.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import zipfile
from pathlib import Path

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-sync-b"
os.environ["CANDID_CONFIG_DIR"] = "/tmp/candid-test-sync-b-config"

import pytest

from candid import config
from candid.sync import importer, manifest
from candid.sync.base import load_base
from candid.sync.errors import SyncError
from candid.sync.machine import get_machine_id

DATA = Path(config.DATA_DIR)
MACHINE = get_machine_id()
BUNDLE_NO = 0


def _fresh_data_dir() -> None:
    if DATA.exists():
        shutil.rmtree(DATA)
    DATA.mkdir(parents=True)


def _make_bundle(
    files: dict[str, bytes],
    *,
    peer_id: str | None = None,
    machine_id: str = "m-export-1",
    tamper_manifest=None,
    include_manifest: bool = True,
    manifest_text: str | None = None,
) -> Path:
    """Build a sync bundle zip by hand, returning its path."""
    global BUNDLE_NO
    BUNDLE_NO += 1
    bundle_dir = DATA / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    path = bundle_dir / f"bundle-{BUNDLE_NO}.zip"
    metas = {
        rel: {"sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}
        for rel, content in files.items()
    }
    m = manifest.build_manifest(
        machine_id=machine_id, files=metas, categories=["tracker"]
    )
    if peer_id is not None:
        m["peer_id"] = peer_id
    if tamper_manifest is not None:
        tamper_manifest(m)
    with zipfile.ZipFile(path, "w") as zf:
        for rel, content in files.items():
            zf.writestr(rel, content)
        if include_manifest:
            zf.writestr(
                manifest.MANIFEST_NAME,
                manifest_text if manifest_text is not None
                else manifest.write_manifest(m),
            )
    return path


def _write_local(rel: str, content: bytes) -> Path:
    p = DATA / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


def _tree_snapshot() -> dict[str, str]:
    return {
        p.relative_to(DATA).as_posix(): manifest.sha256_file(p)
        for p in sorted(DATA.rglob("*"))
        if p.is_file()
    }


@pytest.fixture(autouse=True)
def clean_data():
    _fresh_data_dir()
    yield


def test_preview_reports_new_changed_unchanged_and_writes_nothing():
    _write_local("tracker.json", b'{"old": true}')
    _write_local("offers.json", b'{"same": 1}')
    bundle = _make_bundle(
        {
            "tracker.json": b'{"new": true}',  # changed
            "offers.json": b'{"same": 1}',  # unchanged
            "prep.json": b'{"added": 1}',  # new
        }
    )
    before = _tree_snapshot()
    result = importer.preview_import(bundle)

    assert result["machine_id"] == "m-export-1"
    assert result["created_at"]
    assert result["categories"] == ["tracker"]
    assert result["files"] == [
        {"path": "offers.json", "status": "unchanged"},
        {"path": "prep.json", "status": "new"},
        {"path": "tracker.json", "status": "changed"},
    ]
    assert _tree_snapshot() == before  # dry-run writes nothing


def test_preview_not_a_bundle_raises():
    path = DATA / "plain.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("random.txt", b"no manifest here")
    with pytest.raises(SyncError):
        importer.preview_import(path)


def test_preview_corrupt_checksum_raises():
    def tamper(m):
        m["files"]["tracker.json"]["sha256"] = "0" * 64

    bundle = _make_bundle({"tracker.json": b"{}"}, tamper_manifest=tamper)
    with pytest.raises(SyncError, match="checksum mismatch"):
        importer.preview_import(bundle)


def test_import_replace_overwrites_and_backs_up():
    old_bytes = b'{"old": true}'
    _write_local("tracker.json", old_bytes)
    bundle = _make_bundle({"tracker.json": b'{"new": true}', "prep.json": b"{}"})

    result = importer.import_bundle(bundle)

    assert result["mode"] == "replace"
    assert result["applied"] == ["prep.json", "tracker.json"]
    assert result["backed_up"] == ["tracker.json"]
    assert (DATA / "tracker.json").read_bytes() == b'{"new": true}'
    assert (DATA / "prep.json").read_bytes() == b"{}"

    backup_dirs = list((DATA / "sync" / "backups").iterdir())
    assert len(backup_dirs) == 1
    assert (backup_dirs[0] / "tracker.json").read_bytes() == old_bytes


def test_import_replace_new_only_backs_up_nothing():
    bundle = _make_bundle({"prep.json": b"{}"})
    result = importer.import_bundle(bundle)
    assert result["applied"] == ["prep.json"]
    assert result["backed_up"] == []
    assert not (DATA / "sync" / "backups").exists()


def test_import_replace_updates_last_base():
    _write_local("tracker.json", b'{"old": true}')
    bundle = _make_bundle({"tracker.json": b'{"new": true}'})
    importer.import_bundle(bundle)
    last = load_base("last")
    assert last["tracker.json"] == manifest.sha256_file(DATA / "tracker.json")


def test_verify_bundle_file_ok():
    bundle = _make_bundle(
        {"tracker.json": b"{}", "offers.json": b"{}"}, machine_id="m-export-9"
    )
    result = importer.verify_bundle_file(bundle)
    assert result == {"ok": True, "files": 2, "machine_id": "m-export-9"}


def test_verify_corrupt_checksum_raises():
    def tamper(m):
        m["files"]["tracker.json"]["sha256"] = "f" * 64

    bundle = _make_bundle({"tracker.json": b"{}"}, tamper_manifest=tamper)
    with pytest.raises(SyncError, match="checksum mismatch"):
        importer.verify_bundle_file(bundle)


def test_verify_not_a_bundle_raises():
    path = DATA / "notes.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("notes.txt", b"just notes")
    with pytest.raises(SyncError, match="not a candid sync bundle"):
        importer.verify_bundle_file(path)


def test_verify_not_a_zip_raises():
    path = DATA / "fake.zip"
    path.write_bytes(b"this is not a zip file")
    with pytest.raises(SyncError, match="not a valid zip file"):
        importer.verify_bundle_file(path)


def test_verify_corrupt_manifest_raises():
    bundle = _make_bundle({"tracker.json": b"{}"}, manifest_text="{not json")
    with pytest.raises(SyncError, match="corrupt manifest"):
        importer.verify_bundle_file(bundle)


def test_peer_targeted_bundle_for_other_machine_refused():
    _write_local("tracker.json", b'{"old": true}')
    bundle = _make_bundle({"tracker.json": b'{"new": true}'}, peer_id="m-someone-else")
    with pytest.raises(SyncError, match="addressed to another machine"):
        importer.import_bundle(bundle)
    assert (DATA / "tracker.json").read_bytes() == b'{"old": true}'


def test_peer_targeted_bundle_for_us_is_accepted():
    bundle = _make_bundle({"tracker.json": b'{"new": true}'}, peer_id=MACHINE)
    result = importer.import_bundle(bundle)
    assert result["applied"] == ["tracker.json"]
    assert (DATA / "tracker.json").read_bytes() == b'{"new": true}'


def test_merge_mode_without_engine_raises_friendly_error():
    bundle = _make_bundle({"tracker.json": b"{}"})
    with pytest.raises(SyncError, match="merge engine not available in this build"):
        importer.import_bundle(bundle, mode="merge")


def test_unknown_mode_raises():
    bundle = _make_bundle({"tracker.json": b"{}"})
    with pytest.raises(SyncError, match="unknown import mode"):
        importer.import_bundle(bundle, mode="fancy")

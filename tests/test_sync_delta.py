"""Tests for incremental (delta) sync bundles: candid.sync.delta.

Hermetic: DATA_DIR/CONFIG_DIR are pointed at throwaway tmp dirs before
candid is imported, and each test rebinds DATA_DIR to its own tmp_path.
"""

from __future__ import annotations

import os
import zipfile

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-sync-d"
os.environ["CANDID_CONFIG_DIR"] = "/tmp/candid-test-sync-d-config"

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

import candid.config  # noqa: E402

candid.config.DATA_DIR = Path(os.environ["CANDID_DATA_DIR"])
candid.config.CONFIG_DIR = Path(os.environ["CANDID_CONFIG_DIR"])

from candid.sync import base, delta  # noqa: E402
from candid.sync.errors import SyncError  # noqa: E402
from candid.sync.manifest import (  # noqa: E402
    MANIFEST_NAME,
    build_manifest,
    read_manifest,
    sha256_file,
    verify_bundle,
    write_manifest,
)


@pytest.fixture(autouse=True)
def _restore_config():
    """Save/restore config dirs around each test (other fixtures rebind)."""
    old_data, old_cfg = candid.config.DATA_DIR, candid.config.CONFIG_DIR
    yield
    candid.config.DATA_DIR, candid.config.CONFIG_DIR = old_data, old_cfg


@pytest.fixture()
def src(tmp_path):
    """Exporter machine data dir, rebased to a snapshot of its content."""
    d = tmp_path / "src"
    d.mkdir()
    candid.config.DATA_DIR = d
    (d / "tracker.json").write_text('{"v": 1}', encoding="utf-8")
    (d / "profile.json").write_text('{"name": "k"}', encoding="utf-8")
    (d / "prep_packs").mkdir()
    (d / "prep_packs" / "old.md").write_text("old", encoding="utf-8")
    base.update_last(base.snapshot_current())
    return d


@pytest.fixture()
def dst(tmp_path):
    """Importer machine data dir holding the same original content."""
    d = tmp_path / "dst"
    d.mkdir()
    (d / "tracker.json").write_text('{"v": 1}', encoding="utf-8")
    (d / "profile.json").write_text('{"name": "k"}', encoding="utf-8")
    (d / "prep_packs").mkdir()
    (d / "prep_packs" / "old.md").write_text("old", encoding="utf-8")
    return d


def _rebind(data_dir: Path) -> None:
    candid.config.DATA_DIR = data_dir


def test_export_delta_contains_only_changed_files(src, tmp_path):
    """Only changed/new files land in the bundle and its manifest."""
    (src / "tracker.json").write_text('{"v": 2}', encoding="utf-8")
    (src / "prep_packs" / "new.md").write_text("new", encoding="utf-8")

    bundle = delta.export_delta(tmp_path / "out")

    assert bundle.name.startswith("candid-sync-delta-")
    assert bundle.suffix == ".zip"
    manifest = verify_bundle(bundle)
    assert manifest["incremental"] is True
    assert manifest["base_id"] == "last"
    assert set(manifest["files"]) == {"tracker.json", "prep_packs/new.md"}
    assert manifest["deleted"] == []
    with zipfile.ZipFile(bundle) as zf:
        assert set(zf.namelist()) == {
            MANIFEST_NAME,
            "tracker.json",
            "prep_packs/new.md",
        }


def test_export_delta_empty_diff_is_valid(src, tmp_path):
    """No changes still yields a valid, verifiable bundle with zero files."""
    bundle = delta.export_delta(tmp_path / "out")

    manifest = verify_bundle(bundle)
    assert manifest["files"] == {}
    assert manifest["deleted"] == []
    assert manifest["incremental"] is True

    _rebind(tmp_path / "peer")
    (tmp_path / "peer").mkdir()
    base.update_last({})
    result = delta.apply_delta(bundle)
    assert result == {"applied": [], "deleted": []}


def test_export_delta_explicit_file_path(src, tmp_path):
    """An explicit .zip target is used verbatim instead of auto-naming."""
    target = tmp_path / "custom" / "my-delta.zip"
    bundle = delta.export_delta(target)
    assert bundle == target
    assert target.is_file()


def test_export_delta_include_exclude(src, tmp_path):
    """include/exclude narrow which categories are diffed."""
    (src / "tracker.json").write_text('{"v": 2}', encoding="utf-8")
    (src / "profile.json").write_text('{"name": "changed"}', encoding="utf-8")

    bundle = delta.export_delta(tmp_path / "out", include=["tracker"])
    manifest = read_manifest(bundle)
    assert set(manifest["files"]) == {"tracker.json"}

    bundle = delta.export_delta(tmp_path / "out2", exclude=["tracker", "profile"])
    manifest = read_manifest(bundle)
    assert manifest["files"] == {}


def test_export_delta_records_deleted_files(src, tmp_path):
    """Files missing since the base are listed under manifest "deleted"."""
    (src / "prep_packs" / "old.md").unlink()

    bundle = delta.export_delta(tmp_path / "out")

    manifest = read_manifest(bundle)
    assert manifest["deleted"] == ["prep_packs/old.md"]
    assert manifest["files"] == {}
    with zipfile.ZipFile(bundle) as zf:
        assert set(zf.namelist()) == {MANIFEST_NAME}


def test_apply_delta_applies_changes_deletes_with_backup(src, dst, tmp_path):
    """Peer apply writes changed files, backs up then deletes doomed ones."""
    (src / "tracker.json").write_text('{"v": 2}', encoding="utf-8")
    (src / "prep_packs" / "old.md").unlink()
    bundle = delta.export_delta(tmp_path / "out")

    _rebind(dst)
    base.update_last(base.snapshot_current())

    result = delta.apply_delta(bundle)

    assert result == {
        "applied": ["tracker.json"],
        "deleted": ["prep_packs/old.md"],
    }
    assert (dst / "tracker.json").read_text(encoding="utf-8") == '{"v": 2}'
    assert not (dst / "prep_packs" / "old.md").exists()
    backups = list((dst / "sync" / "backups").iterdir())
    assert len(backups) == 1
    backup_file = backups[0] / "prep_packs" / "old.md"
    assert backup_file.is_file()
    assert backup_file.read_text(encoding="utf-8") == "old"
    # base advanced to the post-apply state
    new_base = base.load_base("last")
    assert new_base["tracker.json"] == sha256_file(dst / "tracker.json")
    assert "prep_packs/old.md" not in new_base


def test_apply_delta_base_mismatch_raises(src, tmp_path):
    """A delta built on another base is rejected with a full-bundle hint."""
    bundle = delta.export_delta(tmp_path / "out")

    with pytest.raises(SyncError) as exc_info:
        delta.apply_delta(bundle, base_id="some-other-base")

    message = str(exc_info.value)
    assert "last" in message and "some-other-base" in message
    assert "full bundle" in message


def test_apply_delta_rejects_non_incremental_bundle(tmp_path):
    """apply_delta refuses a full bundle and points at the full importer."""
    d = tmp_path / "data"
    d.mkdir()
    _rebind(d)
    (d / "tracker.json").write_text('{"v": 1}', encoding="utf-8")

    files = {
        "tracker.json": {
            "sha256": sha256_file(d / "tracker.json"),
            "size": (d / "tracker.json").stat().st_size,
        }
    }
    manifest = build_manifest(
        machine_id="m-test", files=files, categories=["tracker"]
    )
    bundle = tmp_path / "full.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, write_manifest(manifest))
        zf.write(d / "tracker.json", arcname="tracker.json")

    with pytest.raises(SyncError) as exc_info:
        delta.apply_delta(bundle)
    assert "full bundle" in str(exc_info.value)

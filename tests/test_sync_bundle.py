"""Tests for candid.sync.bundle: sync bundle export and selective sync.

Env overrides are set BEFORE importing candid modules, matching how the
other test files in this repo handle CANDID_DATA_DIR / CANDID_CONFIG_DIR.
"""

from __future__ import annotations

import os
import shutil
import zipfile

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-sync-a"
os.environ["CANDID_CONFIG_DIR"] = "/tmp/candid-test-sync-a-config"

import pytest  # noqa: E402

from candid.sync import base, categories, manifest  # noqa: E402
from candid.sync.bundle import (  # noqa: E402
    export_bundle,
    resolve_selection,
    summarize_selection,
)
from candid.sync.errors import SyncError  # noqa: E402

DATA = "/tmp/candid-test-sync-a"


@pytest.fixture(autouse=True)
def fresh_data_dir():
    shutil.rmtree(DATA, ignore_errors=True)
    os.makedirs(DATA, exist_ok=True)
    # Sample data: tracker, profile, and a prep_packs dir with nesting.
    open(f"{DATA}/tracker.json", "w").write('{"jobs": []}')
    open(f"{DATA}/profile.json", "w").write('{"name": "Keshavan"}')
    os.makedirs(f"{DATA}/prep_packs/sub", exist_ok=True)
    open(f"{DATA}/prep_packs/pack1.md", "w").write("# pack 1")
    open(f"{DATA}/prep_packs/sub/pack2.md", "w").write("# pack 2")
    yield
    # Leave the tree for the last test's introspection; next run cleans it.


def _bundle_files(bundle_path):
    with zipfile.ZipFile(bundle_path) as zf:
        return zf.namelist()


def test_export_all_creates_named_bundle_with_valid_manifest():
    out_dir = f"{DATA}/out"
    os.makedirs(out_dir, exist_ok=True)
    bundle_path = export_bundle(out_dir)
    assert bundle_path.name.startswith("candid-sync-")
    assert bundle_path.name.endswith(".zip")
    assert bundle_path.is_file()

    m = manifest.read_manifest(bundle_path)
    assert m["format"] == "candid-sync/1"
    assert set(m["categories"]) == set(categories.all_categories())
    # Files present under DATA_DIR for categories whose paths exist.
    assert "tracker.json" in m["files"]
    assert "profile.json" in m["files"]
    assert "prep_packs/pack1.md" in m["files"]
    assert "prep_packs/sub/pack2.md" in m["files"]
    # verify_bundle returns the manifest when everything checks out.
    assert manifest.verify_bundle(bundle_path)["format"] == "candid-sync/1"


def test_missing_category_paths_are_skipped_silently():
    # offers.json, salary.db, tailored/, gmail_proposals.json do not exist.
    bundle_path = export_bundle(f"{DATA}/out2.zip")
    names = _bundle_files(bundle_path)
    assert "candid-sync-manifest.json" in names
    assert "offers.json" not in names
    assert "salary.db" not in names


def test_include_filters_categories():
    bundle_path = export_bundle(f"{DATA}/inc.zip", include=["profile"])
    m = manifest.read_manifest(bundle_path)
    assert m["categories"] == ["profile"]
    assert set(m["files"]) == {"profile.json"}


def test_exclude_filters_categories():
    bundle_path = export_bundle(
        f"{DATA}/exc.zip", include=["profile", "tracker"], exclude=["tracker"]
    )
    m = manifest.read_manifest(bundle_path)
    assert set(m["files"]) == {"profile.json"}


def test_excludes_win_over_includes():
    assert resolve_selection(["profile", "tracker"], ["tracker"]) == ["profile"]


def test_unknown_category_raises_sync_error():
    with pytest.raises(SyncError):
        export_bundle(f"{DATA}/bad.zip", include=["nope"])
    with pytest.raises(SyncError):
        export_bundle(f"{DATA}/bad2.zip", exclude=["nope"])
    with pytest.raises(SyncError):
        summarize_selection(include=["nope"])


def test_default_selection_is_all_categories():
    assert resolve_selection() == categories.all_categories()
    assert resolve_selection([], []) == categories.all_categories()


def test_summarize_selection_matches_export():
    summary = summarize_selection(include=["prep", "tracker"])
    assert summary["categories"] == ["prep", "tracker"]
    assert summary["file_count"] == 3  # tracker.json + 2 prep files
    expected_bytes = sum(
        os.path.getsize(p)
        for p in (
            f"{DATA}/tracker.json",
            f"{DATA}/prep_packs/pack1.md",
            f"{DATA}/prep_packs/sub/pack2.md",
        )
    )
    assert summary["total_bytes"] == expected_bytes


def test_peer_id_recorded_in_manifest():
    bundle_path = export_bundle(f"{DATA}/peer.zip", peer_id="m-peer123")
    m = manifest.read_manifest(bundle_path)
    assert m["peer_id"] == "m-peer123"


def test_last_base_snapshot_written_after_export():
    export_bundle(f"{DATA}/base.zip", include=["tracker"])
    last = base.load_base("last")
    assert last == {
        "tracker.json": manifest.sha256_file(
            __import__("pathlib").Path(f"{DATA}/tracker.json")
        )
    }
    assert "last" in base.list_bases()

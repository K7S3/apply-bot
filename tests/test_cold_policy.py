"""Tests for candid.cold_policy — retention policies, pruning, one-shot apply.

Every test isolates state by monkeypatching ``candid.config.DATA_DIR`` to a
fresh tmp dir; cold_policy (via coldstore) resolves the data dir at call
time, so no re-import is needed.  Sibling modules (coldstore, cold_cycles,
cold_searchdata, cold_verify) are the real implementations.
"""

from __future__ import annotations

import json
import os
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from candid import cold_policy
from candid import coldstore
from candid import config as config_module


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "candid_data"
    monkeypatch.setattr(config_module, "DATA_DIR", d)
    monkeypatch.delenv("CANDID_COLD_DIR", raising=False)
    return d


# --- seeding helpers ---------------------------------------------------------

def _create(label="seed", members=None, kind="misc"):
    manifest = coldstore.create_archive(
        kind, label, members=members or {"data.txt": b"seed-data"}
    )
    return manifest["archive_id"]


def _backdate(archive_id, days_old):
    """Rewrite the manifest so the archive looks ``days_old`` days old."""
    path = coldstore.archive_root() / f"{archive_id}.zip"
    with zipfile.ZipFile(path, "a") as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        manifest["created_utc"] = (
            datetime.now(timezone.utc) - timedelta(days=days_old)
        ).isoformat()
        zf.writestr(
            "manifest.json",
            json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
        )


def _tamper_member(archive_id, member="data.txt"):
    """Append a second copy of a member with bytes that break its hash."""
    path = coldstore.archive_root() / f"{archive_id}.zip"
    with zipfile.ZipFile(path, "a") as zf:
        zf.writestr(member, b"tampered-bytes-not-matching-manifest")


def _zip_exists(archive_id):
    return (coldstore.archive_root() / f"{archive_id}.zip").is_file()


def _snapshot_tree(data_dir):
    """Full byte snapshot of the data dir (paths -> contents)."""
    snap = {}
    if data_dir.is_dir():
        for p in sorted(data_dir.rglob("*")):
            if p.is_file():
                snap[str(p.relative_to(data_dir))] = p.read_bytes()
    return snap


def _seed_stale_cycle(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    old = (datetime.now(timezone.utc) - timedelta(days=200)).date().isoformat()
    apps = [
        {
            "id": "app-1",
            "company": "Acme",
            "status": "rejected",
            "date_updated": old,
        }
    ]
    (data_dir / "tracker.json").write_text(json.dumps(apps), encoding="utf-8")


def _seed_stale_searchdata(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    jobs = data_dir / "jobs.json"
    jobs.write_text(json.dumps([{"id": "job-1"}]), encoding="utf-8")
    stale = (datetime.now(timezone.utc) - timedelta(days=60)).timestamp()
    os.utime(jobs, (stale, stale))


# --- load_policy -------------------------------------------------------------

def test_load_policy_defaults():
    assert cold_policy.load_policy() == cold_policy.DEFAULT_POLICY
    assert cold_policy.load_policy()["cycles_after_days"] == 90
    assert cold_policy.load_policy()["searchdata_after_days"] == 30
    assert cold_policy.load_policy()["prune_archives_after_days"] == 365
    assert cold_policy.load_policy()["min_archives_to_keep"] == 1


def test_load_policy_overrides_merge():
    policy = cold_policy.load_policy({"cycles_after_days": 7, "min_archives_to_keep": 0})
    assert policy["cycles_after_days"] == 7
    assert policy["min_archives_to_keep"] == 0
    assert policy["searchdata_after_days"] == 30  # untouched default
    assert cold_policy.DEFAULT_POLICY["cycles_after_days"] == 90  # not mutated


# --- prune_archives ----------------------------------------------------------

def test_prune_keeps_minimum_newest(data_dir):
    newer = _create(label="newer")
    _backdate(newer, 400)
    older = _create(label="older")
    _backdate(older, 500)

    report = cold_policy.prune_archives(older_than_days=365, keep_minimum=1)

    assert report["deleted"] == [older]
    assert report["kept"] == 1
    assert report["dry_run"] is False
    assert _zip_exists(newer)          # newest kept despite being old
    assert not _zip_exists(older)      # only the excess old one deleted


def test_prune_skips_unverified_archives(data_dir):
    fresh = _create(label="fresh")
    valid_old = _create(label="valid-old")
    _backdate(valid_old, 400)
    corrupt_old = _create(label="corrupt-old")
    _backdate(corrupt_old, 400)
    _tamper_member(corrupt_old)

    report = cold_policy.prune_archives(older_than_days=365, keep_minimum=1)

    assert report["deleted"] == [valid_old]
    assert corrupt_old in report["skipped_unverified"]
    assert report["kept"] == 2
    assert _zip_exists(corrupt_old)    # corrupt archive never deleted
    assert _zip_exists(fresh)
    assert not _zip_exists(valid_old)


def test_prune_dry_run_changes_nothing(data_dir):
    old = _create(label="old")
    _backdate(old, 400)
    before = _snapshot_tree(data_dir)

    report = cold_policy.prune_archives(
        older_than_days=365, dry_run=True, keep_minimum=0
    )

    assert report["dry_run"] is True
    assert report["deleted"] == [old]  # would-be deletion reported
    assert _zip_exists(old)
    assert _snapshot_tree(data_dir) == before


def test_prune_ignores_fresh_archives(data_dir):
    fresh = _create(label="fresh")
    report = cold_policy.prune_archives(older_than_days=365, keep_minimum=0)
    assert report["deleted"] == []
    assert report["kept"] == 1
    assert _zip_exists(fresh)


def test_prune_keep_minimum_larger_than_store(data_dir):
    old = _create(label="old")
    _backdate(old, 400)
    report = cold_policy.prune_archives(older_than_days=365, keep_minimum=5)
    assert report["deleted"] == []
    assert report["kept"] == 1
    assert _zip_exists(old)


# --- policy_report (read-only) ------------------------------------------------

def test_policy_report_is_read_only(data_dir):
    _seed_stale_cycle(data_dir)
    _seed_stale_searchdata(data_dir)
    old = _create(label="old")
    _backdate(old, 400)
    _create(label="fresh")  # newest: satisfies keep_minimum so `old` is prunable
    before = _snapshot_tree(data_dir)

    report = cold_policy.policy_report()

    assert _snapshot_tree(data_dir) == before
    assert _zip_exists(old)
    assert report["dry_run"] is True
    assert report["cycles"]["dry_run"] is True
    assert report["cycles"]["archived"] >= 1      # stale app would be archived
    assert report["searchdata"]["dry_run"] is True
    assert report["searchdata"]["files"] >= 1     # stale jobs.json compressible
    assert report["prune"]["dry_run"] is True
    assert old in report["prune"]["deleted"]      # would-be pruned
    assert report["errors"] == []


# --- apply_policies -----------------------------------------------------------

def test_apply_policies_dry_run_changes_nothing(data_dir):
    _seed_stale_cycle(data_dir)
    _seed_stale_searchdata(data_dir)
    old = _create(label="old")
    _backdate(old, 400)
    _create(label="fresh")  # newest: satisfies keep_minimum so `old` is prunable
    before = _snapshot_tree(data_dir)

    report = cold_policy.apply_policies(dry_run=True)

    assert _snapshot_tree(data_dir) == before
    assert _zip_exists(old)
    assert report["dry_run"] is True
    assert report["archive_cycles"]["dry_run"] is True
    assert report["archive_cycles"]["archived"] >= 1
    assert report["prune_archives"]["dry_run"] is True
    assert report["errors"] == []


def test_apply_policies_real_run_archives_then_prunes(data_dir):
    _seed_stale_cycle(data_dir)
    old = _create(label="old")
    _backdate(old, 400)
    policy = {
        "cycles_after_days": 90,
        "searchdata_after_days": 30,
        "prune_archives_after_days": 365,
        "min_archives_to_keep": 1,
    }

    report = cold_policy.apply_policies(policy=policy)

    assert report["errors"] == []
    assert report["dry_run"] is False
    # 1. stale cycles archived for real
    assert report["archive_cycles"]["archived"] == 1
    cycles_id = report["archive_cycles"]["archive_id"]
    assert cycles_id
    assert _zip_exists(cycles_id)
    apps = json.loads((data_dir / "tracker.json").read_text(encoding="utf-8"))
    assert apps == []  # archived app removed from the tracker
    # 2. old archive pruned afterwards; the fresh cycles archive is newest
    #    and protected by min_archives_to_keep=1
    assert old in report["prune_archives"]["deleted"]
    assert not _zip_exists(old)
    assert _zip_exists(cycles_id)


def test_apply_policies_collects_errors_without_aborting(data_dir, monkeypatch):
    import candid.cold_cycles as cycles_mod

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(cycles_mod, "archive_old_cycles", boom)

    report = cold_policy.apply_policies()

    steps = [e["step"] for e in report["errors"]]
    assert "archive_old_cycles" in steps
    assert any("boom" in e["error"] for e in report["errors"])
    # remaining steps still ran
    assert report["compress_searchdata"] is not None
    assert report["prune_archives"] is not None

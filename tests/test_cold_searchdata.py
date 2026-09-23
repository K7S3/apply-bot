"""Tests for candid.cold_searchdata.

Isolates state by monkeypatching ``candid.config.DATA_DIR`` to a fresh tmp
dir (plus ``CANDID_COLD_DIR`` unset); coldstore and cold_searchdata resolve
the data dir at call time, so no re-import is needed.
"""

from __future__ import annotations

import json
import time
import zipfile

import pytest

from candid import config as config_module
from candid import coldstore
from candid import cold_searchdata


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "candid_data"
    d.mkdir()
    monkeypatch.setattr(config_module, "DATA_DIR", d)
    monkeypatch.delenv("CANDID_COLD_DIR", raising=False)
    return d


def _make_stale(path, content=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    old = time.time() - 40 * 86400  # 40 days ago
    import os

    os.utime(path, (old, old))
    return path


# --- compress_stale_data -----------------------------------------------------

def test_dry_run_changes_nothing(data_dir):
    jobs = _make_stale(data_dir / "jobs.json", b'{"jobs": []}')
    pack = _make_stale(data_dir / "prep_packs" / "acme" / "pack.md", b"# pack")
    result = cold_searchdata.compress_stale_data(days=30, dry_run=True)
    assert result["dry_run"] is True
    assert result["archives"] == []
    assert result["files"] == 2
    assert result["bytes_saved"] > 0
    assert jobs.exists() and pack.exists()
    assert coldstore.list_archives() == []


def test_stale_jobs_archived_and_removed(data_dir):
    content = b'{"curated": [{"company": "Globex Corp"}]}'
    _make_stale(data_dir / "jobs.json", content)
    result = cold_searchdata.compress_stale_data(days=30, kinds=("jobs",))
    assert not (data_dir / "jobs.json").exists()
    assert len(result["archives"]) == 1
    assert result["files"] == 1
    assert result["dry_run"] is False

    archive_id = result["archives"][0]
    info = coldstore.read_archive(archive_id)
    assert info["kind"] == "searchdata"
    assert info["members"] == ["jobs/jobs.json"]
    assert coldstore.extract_member(archive_id, "jobs/jobs.json") == content
    assert info["payload"]["searchdata_kind"] == "jobs"


def test_fresh_files_untouched(data_dir):
    (data_dir / "jobs.json").write_text('{"curated": []}')
    fresh_pack = data_dir / "prep_packs" / "acme" / "pack.md"
    fresh_pack.parent.mkdir(parents=True, exist_ok=True)
    fresh_pack.write_text("# fresh")
    result = cold_searchdata.compress_stale_data(days=30)
    assert result["archives"] == []
    assert result["files"] == 0
    assert (data_dir / "jobs.json").exists()
    assert fresh_pack.exists()


def test_live_files_never_compressed(data_dir):
    for name in ("tracker.json", "profile.json", "offers.json"):
        _make_stale(data_dir / name, b'{"live": true}')
    result = cold_searchdata.compress_stale_data(days=30)
    for name in ("tracker.json", "profile.json", "offers.json"):
        assert (data_dir / name).exists()
    # nothing else stale existed, so no archives
    assert result["archives"] == []


def test_prep_packs_grouped_per_directory(data_dir):
    # stale dir -> archived; fresh dir -> untouched
    _make_stale(data_dir / "prep_packs" / "stale-co" / "pack.md", b"# old")
    _make_stale(data_dir / "prep_packs" / "stale-co" / "notes.txt", b"notes")
    fresh = data_dir / "prep_packs" / "fresh-co" / "pack.md"
    fresh.parent.mkdir(parents=True, exist_ok=True)
    fresh.write_text("# new")
    # mixed dir: one fresh file keeps the whole dir alive
    mixed = data_dir / "prep_packs" / "mixed-co"
    mixed.mkdir(parents=True, exist_ok=True)
    _make_stale(mixed / "old.md", b"# old")
    (mixed / "new.md").write_text("# new")

    result = cold_searchdata.compress_stale_data(days=30, kinds=("prep_packs",))
    assert len(result["archives"]) == 1
    assert result["files"] == 2
    assert not (data_dir / "prep_packs" / "stale-co").exists()
    assert fresh.exists()
    assert (mixed / "old.md").exists() and (mixed / "new.md").exists()

    archive_id = result["archives"][0]
    members = coldstore.read_archive(archive_id)["members"]
    assert sorted(members) == [
        "prep_packs/stale-co/notes.txt",
        "prep_packs/stale-co/pack.md",
    ]


def test_salary_cache_archived_but_live_db_untouched(data_dir):
    _make_stale(data_dir / "salary_cache.json", b'{"ranges": {}}')
    _make_stale(data_dir / "salary.db", b"fake-db-bytes")
    result = cold_searchdata.compress_stale_data(days=30, kinds=("salary_cache",))
    assert not (data_dir / "salary_cache.json").exists()
    assert (data_dir / "salary.db").exists()
    archive_id = result["archives"][0]
    assert coldstore.read_archive(archive_id)["members"] == [
        "salary_cache/salary_cache.json"
    ]


def test_unknown_kind_raises(data_dir):
    with pytest.raises(ValueError):
        cold_searchdata.compress_stale_data(kinds=("nope",))


# --- search_archives ----------------------------------------------------------

def _make_cycles_archive(data_dir):
    members = {
        "apps/app1.json": json.dumps(
            {"company": "Globex Corp", "role": "ML Engineer", "status": "applied"}
        ).encode(),
        "apps/app2.json": json.dumps(
            {"company": "Initech", "role": "Data Scientist", "status": "rejected"}
        ).encode(),
    }
    manifest = coldstore.create_archive("cycles", "Q3 applications", members=members)
    return manifest["archive_id"]


def test_search_archives_finds_company_in_cycles_payload(data_dir):
    archive_id = _make_cycles_archive(data_dir)
    hits = cold_searchdata.search_archives("globex")
    assert len(hits) == 1
    hit = hits[0]
    assert hit["archive_id"] == archive_id
    assert hit["kind"] == "cycles"
    assert "member:company" in hit["matched"]

    hits = cold_searchdata.search_archives("REJECTED")
    assert len(hits) == 1
    assert "member:status" in hits[0]["matched"]

    assert cold_searchdata.search_archives("no-such-company-xyz") == []


def test_search_archives_label_and_payload_hints(data_dir):
    manifest = coldstore.create_archive(
        "searchdata",
        "stale jobs backup",
        members={"jobs/jobs.json": b'{"x": 1}'},
        payload={"searchdata_kind": "jobs"},
    )
    hits = cold_searchdata.search_archives("stale jobs")
    assert len(hits) == 1
    assert "label" in hits[0]["matched"]
    hits = cold_searchdata.search_archives("searchdata_kind")
    assert len(hits) == 1
    assert "payload" in hits[0]["matched"]
    # a manifest hint triggers a deep member scan; the query text is not in
    # the member content, so no member hints appear
    hits = cold_searchdata.search_archives("backup")
    assert len(hits) == 1
    assert "label" in hits[0]["matched"]
    assert "member:jobs/jobs.json" not in hits[0]["matched"]


def test_search_archives_kinds_filter(data_dir):
    _make_cycles_archive(data_dir)
    assert cold_searchdata.search_archives("globex", kinds=("searchdata",)) == []
    assert len(cold_searchdata.search_archives("globex", kinds=("cycles",))) == 1
    assert cold_searchdata.search_archives("") == []


def test_search_archives_searchdata_content_index(data_dir):
    # archive stale jobs.json containing a company name, then find it via
    # the payload content index (manifest label alone would not match)
    _make_stale(
        data_dir / "jobs.json",
        json.dumps({"curated": [{"company": "Umbrella Health"}]}).encode(),
    )
    archive_id = cold_searchdata.compress_stale_data(kinds=("jobs",))["archives"][0]
    hits = cold_searchdata.search_archives("umbrella")
    assert len(hits) == 1
    assert hits[0]["archive_id"] == archive_id
    assert "payload" in hits[0]["matched"] or "member:company" in hits[0]["matched"]


# --- restore_searchdata --------------------------------------------------------

def test_restore_roundtrip(data_dir):
    jobs_content = b'{"curated": []}'
    pack_content = b"# pack"
    _make_stale(data_dir / "jobs.json", jobs_content)
    _make_stale(data_dir / "prep_packs" / "acme" / "pack.md", pack_content)
    archive_ids = cold_searchdata.compress_stale_data(
        kinds=("jobs", "prep_packs")
    )["archives"]
    assert len(archive_ids) == 2
    assert not (data_dir / "jobs.json").exists()

    for archive_id in archive_ids:
        dest = cold_searchdata.restore_searchdata(archive_id)
        assert dest == data_dir
    assert (data_dir / "jobs" / "jobs.json").read_bytes() == jobs_content
    assert (data_dir / "prep_packs" / "acme" / "pack.md").read_bytes() == pack_content


def test_restore_dest_override(data_dir, tmp_path):
    _make_stale(data_dir / "jobs.json", b"{}")
    archive_id = cold_searchdata.compress_stale_data(kinds=("jobs",))["archives"][0]
    alt = tmp_path / "restore-here"
    dest = cold_searchdata.restore_searchdata(archive_id, dest=alt)
    assert dest == alt
    assert (alt / "jobs" / "jobs.json").exists()
    assert not (data_dir / "jobs" / "jobs.json").exists()


def test_restore_refuses_wrong_kind(data_dir):
    archive_id = _make_cycles_archive(data_dir)
    with pytest.raises(ValueError):
        cold_searchdata.restore_searchdata(archive_id)


def test_restore_overwrite_protection(data_dir):
    _make_stale(data_dir / "jobs.json", b'{"v": 1}')
    archive_id = cold_searchdata.compress_stale_data(kinds=("jobs",))["archives"][0]
    cold_searchdata.restore_searchdata(archive_id)
    assert (data_dir / "jobs" / "jobs.json").read_bytes() == b'{"v": 1}'

    # second restore without overwrite -> refused before anything is written
    (data_dir / "jobs" / "jobs.json").write_bytes(b'{"v": 2}')
    with pytest.raises(FileExistsError):
        cold_searchdata.restore_searchdata(archive_id)
    assert (data_dir / "jobs" / "jobs.json").read_bytes() == b'{"v": 2}'

    # with overwrite=True it goes through
    cold_searchdata.restore_searchdata(archive_id, overwrite=True)
    assert (data_dir / "jobs" / "jobs.json").read_bytes() == b'{"v": 1}'


def test_restore_zip_slip_safe(data_dir):
    # hand-crafted hostile archive: coldstore.create_archive would reject
    # this member name, so build the zip directly
    bad_id = "20000101T000000-000000-searchdata-evil"
    zip_path = coldstore.archive_root() / f"{bad_id}.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps({"archive_id": bad_id, "kind": "searchdata", "label": "evil"}),
        )
        zf.writestr("../../evil.txt", b"pwned")
    with pytest.raises(Exception):
        cold_searchdata.restore_searchdata(bad_id)
    assert not (data_dir / "evil.txt").exists()
    assert not (data_dir.parent / "evil.txt").exists()

"""Tests for cold archive verify / export / import / stats.

Run: cd <repo> && python3 -m pytest tests/test_cold_ops.py -q
"""

import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Redirect candid's DATA_DIR (and the cold-dir override) at a tmp tree."""
    monkeypatch.delenv("CANDID_COLD_DIR", raising=False)
    monkeypatch.delenv("CANDID_DATA_DIR", raising=False)
    from candid import config as C

    d = tmp_path / "data"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(C, "DATA_DIR", d)
    return d


def _make(kind="jobs", label="test", members=None, payload=None):
    from candid import coldstore as cs

    return cs.create_archive(
        kind=kind,
        label=label,
        members=members if members is not None else {"a.txt": b"hello", "b.txt": b"world"},
        payload=payload if payload is not None else {"x": 1},
    )


def _zip_path(archive_id):
    from candid import coldstore as cs

    return cs.archive_root() / f"{archive_id}.zip"


def _tamper_member(path: Path, member: str):
    """Rebuild the zip with one member's bytes changed (manifest untouched)."""
    with zipfile.ZipFile(path) as zin:
        items = [(info, zin.read(info.filename)) for info in zin.infolist()]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for info, data in items:
            if info.filename == member:
                data = data + b"<<TAMPERED>>"
            zout.writestr(info, data)


class TestVerify:
    def test_verify_ok_on_fresh_archive(self, data_dir):
        from candid import cold_verify as cv

        m = _make()
        result = cv.verify_archive(m["archive_id"])
        assert result["ok"] is True
        assert result["errors"] == []
        # a.txt + b.txt + payload.json checksums compared
        assert result["checked"] == 3

    def test_verify_missing_archive(self, data_dir):
        from candid import cold_verify as cv

        result = cv.verify_archive("no-such-archive")
        assert result["ok"] is False
        assert result["errors"]

    def test_verify_detects_tampered_member(self, data_dir):
        from candid import cold_verify as cv

        m = _make()
        _tamper_member(_zip_path(m["archive_id"]), "a.txt")
        result = cv.verify_archive(m["archive_id"])
        assert result["ok"] is False
        assert any("checksum mismatch" in e and "a.txt" in e for e in result["errors"])
        assert result["checked"] == 3

    def test_verify_detects_missing_member(self, data_dir):
        from candid import cold_verify as cv

        m = _make()
        path = _zip_path(m["archive_id"])
        with zipfile.ZipFile(path) as zin:
            items = [(info, zin.read(info.filename)) for info in zin.infolist()]
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for info, data in items:
                if info.filename != "b.txt":
                    zout.writestr(info, data)
        result = cv.verify_archive(m["archive_id"])
        assert result["ok"] is False
        assert any("missing from zip" in e and "b.txt" in e for e in result["errors"])

    def test_verify_all_aggregates(self, data_dir):
        from candid import cold_verify as cv

        good1 = _make(label="good-one")
        good2 = _make(kind="prep", label="good-two")
        bad = _make(label="bad-one")
        _tamper_member(_zip_path(bad["archive_id"]), "b.txt")

        result = cv.verify_all()
        assert result["total"] == 3
        assert result["ok"] == 2
        assert result["failed"] == [bad["archive_id"]]

        jobs_only = cv.verify_all(kind="jobs")
        assert jobs_only["total"] == 2
        assert jobs_only["ok"] == 1
        assert jobs_only["failed"] == [bad["archive_id"]]

        prep_only = cv.verify_all(kind="prep")
        assert prep_only == {
            "total": 1,
            "ok": 1,
            "failed": [],
        }


class TestExportImport:
    def test_export_produces_candid_cold_and_keeps_original(self, data_dir, tmp_path):
        from candid import cold_export as ce

        m = _make()
        dest = ce.export_archive(m["archive_id"], tmp_path / "exports")
        assert isinstance(dest, Path)
        assert dest.suffix == ".candid-cold"
        assert dest.is_file()
        # original stays in place
        assert _zip_path(m["archive_id"]).is_file()
        # byte-identical portable copy
        assert dest.read_bytes() == _zip_path(m["archive_id"]).read_bytes()

    def test_export_to_explicit_file_path(self, data_dir, tmp_path):
        from candid import cold_export as ce

        m = _make()
        dest = ce.export_archive(m["archive_id"], tmp_path / "mybackup")
        assert dest.name == "mybackup.candid-cold"
        assert dest.is_file()

    def test_export_missing_archive_raises(self, data_dir, tmp_path):
        from candid import cold_export as ce
        from candid import coldstore as cs

        with pytest.raises(cs.ColdArchiveError):
            ce.export_archive("no-such-archive", tmp_path)

    def test_import_round_trip(self, data_dir, tmp_path):
        from candid import cold_export as ce
        from candid import cold_verify as cv
        from candid import coldstore as cs

        m = _make(members={"note.txt": b"round trip"})
        portable = ce.export_archive(m["archive_id"], tmp_path)
        assert cs.delete_archive(m["archive_id"])
        assert not _zip_path(m["archive_id"]).exists()

        manifest = ce.import_archive(portable)
        assert manifest["archive_id"] == m["archive_id"]
        assert _zip_path(m["archive_id"]).is_file()
        result = cv.verify_archive(m["archive_id"])
        assert result["ok"] is True
        # payload survived the round trip
        assert cs.read_archive(m["archive_id"])["payload"] == {"x": 1}

    def test_import_collision_renames(self, data_dir, tmp_path):
        from candid import cold_export as ce
        from candid import cold_verify as cv

        m = _make(label="collision")
        portable = ce.export_archive(m["archive_id"], tmp_path)
        # original still installed -> collision on import
        manifest = ce.import_archive(portable)
        assert manifest["archive_id"] != m["archive_id"]
        assert manifest["archive_id"].startswith(m["archive_id"] + "-")
        assert _zip_path(m["archive_id"]).is_file()
        assert _zip_path(manifest["archive_id"]).is_file()
        assert cv.verify_archive(manifest["archive_id"])["ok"] is True

    def test_import_rejects_garbage(self, data_dir, tmp_path):
        from candid import cold_export as ce
        from candid import coldstore as cs

        garbage = tmp_path / "garbage.candid-cold"
        garbage.write_text("this is definitely not a zip file")
        with pytest.raises(cs.ColdArchiveError):
            ce.import_archive(garbage)

        not_an_archive = tmp_path / "plain.zip"
        with zipfile.ZipFile(not_an_archive, "w") as zf:
            zf.writestr("random.txt", b"no manifest here")
        with pytest.raises(cs.ColdArchiveError):
            ce.import_archive(not_an_archive)

        with pytest.raises(cs.ColdArchiveError):
            ce.import_archive(tmp_path / "missing.candid-cold")


class TestStats:
    def test_storage_stats_numbers_add_up(self, data_dir):
        from candid import cold_stats as st

        (data_dir / "tracker.json").write_text(json.dumps({"apps": [1, 2, 3]}))
        (data_dir / "profile.json").write_text(json.dumps({"name": "Test"}))
        (data_dir / "gmail_proposals.json").write_text("{}")
        (data_dir / "salary.db").write_bytes(b"\x00" * 2048)
        (data_dir / "jobs.json").write_text(json.dumps({"jobs": []}))
        (data_dir / "job_meta.json").write_text("{}")
        pack = data_dir / "prep_packs" / "pack1"
        pack.mkdir(parents=True)
        (pack / "notes.md").write_bytes(b"n" * 500)
        tailored = data_dir / "tailored"
        tailored.mkdir()
        (tailored / "resume.pdf").write_bytes(b"r" * 1500)

        jm = _make(kind="jobs", label="stats-jobs", members={"j.txt": b"1" * 100})
        pm = _make(kind="prep", label="stats-prep", members={"p.txt": b"2" * 200})

        stats = st.storage_stats()
        by = stats["by_category"]
        assert by["tracker"] == (data_dir / "tracker.json").stat().st_size
        assert by["profile"] == (data_dir / "profile.json").stat().st_size
        assert by["prep_packs"] == 500
        assert by["tailored"] == 1500
        assert by["gmail_proposals"] == (data_dir / "gmail_proposals.json").stat().st_size
        assert by["salary"] == 2048
        assert by["jobs"] == (data_dir / "jobs.json").stat().st_size + (
            data_dir / "job_meta.json"
        ).stat().st_size

        assert by["cold_archive:jobs"] == _zip_path(jm["archive_id"]).stat().st_size
        assert by["cold_archive:prep"] == _zip_path(pm["archive_id"]).stat().st_size

        assert stats["cold_bytes"] == by["cold_archive:jobs"] + by["cold_archive:prep"]
        assert stats["active_bytes"] == sum(
            by[k] for k in ("tracker", "profile", "prep_packs", "tailored",
                            "gmail_proposals", "salary", "jobs")
        )
        assert stats["total_bytes"] == stats["active_bytes"] + stats["cold_bytes"]
        assert stats["archive_count"] == 2
        assert stats["oldest_archive_utc"] == min(
            jm["created_utc"], pm["created_utc"]
        )

    def test_storage_stats_empty_dir(self, data_dir):
        from candid import cold_stats as st

        stats = st.storage_stats()
        assert stats["active_bytes"] == 0
        assert stats["cold_bytes"] == 0
        assert stats["total_bytes"] == 0
        assert stats["archive_count"] == 0
        assert stats["oldest_archive_utc"] is None

    def test_format_stats_human_readable(self, data_dir):
        from candid import cold_stats as st

        (data_dir / "tracker.json").write_bytes(b"x" * 2048)  # 2.0 KB
        _make(kind="jobs", label="fmt")
        out = st.format_stats(st.storage_stats())
        assert isinstance(out, str)
        assert "tracker" in out
        assert "KB" in out
        assert "cold_archive" in out
        assert "total" in out
        assert "oldest archive" in out
        print(out)

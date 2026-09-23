"""Tests for candid.coldstore — cold archival core engine.

Every test isolates state by monkeypatching ``candid.config.DATA_DIR`` to a
fresh tmp dir; coldstore resolves the data dir at call time, so no re-import
is needed.
"""

from __future__ import annotations

import hashlib
import json
import zipfile

import pytest

import candid
from candid import config as config_module
from candid import coldstore


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "candid_data"
    monkeypatch.setattr(config_module, "DATA_DIR", d)
    monkeypatch.delenv("CANDID_COLD_DIR", raising=False)
    return d


def test_archive_root_creates_dir(data_dir):
    root = coldstore.archive_root()
    assert root == data_dir / "cold_archive"
    assert root.is_dir()


def test_create_list_read_roundtrip(data_dir):
    manifest = coldstore.create_archive("applications", "Q3 backups",
                                        members={"notes.txt": b"hello"})
    assert manifest["kind"] == "applications"
    assert manifest["label"] == "Q3 backups"
    assert manifest["candid_version"] == candid.__version__
    assert "created_utc" in manifest
    assert manifest["compression"] == 6

    archives = coldstore.list_archives()
    assert len(archives) == 1
    assert archives[0]["archive_id"] == manifest["archive_id"]

    read = coldstore.read_archive(manifest["archive_id"])
    assert read["kind"] == "applications"
    assert read["members"] == ["notes.txt"]
    assert read["payload"] is None
    assert coldstore.extract_member(manifest["archive_id"], "notes.txt") == b"hello"


def test_payload_and_binary_members(data_dir):
    binary = bytes(range(256)) * 4
    manifest = coldstore.create_archive(
        "profile",
        "snapshot",
        members={"blob.bin": binary, "doc.md": b"# hi"},
        payload={"name": "Keshavan", "n": 3},
    )
    aid = manifest["archive_id"]
    read = coldstore.read_archive(aid)
    assert read["payload"] == {"name": "Keshavan", "n": 3}
    assert sorted(read["members"]) == ["blob.bin", "doc.md"]
    assert coldstore.extract_member(aid, "blob.bin") == binary
    # payload.json itself is a zip member too
    assert coldstore.extract_member(aid, "payload.json")


def test_checksum_manifest_correctness(data_dir):
    members = {"a.txt": b"alpha", "sub/b.bin": b"\x00\x01\x02"}
    manifest = coldstore.create_archive("checks", "verify me",
                                        members=members,
                                        payload={"x": 1})
    expected = {name: hashlib.sha256(data).hexdigest()
                for name, data in members.items()}
    expected["payload.json"] = hashlib.sha256(
        json.dumps({"x": 1}, indent=2, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert manifest["files"] == expected

    # cross-check against the bytes actually stored in the zip
    path = data_dir / "cold_archive" / f"{manifest['archive_id']}.zip"
    with zipfile.ZipFile(path) as zf:
        for name, digest in manifest["files"].items():
            assert hashlib.sha256(zf.read(name)).hexdigest() == digest


def test_zip_slip_rejection(data_dir):
    manifest = coldstore.create_archive("safe", "slip test",
                                        members={"ok.txt": b"fine"})
    aid = manifest["archive_id"]
    for evil in ("../evil.txt", "..\\evil.txt", "/abs/path.txt", "a/../../x"):
        with pytest.raises(coldstore.ColdArchiveError):
            coldstore.extract_member(aid, evil)
        with pytest.raises(coldstore.ColdArchiveError):
            coldstore.create_archive("safe", "slip test", members={evil: b"x"})
    # legit files still fine
    assert coldstore.extract_member(aid, "ok.txt") == b"fine"


def test_corrupt_zip_skipped_in_list(data_dir, capsys):
    good = coldstore.create_archive("good", "keeper", members={"k.txt": b"k"})
    bad_path = coldstore.archive_root() / "20240101T000000-fake-bad.zip"
    bad_path.write_bytes(b"this is not a zip file")
    archives = coldstore.list_archives()
    assert [a["archive_id"] for a in archives] == [good["archive_id"]]
    assert "skipping corrupt archive" in capsys.readouterr().err


def test_list_kind_filter_and_newest_first(data_dir):
    first = coldstore.create_archive("a", "first")
    second = coldstore.create_archive("b", "second")
    third = coldstore.create_archive("a", "third")
    all_ids = [a["archive_id"] for a in coldstore.list_archives()]
    assert all_ids == sorted(all_ids, reverse=True)
    assert {a["archive_id"] for a in coldstore.list_archives(kind="a")} == {
        first["archive_id"], third["archive_id"]}
    assert [a["archive_id"] for a in coldstore.list_archives(kind="b")] == [
        second["archive_id"]]


def test_delete(data_dir):
    manifest = coldstore.create_archive("tmp", "to delete")
    aid = manifest["archive_id"]
    assert coldstore.archive_size(aid) > 0
    assert coldstore.delete_archive(aid) is True
    assert coldstore.delete_archive(aid) is False  # already gone
    assert coldstore.list_archives() == []
    with pytest.raises(coldstore.ColdArchiveError):
        coldstore.read_archive(aid)


def test_archive_id_uniqueness(data_dir):
    manifests = [coldstore.create_archive("dup", "same label")
                 for _ in range(10)]
    ids = [m["archive_id"] for m in manifests]
    assert len(set(ids)) == 10
    assert len(coldstore.list_archives()) == 10


def test_compression_clamped(data_dir):
    m = coldstore.create_archive("c", "clamp", compression=99)
    assert m["compression"] == 9
    m = coldstore.create_archive("c", "clamp", compression=-3)
    assert m["compression"] == 0


def test_read_missing_archive_raises(data_dir):
    with pytest.raises(coldstore.ColdArchiveError):
        coldstore.read_archive("no-such-archive")
    with pytest.raises(coldstore.ColdArchiveError):
        coldstore.archive_size("no-such-archive")


def test_env_override(tmp_path, monkeypatch):
    override = tmp_path / "elsewhere"
    monkeypatch.setenv("CANDID_COLD_DIR", str(override))
    root = coldstore.archive_root()
    assert root == override
    assert root.is_dir()
    m = coldstore.create_archive("env", "override works")
    assert (override / f"{m['archive_id']}.zip").is_file()

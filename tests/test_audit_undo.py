"""Tests for audit instrumentation of tracker ops + undo (batch 75, worker B).

Covers: tracker.add/update/remove each produce an audit entry with correct
before/after snapshots; the audit entry's derived ``changes`` diff captures
the changed fields; duplicate add and explicit-path ops are not audited;
audit failures never break tracker ops; return values are unchanged;
undo of update/delete/create; double-undo; UndoError for non-tracker
entries and unknown ids.

Runs against the real ``candid.audit`` module (worker A).
"""

import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-audit-undo"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import audit as AUD  # noqa: E402
from candid import config as C  # noqa: E402
from candid import tracker as T  # noqa: E402
from candid import undo as U  # noqa: E402


def _entries():
    """Audit entries in chronological (oldest-first) order."""
    return list(reversed(AUD.read()))


@pytest.fixture(autouse=True)
def _clean():
    for p in (Path(C.AUDIT_PATH), Path(C.TRACKER_PATH)):
        if p.exists():
            p.unlink()
    yield
    for p in (Path(C.AUDIT_PATH), Path(C.TRACKER_PATH)):
        if p.exists():
            p.unlink()


# ---------------------------------------------------------------------------
# instrumentation
# ---------------------------------------------------------------------------

def test_add_produces_create_entry():
    rec = T.add("Acme", "Backend Engineer")
    entries = _entries()
    assert len(entries) == 1
    e = entries[0]
    assert e["actor"] == "cli"
    assert e["command"] == "track add"
    assert e["entity"] == "tracker"
    assert e["entity_id"] == str(rec["id"])
    assert e["action"] == "create"
    assert e["before"] is None
    assert e["after"]["company"] == "Acme"
    assert e["after"]["role"] == "Backend Engineer"
    assert e["after"]["status"] == "saved"
    assert e["after"]["id"] == rec["id"]
    assert AUD.verify() == []


def test_update_produces_update_entry():
    rec = T.add("Acme", "Backend Engineer")
    T.update(rec["id"], status="applied", notes="applied via referral")
    entries = _entries()
    assert len(entries) == 2
    e = entries[1]
    assert e["actor"] == "cli"
    assert e["command"] == "track update"
    assert e["entity"] == "tracker"
    assert e["entity_id"] == str(rec["id"])
    assert e["action"] == "update"
    assert e["before"]["status"] == "saved"
    assert e["before"]["notes"] == ""
    assert e["after"]["status"] == "applied"
    assert e["after"]["notes"] == "applied via referral"
    assert AUD.verify() == []


def test_update_diff_captures_changed_fields():
    rec = T.add("Acme", "Backend Engineer")
    T.update(rec["id"], status="rejected")
    e = _entries()[1]
    changed = {c["field"] for c in e["changes"]}
    # only the status changed; date_updated was already today's date
    assert changed == {"status"}
    change = e["changes"][0]
    assert change["old"] == "saved"
    assert change["new"] == "rejected"
    # and a multi-field update shows exactly those fields
    T.update(rec["id"], status="applied", notes="via referral")
    e2 = _entries()[2]
    changed2 = {c["field"] for c in e2["changes"]}
    assert changed2 == {"status", "notes"}
    assert e2["before"]["status"] == "rejected"
    assert e2["after"]["status"] == "applied"


def test_remove_produces_delete_entry():
    rec = T.add("Acme", "Backend Engineer")
    T.remove(rec["id"])
    entries = _entries()
    assert len(entries) == 2
    e = entries[1]
    assert e["actor"] == "cli"
    assert e["command"] == "track remove"
    assert e["entity"] == "tracker"
    assert e["entity_id"] == str(rec["id"])
    assert e["action"] == "delete"
    assert e["before"]["company"] == "Acme"
    assert e["before"]["id"] == rec["id"]
    assert e["after"] is None
    assert AUD.verify() == []


def test_duplicate_add_records_nothing():
    T.add("Acme", "Backend Engineer")
    assert len(_entries()) == 1
    dup = T.add("acme", "backend engineer")
    assert dup.get("duplicate") is True
    # duplicate is a no-op: no write happened, so no audit entry
    assert len(_entries()) == 1


def test_explicit_path_skips_audit():
    td = tempfile.mkdtemp()
    p = str(Path(td) / "tmp-tracker.json")
    rec = T.add("Acme", "Backend Engineer", path=p)
    T.update(rec["id"], status="applied", path=p)
    T.remove(rec["id"], path=p)
    # temp-path ops are not the real file: no audit entries
    assert _entries() == []
    # sanity: the temp file itself still worked
    assert T.list_apps(path=p) == []


def test_audit_failure_never_breaks_ops(capsys):
    with patch.object(AUD, "record", side_effect=RuntimeError("audit down")):
        rec = T.add("Acme", "Backend Engineer")
        assert rec["company"] == "Acme"
        upd = T.update(rec["id"], status="applied")
        assert upd["status"] == "applied"
        T.remove(rec["id"])
        assert T.list_apps() == []
    err = capsys.readouterr().err
    assert "audit failed" in err
    # no entries made it through
    assert _entries() == []


def test_return_values_unchanged_by_instrumentation():
    rec = T.add("Acme", "Backend Engineer")
    assert isinstance(rec, dict)
    assert rec["id"] == 1 and rec["company"] == "Acme"
    assert "duplicate" not in rec
    dup = T.add("Acme", "Backend Engineer")
    assert dup.get("duplicate") is True and dup["id"] == 1
    upd = T.update(1, status="offer")
    assert upd["id"] == 1 and upd["status"] == "offer"
    assert T.remove(1) is None


def test_failed_ops_record_no_audit():
    T.add("Acme", "Backend Engineer")
    with pytest.raises(T.TrackerError):
        T.update(999, status="applied")
    with pytest.raises(T.TrackerError):
        T.remove(999)
    with pytest.raises(T.TrackerError):
        T.update(1, status="bogus")
    # only the successful add is in the log
    assert [e["action"] for e in _entries()] == ["create"]


# ---------------------------------------------------------------------------
# undo
# ---------------------------------------------------------------------------

def test_undo_update_restores_old_status_and_notes():
    rec = T.add("Acme", "Backend Engineer", notes="original notes")
    T.update(rec["id"], status="rejected", notes="changed notes")
    assert T.list_apps()[0]["status"] == "rejected"
    undo_entry = U.undo(_entries()[1]["id"])
    assert T.list_apps()[0]["status"] == "saved"
    assert T.list_apps()[0]["notes"] == "original notes"
    assert undo_entry["action"] == "undo"
    assert undo_entry["entity"] == "tracker"
    assert undo_entry["entity_id"] == str(rec["id"])
    assert undo_entry["command"] == "undo"
    assert str(_entries()[1]["id"]) in undo_entry["note"]
    # the undo entry's own before/after mirror the reversal
    assert undo_entry["before"]["status"] == "rejected"
    assert undo_entry["after"]["status"] == "saved"
    assert AUD.verify() == []


def test_undo_delete_reinserts_record():
    rec = T.add("Acme", "Backend Engineer")
    T.remove(rec["id"])
    assert T.list_apps() == []
    undo_entry = U.undo(_entries()[1]["id"])
    apps = T.list_apps()
    assert len(apps) == 1
    assert apps[0]["id"] == rec["id"]
    assert apps[0]["company"] == "Acme"
    assert apps[0]["role"] == "Backend Engineer"
    assert undo_entry["action"] == "undo"
    assert undo_entry["after"]["company"] == "Acme"
    assert undo_entry["before"] is None


def test_undo_create_removes_record():
    rec = T.add("Acme", "Backend Engineer")
    assert len(T.list_apps()) == 1
    undo_entry = U.undo(_entries()[0]["id"])
    assert T.list_apps() == []
    assert undo_entry["action"] == "undo"
    assert undo_entry["after"] is None
    assert undo_entry["before"]["company"] == "Acme"


def test_double_undo():
    rec = T.add("Acme", "Backend Engineer")
    T.update(rec["id"], status="applied")
    first_undo = U.undo(_entries()[1]["id"])   # back to saved
    assert T.list_apps()[0]["status"] == "saved"
    second_undo = U.undo(first_undo["id"])     # undo of undo: back to applied
    assert T.list_apps()[0]["status"] == "applied"
    assert second_undo["action"] == "undo"
    assert second_undo["entity_id"] == str(rec["id"])
    # the log now holds: create, update, undo, undo
    assert [e["action"] for e in _entries()] == ["create", "update", "undo", "undo"]
    assert AUD.verify() == []


def test_undo_non_tracker_entry_raises():
    entry = AUD.record(actor="cli", command="match run", entity="match",
                       entity_id="job-9", action="create", before=None,
                       after={"id": "job-9"})
    with pytest.raises(U.UndoError):
        U.undo(entry["id"])


def test_undo_unknown_action_raises():
    entry = AUD.record(actor="cli", command="track add", entity="tracker",
                       entity_id="3", action="migrate", before=None, after=None)
    with pytest.raises(U.UndoError):
        U.undo(entry["id"])


def test_undo_unknown_id_raises():
    with pytest.raises(U.UndoError):
        U.undo("no-such-id")
    with pytest.raises(U.UndoError):
        U.undo(99999)


def test_undo_preserves_other_records():
    r1 = T.add("Acme", "Backend Engineer")
    r2 = T.add("Globex", "ML Engineer")
    T.update(r1["id"], status="rejected")
    U.undo(_entries()[2]["id"])
    apps = {a["id"]: a for a in T.list_apps()}
    assert apps[r1["id"]]["status"] == "saved"
    assert apps[r2["id"]]["status"] == "saved"
    assert apps[r2["id"]]["company"] == "Globex"

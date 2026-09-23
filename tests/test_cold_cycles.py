"""Tests for candid.cold_cycles. Run: python -m pytest tests/test_cold_cycles.py -q"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C


# --- stub coldstore (the real candid/coldstore.py is being built in parallel) -


class StubColdstore:
    """In-memory stand-in for the assumed coldstore contract."""

    def __init__(self):
        self.archives = {}
        self.counter = 0

    def create_archive(self, kind, label=None, members=None, payload=None):
        self.counter += 1
        aid = f"arc-{self.counter:04d}"
        self.archives[aid] = {
            "id": aid,
            "kind": kind,
            "label": label,
            "members": dict(members or {}),
            "payload": dict(payload or {}),
        }
        return {"id": aid, "kind": kind, "label": label}

    def list_archives(self, kind=None):
        return [
            {"id": a["id"], "kind": a["kind"], "label": a["label"]}
            for a in self.archives.values()
            if kind is None or a["kind"] == kind
        ]

    def read_archive(self, archive_id):
        a = self.archives[archive_id]
        return {
            "id": a["id"],
            "kind": a["kind"],
            "label": a["label"],
            "members": list(a["members"].keys()),
            "payload": a["payload"],
        }

    def extract_member(self, archive_id, name):
        return self.archives[archive_id]["members"][name]

    def delete_archive(self, archive_id):
        if archive_id not in self.archives:
            return False
        del self.archives[archive_id]
        return True


@pytest.fixture()
def tmp_data(monkeypatch, tmp_path):
    """Isolated CANDID data dir."""
    monkeypatch.setattr(C, "DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture()
def stub_coldstore(monkeypatch):
    stub = StubColdstore()
    monkeypatch.setitem(sys.modules, "candid.coldstore", stub)
    return stub


@pytest.fixture()
def cc(tmp_data, stub_coldstore):
    import importlib

    import candid.cold_cycles as cc

    return importlib.reload(cc)


def iso_days_ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


def mk(app_id, status, date_updated, company="Acme", role="Engineer"):
    return {
        "id": app_id,
        "company": company,
        "role": role,
        "status": status,
        "date_added": date_updated,
        "date_updated": date_updated,
    }


def seed_tracker(tmp_data, apps):
    p = tmp_data / "tracker.json"
    p.write_text(json.dumps(apps), encoding="utf-8")
    return p


def load_tracker(tmp_data):
    return json.loads((tmp_data / "tracker.json").read_text(encoding="utf-8"))


# --- fixtures of apps ---------------------------------------------------------


def sample_apps():
    return [
        mk(1, "rejected", iso_days_ago(120), "Old Corp", "SWE"),  # old+closed -> archive
        mk(2, "withdrawn", iso_days_ago(200), "Ancient Inc", "ML"),  # old+closed -> archive
        mk(3, "rejected", iso_days_ago(10), "Fresh Co", "SWE"),  # recent closed -> keep
        mk(4, "offer", iso_days_ago(150), "Hired LLC", "SDE"),  # old+closed -> archive
        mk(5, "applied", iso_days_ago(120), "Active Co", "DS"),  # old but active -> keep
        mk(6, "selected_for_interview", iso_days_ago(200), "Interview Co", "PM"),  # old but active -> keep
        mk(7, "rejected", "not-a-date", "Weird Dates", "SWE"),  # unparseable -> keep
        mk(8, "rejected", "", "No Dates", "SWE"),  # missing -> keep
    ]


# --- tests --------------------------------------------------------------------


def test_closed_statuses_come_from_tracker_statuses(cc):
    assert {"rejected", "withdrawn"} <= cc.CLOSED_STATUSES
    assert cc.CLOSED_STATUSES <= set(C.STATUSES)
    assert "applied" not in cc.CLOSED_STATUSES
    assert "selected_for_interview" not in cc.CLOSED_STATUSES
    assert "saved" not in cc.CLOSED_STATUSES


def test_dry_run_archives_nothing(cc, tmp_data, stub_coldstore):
    apps = sample_apps()
    seed_tracker(tmp_data, apps)
    result = cc.archive_old_cycles(days=90, dry_run=True)

    assert result["dry_run"] is True
    assert result["archived"] == 3
    assert sorted(result["app_ids"]) == [1, 2, 4]
    assert result["archive_id"] is None
    # nothing changed
    assert load_tracker(tmp_data) == apps
    assert stub_coldstore.list_archives() == []


def test_real_run_archives_only_old_closed(cc, tmp_data, stub_coldstore):
    seed_tracker(tmp_data, sample_apps())
    result = cc.archive_old_cycles(days=90, dry_run=False)

    assert result["dry_run"] is False
    assert result["archived"] == 3
    assert sorted(result["app_ids"]) == [1, 2, 4]
    assert result["archive_id"] is not None

    # tracker no longer contains the archived apps
    remaining = load_tracker(tmp_data)
    assert sorted(a["id"] for a in remaining) == [3, 5, 6, 7, 8]

    # coldstore has one cycles archive with one member per app
    archives = stub_coldstore.list_archives(kind="cycles")
    assert len(archives) == 1
    assert archives[0]["label"].startswith("closed-apps-")
    detail = stub_coldstore.read_archive(result["archive_id"])
    assert sorted(detail["members"]) == ["apps/1.json", "apps/2.json", "apps/4.json"]
    member = json.loads(stub_coldstore.extract_member(result["archive_id"], "apps/1.json"))
    assert member["company"] == "Old Corp"
    assert member["status"] == "rejected"
    # payload summary
    assert detail["payload"]["count"] == 3
    assert "archived_utc" in detail["payload"]
    assert sorted(detail["payload"]["statuses"]) == ["offer", "rejected", "withdrawn"]


def test_nothing_to_archive_returns_empty(cc, tmp_data, stub_coldstore):
    seed_tracker(tmp_data, [mk(1, "applied", iso_days_ago(10))])
    result = cc.archive_old_cycles(days=90)
    assert result == {"archived": 0, "archive_id": None, "app_ids": [], "dry_run": False}
    assert stub_coldstore.list_archives() == []


def test_custom_statuses_override(cc, tmp_data, stub_coldstore):
    seed_tracker(tmp_data, sample_apps())
    # only "offer" counts as closed here
    result = cc.archive_old_cycles(days=90, statuses={"offer"})
    assert result["archived"] == 1
    assert result["app_ids"] == [4]
    assert sorted(a["id"] for a in load_tracker(tmp_data)) == [1, 2, 3, 5, 6, 7, 8]


def test_unparseable_dates_are_left_alone(cc, tmp_data, stub_coldstore):
    seed_tracker(tmp_data, sample_apps())
    cc.archive_old_cycles(days=90)
    remaining = {a["id"]: a for a in load_tracker(tmp_data)}
    # closed apps with unparseable/missing dates were never archived
    assert 7 in remaining and 8 in remaining
    # and nothing else weird happened
    assert cc.list_archived_cycles() and all(
        e["app_id"] in (1, 2, 4) for e in cc.list_archived_cycles()
    )


def test_restore_brings_back_without_duplicating(cc, tmp_data, stub_coldstore):
    seed_tracker(tmp_data, sample_apps())
    cc.archive_old_cycles(days=90)
    assert sorted(a["id"] for a in load_tracker(tmp_data)) == [3, 5, 6, 7, 8]

    restored = cc.restore_application("1")
    assert restored["company"] == "Old Corp"
    assert restored["status"] == "rejected"
    assert sorted(a["id"] for a in load_tracker(tmp_data)) == [1, 3, 5, 6, 7, 8]

    # restoring again does not duplicate
    again = cc.restore_application(1)
    assert again["id"] == 1
    ids = [a["id"] for a in load_tracker(tmp_data)]
    assert sorted(ids) == [1, 3, 5, 6, 7, 8]
    assert len(ids) == len(set(ids))


def test_restore_missing_raises(cc, tmp_data, stub_coldstore):
    seed_tracker(tmp_data, sample_apps())
    cc.archive_old_cycles(days=90)
    with pytest.raises(cc.ColdCyclesError):
        cc.restore_application("999")


def test_list_archived_cycles_reflects_state(cc, tmp_data, stub_coldstore):
    seed_tracker(tmp_data, sample_apps())
    assert cc.list_archived_cycles() == []

    result = cc.archive_old_cycles(days=90)
    listed = cc.list_archived_cycles()
    assert len(listed) == 3
    assert all(e["archive_id"] == result["archive_id"] for e in listed)
    assert sorted(e["app_id"] for e in listed) == [1, 2, 4]
    by_id = {e["app_id"]: e for e in listed}
    assert by_id[2]["company"] == "Ancient Inc"
    assert by_id[4]["status"] == "offer"


def test_prune_cycles_archive(cc, tmp_data, stub_coldstore):
    seed_tracker(tmp_data, sample_apps())
    result = cc.archive_old_cycles(days=90)
    assert len(cc.list_archived_cycles()) == 3

    assert cc.prune_cycles_archive(result["archive_id"]) is True
    assert cc.list_archived_cycles() == []
    # pruning again reports not-found
    assert cc.prune_cycles_archive(result["archive_id"]) is False


def test_prune_refuses_non_cycles_archive(cc, tmp_data, stub_coldstore):
    other = stub_coldstore.create_archive(
        "backups", label="other", members={}, payload={}
    )
    with pytest.raises(cc.ColdCyclesError):
        cc.prune_cycles_archive(other["id"])


def test_uses_monkeypatched_data_dir(cc, tmp_data, stub_coldstore):
    # module must read C.DATA_DIR at call time, not at import time
    seed_tracker(tmp_data, sample_apps())
    cc.archive_old_cycles(days=90)
    assert (tmp_data / "tracker.json").exists()
    assert len(stub_coldstore.list_archives()) == 1


# --- integration with the real candid.coldstore (worker A's module) ---------


@pytest.fixture()
def cc_real(tmp_data):
    """cold_cycles wired to the real candid.coldstore (no stub)."""
    import importlib

    # make sure no test stub shadows the real module
    sys.modules.pop("candid.coldstore", None)
    import candid.coldstore  # noqa: F401 - must exist on disk
    import candid.cold_cycles as cc

    return importlib.reload(cc)


def test_end_to_end_with_real_coldstore(cc_real, tmp_data):
    seed_tracker(tmp_data, sample_apps())

    result = cc_real.archive_old_cycles(days=90)
    assert result["archived"] == 3
    assert result["archive_id"]
    assert sorted(a["id"] for a in load_tracker(tmp_data)) == [3, 5, 6, 7, 8]

    listed = cc_real.list_archived_cycles()
    assert len(listed) == 3
    assert all(e["archive_id"] == result["archive_id"] for e in listed)

    restored = cc_real.restore_application(2)
    assert restored["company"] == "Ancient Inc"
    # no duplicate on second restore
    cc_real.restore_application("2")
    assert len(load_tracker(tmp_data)) == 6

    assert cc_real.prune_cycles_archive(result["archive_id"]) is True
    assert cc_real.list_archived_cycles() == []

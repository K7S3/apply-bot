"""Tests for candid.reject_log. Run: python -m pytest tests/test_reject_log.py -q"""
import os
import shutil
import sys
from pathlib import Path

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-reject-log"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from candid import config as C  # noqa: E402
from candid import reject_log as RL  # noqa: E402
from candid import tracker as T  # noqa: E402


@pytest.fixture(autouse=True)
def clean_data_dir():
    if C.DATA_DIR.exists():
        shutil.rmtree(C.DATA_DIR)
    C.DATA_DIR.mkdir(parents=True, exist_ok=True)
    yield


def _add_app(company="Acme Corp", role="MLE"):
    return T.add(company, role, status="applied")


def test_log_rejection_sets_tracker_status_and_stores_fields():
    app = _add_app()
    rec = RL.log_rejection(app["id"], stage="onsite",
                           reason_notes="culture fit", feedback="strong technically")
    assert T.list_apps(path=None)[0]["status"] == "rejected"
    assert rec["app_id"] == app["id"]
    assert rec["company"] == "Acme Corp"
    assert rec["role"] == "MLE"
    assert rec["stage"] == "onsite"
    assert rec["reason_notes"] == "culture fit"
    assert rec["feedback"] == "strong technically"
    assert RL.get_rejection(app["id"]) == rec


def test_log_rejection_invalid_stage_raises():
    app = _add_app()
    with pytest.raises(RL.RejectLogError):
        RL.log_rejection(app["id"], stage="coffee_chat")


def test_log_rejection_unknown_app_id_raises():
    with pytest.raises(RL.RejectLogError):
        RL.log_rejection(999, stage="applied")


def test_relogging_same_app_updates_rather_than_duplicates():
    app = _add_app()
    RL.log_rejection(app["id"], stage="phone_screen", reason_notes="first try")
    rec = RL.log_rejection(app["id"], stage="onsite", reason_notes="second try")
    assert rec["stage"] == "onsite"
    assert rec["reason_notes"] == "second try"
    assert len(RL.list_rejections()) == 1


def test_get_rejection_returns_none_for_unknown():
    assert RL.get_rejection(12345) is None


def test_render_log_empty():
    assert RL.render_log([]) == "No rejections logged yet."


def test_render_log_nonempty():
    app = _add_app()
    rec = RL.log_rejection(app["id"], stage="onsite", reason_notes="headcount freeze")
    out = RL.render_log([rec])
    assert f"#{app['id']} Acme Corp - MLE" in out
    assert "stage: onsite" in out
    assert "headcount freeze" in out

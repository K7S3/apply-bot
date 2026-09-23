"""Tests for candid/drafting/store.py -- per-application draft version storage."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid.drafting import store  # noqa: E402


def _draft(subject="Subject line", body="Hi there.\n\nThis is the body.\n\nBest,\nKeshavan"):
    return {"subject": subject, "body": body}


def test_save_and_get_roundtrip(tmp_path):
    draft_id = store.save_draft("app-1", _draft(), kind="followup", data_dir=tmp_path)
    assert draft_id == "v1"
    rec = store.get_draft(draft_id, data_dir=tmp_path)
    assert rec["subject"] == "Subject line"
    assert "This is the body" in rec["body"]
    assert rec["kind"] == "followup"
    assert rec["app_id"] == "app-1"
    assert rec["created"]


def test_versions_never_overwrite(tmp_path):
    id1 = store.save_draft("app-1", _draft(body="first"), data_dir=tmp_path)
    id2 = store.save_draft("app-1", _draft(body="second"), data_dir=tmp_path)
    assert id1 != id2
    assert (id1, id2) == ("v1", "v2")
    assert store.get_draft(id1, data_dir=tmp_path)["body"] == "first"
    assert store.get_draft(id2, data_dir=tmp_path)["body"] == "second"
    # both files exist on disk
    files = list((tmp_path / "drafts" / "app-1").glob("v*.json"))
    assert len(files) == 2


def test_versions_isolated_per_app(tmp_path):
    store.save_draft("app-a", _draft(), data_dir=tmp_path)
    store.save_draft("app-a", _draft(), data_dir=tmp_path)
    id_b = store.save_draft("app-b", _draft(), data_dir=tmp_path)
    assert id_b == "v1"  # separate counter per app_id


def test_list_drafts_sorted(tmp_path):
    store.save_draft("app-1", _draft(body="one"), kind="followup", data_dir=tmp_path)
    store.save_draft("app-1", _draft(body="two"), kind="thankyou", data_dir=tmp_path)
    listing = store.list_drafts("app-1", data_dir=tmp_path)
    assert [r["draft_id"] for r in listing] == ["v1", "v2"]
    assert listing[0]["kind"] == "followup"
    assert listing[1]["kind"] == "thankyou"
    assert all(r["created"] for r in listing)
    assert store.list_drafts("unknown-app", data_dir=tmp_path) == []


def test_get_draft_unknown_raises(tmp_path):
    store.save_draft("app-1", _draft(), data_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        store.get_draft("v99", data_dir=tmp_path)


def test_diff_drafts_unified_output(tmp_path):
    id1 = store.save_draft("app-1", _draft(body="Line one.\nLine two."), data_dir=tmp_path)
    id2 = store.save_draft("app-1", _draft(body="Line one.\nLine three."), data_dir=tmp_path)
    out = store.diff_drafts(id1, id2, data_dir=tmp_path)
    assert out.startswith("--- draft v1")
    assert "+++ draft v2" in out
    assert "-Line two." in out
    assert "+Line three." in out
    # identical drafts produce an empty diff (no change lines)
    assert store.diff_drafts(id1, id1, data_dir=tmp_path) == ""


def test_diff_subject_change(tmp_path):
    id1 = store.save_draft("app-1", _draft(subject="Old subject"), data_dir=tmp_path)
    id2 = store.save_draft("app-1", _draft(subject="New subject"), data_dir=tmp_path)
    out = store.diff_drafts(id1, id2, data_dir=tmp_path)
    assert "-Subject: Old subject" in out
    assert "+Subject: New subject" in out


def test_render_markdown(tmp_path):
    md = store.render_markdown(_draft())
    assert md.startswith("# Subject line\n\n")
    assert "This is the body." in md
    # missing subject degrades gracefully
    assert store.render_markdown({"body": "just body"}) == "just body\n"
    assert store.render_markdown({}) == "\n"


def test_on_disk_json_format(tmp_path):
    store.save_draft("app-1", _draft(), data_dir=tmp_path)
    p = tmp_path / "drafts" / "app-1" / "v1.json"
    rec = json.loads(p.read_text(encoding="utf-8"))
    assert rec["draft_id"] == "v1"
    assert rec["subject"] == "Subject line"

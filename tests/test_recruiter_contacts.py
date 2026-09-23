"""Tests for candid/recruiter_contacts.py.

Covers: CRUD, duplicate-add convention, do-not-engage (block/unblock,
is_blocked), list filters, validation errors, persistence round-trip.

Run: CANDID_DATA_DIR=/tmp/candid-test-recruiters python3 -m pytest tests/test_recruiter_contacts.py -q
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-recruiters")

from candid import config as C  # noqa: E402
from candid import recruiter_contacts as R  # noqa: E402


@pytest.fixture
def p(tmp_path):
    return tmp_path / "recruiters.json"


# ---------------------------------------------------------------------------
# add / get / update / delete
# ---------------------------------------------------------------------------

def test_add_minimal(p):
    rec = R.add("Jane Doe", "Acme Corp", path=p)
    assert rec["id"] == 1
    assert rec["name"] == "Jane Doe"
    assert rec["company"] == "Acme Corp"
    assert rec["kind"] == "inhouse"
    assert rec["channel"] == "email"
    assert rec["tags"] == []
    assert rec["blocked"] is False
    assert rec.get("duplicate") is not True


def test_add_full_record(p):
    rec = R.add(
        "John Smith", "Globex", kind="agency", agency="Talent Partners",
        channel="linkedin", handle="johnsmith-recruit",
        first_contact="2026-09-10", notes="Sourcing for ML roles.",
        tags=["ML", " warm ", "ml"], path=p,
    )
    assert rec["kind"] == "agency"
    assert rec["agency"] == "Talent Partners"
    assert rec["channel"] == "linkedin"
    assert rec["first_contact"] == "2026-09-10"
    assert rec["tags"] == ["ml", "warm"]


def test_add_requires_name_and_company(p):
    with pytest.raises(R.RecruiterError):
        R.add("", "Acme Corp", path=p)
    with pytest.raises(R.RecruiterError):
        R.add("   ", "Acme Corp", path=p)
    with pytest.raises(R.RecruiterError):
        R.add("Jane Doe", "", path=p)


def test_add_rejects_bad_kind_channel_date(p):
    with pytest.raises(R.RecruiterError):
        R.add("Jane Doe", "Acme Corp", kind="freelance", path=p)
    with pytest.raises(R.RecruiterError):
        R.add("Jane Doe", "Acme Corp", channel="pigeon", path=p)
    with pytest.raises(R.RecruiterError):
        R.add("Jane Doe", "Acme Corp", first_contact="10/09/2026", path=p)
    with pytest.raises(R.RecruiterError):
        R.add("Jane Doe", "Acme Corp", first_contact="2026-13-40", path=p)


def test_add_agency_requires_agency_name(p):
    with pytest.raises(R.RecruiterError):
        R.add("John Smith", "Globex", kind="agency", path=p)


def test_get_round_trip(p):
    added = R.add("Jane Doe", "Acme Corp", path=p)
    got = R.get(added["id"], path=p)
    assert got == added


def test_get_missing_id(p):
    with pytest.raises(R.RecruiterError):
        R.get(999, path=p)


def test_update_fields(p):
    rec = R.add("Jane Doe", "Acme Corp", path=p)
    out = R.update(rec["id"], notes="Replied quickly.", tags=["responsive"],
                   channel="phone", handle="+1-555-0100", path=p)
    assert out["notes"] == "Replied quickly."
    assert out["tags"] == ["responsive"]
    assert out["channel"] == "phone"
    assert out["handle"] == "+1-555-0100"


def test_update_rejects_bad_values(p):
    rec = R.add("Jane Doe", "Acme Corp", path=p)
    with pytest.raises(R.RecruiterError):
        R.update(rec["id"], kind="freelance", path=p)
    with pytest.raises(R.RecruiterError):
        R.update(rec["id"], name="  ", path=p)
    with pytest.raises(R.RecruiterError):
        R.update(rec["id"], kind="agency", path=p)  # no agency name


def test_update_to_existing_name_company_is_rejected(p):
    r1 = R.add("Jane Doe", "Acme Corp", path=p)
    r2 = R.add("John Smith", "Globex", path=p)
    with pytest.raises(R.RecruiterError):
        R.update(r2["id"], name=r1["name"], company=r1["company"], path=p)


def test_update_missing_id(p):
    with pytest.raises(R.RecruiterError):
        R.update(999, notes="x", path=p)


def test_delete(p):
    rec = R.add("Jane Doe", "Acme Corp", path=p)
    R.delete(rec["id"], path=p)
    assert R.list_recruiters(path=p) == []
    with pytest.raises(R.RecruiterError):
        R.delete(rec["id"], path=p)


# ---------------------------------------------------------------------------
# duplicate handling (mirrors tracker.py convention)
# ---------------------------------------------------------------------------

def test_duplicate_add_returns_existing_no_write(p):
    first = R.add("Jane Doe", "Acme Corp", notes="original", path=p)
    dup = R.add("  jane   DOE ", "acme corp", notes="changed", path=p)
    assert dup["duplicate"] is True
    assert dup["id"] == first["id"]
    assert dup["notes"] == "original"
    # only one record was ever written
    all_recs = R.list_recruiters(path=p)
    assert len(all_recs) == 1


def test_same_name_different_company_is_not_duplicate(p):
    r1 = R.add("Jane Doe", "Acme Corp", path=p)
    r2 = R.add("Jane Doe", "Globex", path=p)
    assert r2.get("duplicate") is not True
    assert r2["id"] != r1["id"]


# ---------------------------------------------------------------------------
# do-not-engage list
# ---------------------------------------------------------------------------

def test_block_unblock(p):
    rec = R.add("Spammy Sam", "SpamCo", path=p)
    blocked = R.block(rec["id"], "Sent 12 identical messages.", path=p)
    assert blocked["blocked"] is True
    assert blocked["blocked_reason"] == "Sent 12 identical messages."
    assert R.is_blocked("Spammy Sam", path=p) is True
    assert R.is_blocked("spammy sam", path=p) is True  # normalized

    unblocked = R.unblock(rec["id"], path=p)
    assert unblocked["blocked"] is False
    assert unblocked["blocked_reason"] == ""
    assert R.is_blocked("Spammy Sam", path=p) is False


def test_blocked_excluded_from_list_by_default(p):
    good = R.add("Jane Doe", "Acme Corp", path=p)
    bad = R.add("Spammy Sam", "SpamCo", path=p)
    R.block(bad["id"], "spam", path=p)

    visible = R.list_recruiters(path=p)
    assert [r["id"] for r in visible] == [good["id"]]

    with_blocked = R.list_recruiters(include_blocked=True, path=p)
    assert {r["id"] for r in with_blocked} == {good["id"], bad["id"]}


def test_is_blocked_unknown_name_is_false(p):
    assert R.is_blocked("Nobody Here", path=p) is False


def test_is_blocked_company_disambiguation(p):
    a = R.add("Jane Doe", "Acme Corp", path=p)
    R.add("Jane Doe", "Globex", path=p)
    R.block(a["id"], "spam", path=p)
    assert R.is_blocked("Jane Doe", path=p) is True  # any match blocked
    assert R.is_blocked("Jane Doe", company="Acme Corp", path=p) is True
    assert R.is_blocked("Jane Doe", company="Globex", path=p) is False


def test_is_blocked_requires_name(p):
    with pytest.raises(R.RecruiterError):
        R.is_blocked("", path=p)


def test_block_missing_id(p):
    with pytest.raises(R.RecruiterError):
        R.block(999, "nope", path=p)


def test_search_excludes_blocked_by_default(p):
    r1 = R.add("Jane Doe", "Acme Corp", path=p)
    R.add("Jane Doel", "SpamCo", path=p)
    R.block(2, "spam", path=p)
    assert [r["id"] for r in R.search_by_name("jane", path=p)] == [r1["id"]]
    assert len(R.search_by_name("jane", include_blocked=True, path=p)) == 2


# ---------------------------------------------------------------------------
# filters + search
# ---------------------------------------------------------------------------

def test_list_filters(p):
    R.add("Jane Doe", "Acme Corp", kind="inhouse", tags=["ml"], path=p)
    R.add("John Smith", "Acme Corp", kind="agency", agency="Talent Partners",
          tags=["infra"], path=p)
    R.add("Bob Ray", "Globex", kind="inhouse", tags=["ml"], path=p)

    assert {r["name"] for r in R.list_recruiters(kind="agency", path=p)} == {"John Smith"}
    assert {r["name"] for r in R.list_recruiters(company="acme", path=p)} == \
        {"Jane Doe", "John Smith"}
    assert {r["name"] for r in R.list_recruiters(tag="ML", path=p)} == \
        {"Jane Doe", "Bob Ray"}
    assert len(R.list_recruiters(kind="agency", tag="ml", path=p)) == 0
    with pytest.raises(R.RecruiterError):
        R.list_recruiters(kind="freelance", path=p)


def test_search_by_name(p):
    R.add("Jane Doe", "Acme Corp", path=p)
    R.add("Janet Field", "Globex", path=p)
    R.add("Bob Ray", "Initech", path=p)
    hits = R.search_by_name("  JAN  ", path=p)
    assert [r["name"] for r in hits] == ["Jane Doe", "Janet Field"]
    assert R.search_by_name("", path=p) == []
    assert R.search_by_name("zzz", path=p) == []


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------

def test_persistence_round_trip(p):
    R.add("Jane Doe", "Acme Corp", tags=["ml"], path=p)
    R.add("John Smith", "Globex", kind="agency", agency="Talent Partners", path=p)
    R.block(1, "ghosted twice", path=p)

    raw = json.loads(p.read_text(encoding="utf-8"))
    assert len(raw) == 2
    assert raw[0]["blocked"] is True
    assert raw[0]["blocked_reason"] == "ghosted twice"

    again = R.list_recruiters(include_blocked=True, path=p)
    assert len(again) == 2
    assert again[0]["tags"] == ["ml"]
    assert again[1]["agency"] == "Talent Partners"


def test_invalid_json_raises(p):
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(R.RecruiterError):
        R.list_recruiters(path=p)


def test_non_list_json_raises(p):
    p.write_text('{"a": 1}', encoding="utf-8")
    with pytest.raises(R.RecruiterError):
        R.list_recruiters(path=p)


def test_default_path_honors_candid_data_dir(monkeypatch, tmp_path):
    """Without path=, storage uses CANDID_DATA_DIR / recruiters.json."""
    import importlib
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    importlib.reload(C)
    rec = R.add("Jane Doe", "Acme Corp")
    assert (tmp_path / "recruiters.json").exists()
    assert rec["name"] == "Jane Doe"
    monkeypatch.undo()
    importlib.reload(C)


def test_render_list(p):
    R.add("Jane Doe", "Acme Corp", path=p)
    bad = R.add("Spammy Sam", "SpamCo", path=p)
    R.block(bad["id"], "spam", path=p)
    text = R.render_list(R.list_recruiters(include_blocked=True, path=p))
    assert "Jane Doe" in text
    assert "Spammy Sam" in text
    assert "spam" in text
    assert R.render_list([]) == "No recruiters tracked yet."

"""Tests for candid.notify_reminders (due-notification collection)."""
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import notify_reminders as R  # noqa: E402
from candid import tracker as T  # noqa: E402

NOW = datetime(2026, 9, 22, 12, 0)  # a Tuesday noon


def make_app(id_, company, role, status, notes, date_updated="2026-09-20"):
    return {
        "id": id_, "company": company, "role": role, "status": status,
        "notes": notes, "date_added": "2026-09-01",
        "date_updated": date_updated, "jd_link": "", "prep_pack": "",
    }


@pytest.fixture
def apps(monkeypatch):
    """Redirect tracker.list_apps to a fabricated list."""
    def use(apps_list):
        monkeypatch.setattr(T, "list_apps", lambda *a, **k: apps_list)
    return use


@pytest.fixture
def fake_notify(monkeypatch):
    """Stand-in for candid.notify (worker A's module may not be present)."""
    sent = set()
    calls = []
    mod = types.ModuleType("candid.notify")
    mod.was_sent = lambda nid: nid in sent
    def notify(title, body, category="general", urgency="normal"):
        calls.append({"title": title, "body": body,
                      "category": category, "urgency": urgency})
    mod.notify = notify
    mod.mark_sent = lambda nid: sent.add(nid)
    monkeypatch.setitem(sys.modules, "candid.notify", mod)
    # Drop the real-module attribute the import system sets on the `candid`
    # package (e.g. by other test modules importing it first), so that
    # `from candid import notify` inside notify_reminders resolves through
    # sys.modules and picks up this fake. Restored by monkeypatch.
    import candid
    monkeypatch.delattr(candid, "notify", raising=False)
    return {"sent": sent, "calls": calls}


@pytest.fixture
def no_notify(monkeypatch):
    """Simulate notify.py being momentarily absent.

    `from candid import notify` inside notify_reminders goes through the
    real import machinery, so patching importlib.import_module does not
    intercept it. Instead, install a meta-path finder that raises
    ImportError for "candid.notify", and also remove any already-imported
    "candid.notify" from sys.modules plus the attribute the import system
    sets on the `candid` package. monkeypatch restores all of it in
    teardown, so other tests are unaffected.
    """
    import importlib.abc
    import candid

    class _BlockNotifyFinder(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path, target=None):
            if name == "candid.notify":
                raise ImportError(
                    "No module named 'candid.notify' (simulated absence)")
            return None

    monkeypatch.setattr(sys, "meta_path",
                        [_BlockNotifyFinder()] + sys.meta_path)
    monkeypatch.delitem(sys.modules, "candid.notify", raising=False)
    monkeypatch.delattr(candid, "notify", raising=False)
    return None


# --- interview windows --------------------------------------------------------

def test_interview_tomorrow_24h_only(apps):
    apps([make_app("a1", "Acme", "SWE", "selected_for_interview",
                   "Onsite interview Sep 23 2026")])
    out = R.interview_reminders(NOW)
    ids = [i["id"] for i in out]
    assert ids == ["interview-a1-2026-09-23-24h"]
    assert out[0]["urgency"] == "normal"
    assert out[0]["category"] == "interviews"
    assert out[0]["title"].startswith("Interview tomorrow: Acme - SWE")


def test_interview_within_1h_adds_1h_variant(apps):
    apps([make_app("a1", "Acme", "SWE", "selected_for_interview",
                   "Interview Sep 22 2026 at 12:30pm")])
    out = R.interview_reminders(NOW)
    ids = sorted(i["id"] for i in out)
    assert ids == ["interview-a1-2026-09-22-1h",
                   "interview-a1-2026-09-22-24h"]
    by_id = {i["id"]: i for i in out}
    assert by_id["interview-a1-2026-09-22-24h"]["urgency"] == "high"
    assert by_id["interview-a1-2026-09-22-1h"]["urgency"] == "high"
    assert by_id["interview-a1-2026-09-22-24h"]["title"].startswith(
        "Interview today: Acme - SWE")


def test_interview_same_day_no_time_is_high(apps):
    apps([make_app("a1", "Acme", "SWE", "selected_for_interview",
                   "Interview on 2026-09-22")])
    out = R.interview_reminders(NOW)
    assert len(out) == 2  # -24h + -1h, same-day unknown time is treated loud
    assert all(i["urgency"] == "high" for i in out)


def test_interview_far_future_or_wrong_status(apps):
    apps([
        make_app("a1", "Acme", "SWE", "selected_for_interview",
                 "Interview Oct 30 2026"),
        make_app("a2", "Beta", "MLE", "applied",
                 "Interview Sep 23 2026"),  # wrong status: ignored
        make_app("a3", "Gamma", "DS", "selected_for_interview",
                 "no dates here at all"),
    ])
    assert R.interview_reminders(NOW) == []


def test_interview_duplicate_dates_deduped(apps):
    apps([make_app("a1", "Acme", "SWE", "selected_for_interview",
                   "Sep 23 2026 ... confirmed for Sep 23 2026")])
    out = R.interview_reminders(NOW)
    assert [i["id"] for i in out] == ["interview-a1-2026-09-23-24h"]


# --- deadline reminders -------------------------------------------------------

def test_deadline_within_days(apps):
    apps([make_app("a1", "Acme", "SWE", "applied",
                   "Apply soon. Application deadline: Sep 24 2026")])
    out = R.deadline_reminders(NOW, days=3)
    assert len(out) == 1
    assert out[0]["id"] == "deadline-a1-2026-09-24"
    assert out[0]["category"] == "deadlines"


def test_deadline_outside_window_or_past(apps):
    apps([
        make_app("a1", "Acme", "SWE", "applied",
                 "deadline: Oct 10 2026"),
        make_app("a2", "Beta", "MLE", "applied",
                 "This posting closes Sep 10 2026"),  # past
        make_app("a3", "Gamma", "DS", "applied",
                 "apply by: sometime soonish"),  # unparsable
    ])
    assert R.deadline_reminders(NOW, days=3) == []


# --- followup reminders -------------------------------------------------------

def test_followup_mapping(apps):
    apps([make_app("a1", "Acme Corp", "SWE", "applied",
                   "nothing", date_updated="2026-08-01")])
    out = R.followup_reminders(NOW)
    assert len(out) == 1
    n = out[0]
    assert n["id"] == "followup-quiet_applied-acme-corp"
    assert n["category"] == "followups"
    assert set(n) == {"id", "title", "body", "category", "urgency"}


# --- collect_due: dedup + was_sent --------------------------------------------

def test_collect_due_filters_sent_and_dedupes(apps, fake_notify):
    apps([make_app("a1", "Acme", "SWE", "selected_for_interview",
                   "Interview Sep 23 2026; Sep 23 2026 again")])
    first = R.collect_due(NOW)
    # interview reminder + the interview_soon follow-up nudge for the same app
    ids = [i["id"] for i in first]
    assert "interview-a1-2026-09-23-24h" in ids
    assert "followup-interview_soon-acme" in ids
    assert len(ids) == len(set(ids))  # deduped by id
    for nid in ids:
        fake_notify["sent"].add(nid)
    assert R.collect_due(NOW) == []


def test_deliver_due_calls_notify_and_marks_sent(apps, fake_notify):
    apps([
        make_app("a1", "Acme", "SWE", "selected_for_interview",
                 "Interview Sep 23 2026"),
        make_app("a2", "Beta", "MLE", "applied",
                 "deadline: Sep 24 2026"),
    ])
    n = R.deliver_due(NOW)
    # interview-24h + interview_soon followup (a1), deadline + interview_soon
    # followup (a2's "deadline: Sep 24 2026" also parses as an interview date)
    assert n == 4
    assert len(fake_notify["calls"]) == 4
    for c in fake_notify["calls"]:
        assert set(c) == {"title", "body", "category", "urgency"}
    assert fake_notify["sent"] == {
        "interview-a1-2026-09-23-24h", "followup-interview_soon-acme",
        "deadline-a2-2026-09-24", "followup-interview_soon-beta"}
    # second run: everything already sent
    assert R.deliver_due(NOW) == 0
    assert len(fake_notify["calls"]) == 4


def test_deliver_due_survives_notify_failure(apps, fake_notify, monkeypatch):
    apps([make_app("a1", "Acme", "SWE", "selected_for_interview",
                   "Interview Sep 23 2026"),
          make_app("a2", "Beta", "MLE", "applied",
                   "deadline: Sep 24 2026")])
    real_notify = sys.modules["candid.notify"].notify

    def flaky(title, body, category="general", urgency="normal"):
        if "interview" in title.lower():
            raise RuntimeError("boom")
        real_notify(title, body, category=category, urgency=urgency)

    monkeypatch.setattr(sys.modules["candid.notify"], "notify", flaky)
    assert R.deliver_due(NOW) == 1  # failed one skipped, other delivered
    assert fake_notify["sent"] == {"deadline-a2-2026-09-24"}


# --- notify absent ------------------------------------------------------------

def test_collect_and_deliver_without_notify_module(apps, no_notify):
    apps([make_app("a1", "Acme", "SWE", "selected_for_interview",
                   "Interview Sep 23 2026")])
    out = R.collect_due(NOW)  # no was_sent info -> include everything
    ids = [i["id"] for i in out]
    assert "interview-a1-2026-09-23-24h" in ids
    assert "followup-interview_soon-acme" in ids
    assert R.deliver_due(NOW) == 0  # nowhere to deliver -> 0, no raise


# --- watchlist ----------------------------------------------------------------

def test_watchlist_absent_returns_empty(monkeypatch):
    monkeypatch.delitem(sys.modules, "candid.watchlist", raising=False)
    assert R.watchlist_alerts() == []


def test_watchlist_present_but_broken(monkeypatch):
    mod = types.ModuleType("candid.watchlist")

    def new_matches():
        raise RuntimeError("watchlist exploded")
    mod.new_matches = new_matches
    monkeypatch.setitem(sys.modules, "candid.watchlist", mod)
    assert R.watchlist_alerts() == []


def test_watchlist_present_with_matches(monkeypatch):
    mod = types.ModuleType("candid.watchlist")
    mod.new_matches = lambda: [{"company": "Acme",
                                "title": "SWE",
                                "url": "https://example.com/j"}]
    monkeypatch.setitem(sys.modules, "candid.watchlist", mod)
    out = R.watchlist_alerts()
    assert len(out) == 1
    assert out[0]["category"] == "watchlist"
    assert out[0]["id"].startswith("watchlist-")


# --- never raise on garbage ----------------------------------------------------

@pytest.mark.parametrize("notes", [
    None, "", "🍕🚀", "deadline: blah blah blah", 123,
    "Interview on the 32nd of Never 2026 at 99:99pm",
    "due: ;;; closes: ??? apply by: --",
])
def test_never_raise_on_garbage_notes(apps, fake_notify, notes):
    apps([make_app("a1", "Acme", "SWE", "selected_for_interview", notes),
          make_app("a2", "Beta", "MLE", "applied", notes)])
    R.interview_reminders(NOW)
    R.deadline_reminders(NOW)
    R.followup_reminders(NOW)
    R.collect_due(NOW)
    R.deliver_due(NOW)


def test_broken_tracker_never_raises(monkeypatch):
    monkeypatch.setattr(T, "list_apps", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("tracker down")))
    R.interview_reminders(NOW)
    R.deadline_reminders(NOW)
    R.followup_reminders(NOW)
    assert R.collect_due(NOW) == []


def test_notification_shape(apps, fake_notify):
    apps([make_app("a1", "Acme", "SWE", "selected_for_interview",
                   "Interview Sep 23 2026 at 10am")])
    for item in R.collect_due(NOW):
        assert set(item) == {"id", "title", "body", "category", "urgency"}
        assert all(isinstance(item[k], str) and item[k]
                   for k in ("id", "title", "body", "category", "urgency"))

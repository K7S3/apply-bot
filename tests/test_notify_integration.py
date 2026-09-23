"""End-to-end integration tests for `candid notify`.

Runs the real CLI (`candid.__main__.main`) against isolated tmp config and
data dirs (the in-process equivalent of CANDID_CONFIG_DIR / CANDID_DATA_DIR
overrides) with the OS backend mocked by patching subprocess in
candid.notify. Tracker data is seeded through the tmp data dir. No real
desktop notifications are ever sent.
"""
import io
import json
import sys
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402
from candid import notify as N  # noqa: E402


@pytest.fixture
def iso(tmp_path, monkeypatch):
    """Isolated config/data dirs, mocked OS backend, clean package state."""
    cfg = tmp_path / "config"
    data = tmp_path / "data"
    cfg.mkdir()
    data.mkdir()
    tracker_path = data / "tracker.json"
    tracker_path.write_text("[]", encoding="utf-8")

    # tmp CANDID_CONFIG_DIR / CANDID_DATA_DIR, applied both as env vars and
    # as the already-imported config module's attributes (config.py resolves
    # the env vars once at import time).
    monkeypatch.setenv("CANDID_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("CANDID_DATA_DIR", str(data))
    monkeypatch.setattr(C, "CONFIG_DIR", cfg)
    monkeypatch.setattr(C, "DATA_DIR", data)
    monkeypatch.setattr(C, "TRACKER_PATH", tracker_path)

    backend_calls = []

    def fake_run(cmd, **kwargs):
        backend_calls.append(list(cmd))
        return mock.Mock(returncode=0)

    # Mocked OS backend: pretend notify-send exists and capture its calls.
    monkeypatch.setattr(N.subprocess, "run", fake_run)
    monkeypatch.setattr(N.shutil, "which", lambda name: "/usr/bin/" + name)

    # Default to no quiet window (start == end) so delivery tests are
    # deterministic regardless of wall-clock time; tests that need quiet
    # hours opt in explicitly.
    N.set_pref("quiet_start", "00:00")
    N.set_pref("quiet_end", "00:00")

    yield SimpleNamespace(cfg=cfg, data=data, tracker=tracker_path,
                          backend_calls=backend_calls)

    # Importing candid.notify leaves a `notify` attribute on the `candid`
    # package; remove it so other test modules that simulate notify being
    # absent keep working.
    import candid
    try:
        del candid.notify
    except AttributeError:
        pass


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def cli(*argv) -> str:
    """Run the real CLI and return its stdout."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        CLI.main(list(argv))
    return buf.getvalue()


def seed_tracker(iso, apps: list[dict]) -> None:
    iso.tracker.write_text(json.dumps(apps), encoding="utf-8")


def interview_app(app_id="a1", company="Acme", days_ahead=1) -> dict:
    day = date.today() + timedelta(days=days_ahead)
    return {
        "id": app_id, "company": company, "role": "SWE",
        "status": "selected_for_interview",
        "notes": f"Onsite interview {day.strftime('%b %d, %Y')}.",
        "date_added": (date.today() - timedelta(days=10)).isoformat(),
        "date_updated": date.today().isoformat(),
        "jd_link": "", "prep_pack": "",
    }


def stale_applied_app(app_id="b1", company="Beta", days_ago=30) -> dict:
    day = date.today() - timedelta(days=days_ago)
    return {
        "id": app_id, "company": company, "role": "DS",
        "status": "applied",
        "notes": "Applied via the careers page.",
        "date_added": day.isoformat(),
        "date_updated": day.isoformat(),
        "jd_link": "", "prep_pack": "",
    }


def queue_records(iso) -> list:
    p = iso.cfg / "notify_queue.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def set_quiet_around_now(iso) -> None:
    """Set a quiet window covering right now via the CLI."""
    now = datetime.now()
    qs = (now - timedelta(hours=1)).strftime("%H:%M")
    qe = (now + timedelta(hours=1)).strftime("%H:%M")
    cli("notify", "prefs", "--set", f"quiet_start={qs}",
        "--set", f"quiet_end={qe}")


def clear_quiet(iso) -> None:
    """Disable the quiet window (start == end means no quiet hours)."""
    cli("notify", "prefs", "--set", "quiet_start=00:00",
        "--set", "quiet_end=00:00")


# ---------------------------------------------------------------------------
# notify due: list + deliver + dedup
# ---------------------------------------------------------------------------

def test_due_lists_due_interview_reminders(iso):
    seed_tracker(iso, [interview_app()])
    out = cli("notify", "due")
    assert "Interview tomorrow: Acme - SWE" in out
    # the same app also yields an interview_soon follow-up nudge
    assert "Interview coming up: Acme" in out
    assert iso.backend_calls == []  # listing alone never touches the backend


def test_due_deliver_sends_and_marks_sent(iso):
    seed_tracker(iso, [interview_app()])
    day = (date.today() + timedelta(days=1)).isoformat()
    out = cli("notify", "due", "--deliver")
    assert "[sent]" in out
    assert f"Sent 2 of 2 due item(s)." in out
    # the mocked OS backend was actually invoked
    assert iso.backend_calls
    assert all(c[0] == "notify-send" for c in iso.backend_calls)
    # both reminder ids are recorded as sent
    assert N.was_sent(f"interview-a1-{day}-24h")
    assert N.was_sent("followup-interview_soon-acme")


def test_due_second_run_delivers_nothing_dedup(iso):
    seed_tracker(iso, [interview_app()])
    cli("notify", "due", "--deliver")
    iso.backend_calls.clear()
    out = cli("notify", "due", "--deliver")
    assert "Nothing due right now." in out
    assert "Sent 0 of 0 due item(s)." in out
    assert iso.backend_calls == []


def test_due_nothing_due_message(iso):
    out = cli("notify", "due")
    assert "Nothing due right now." in out


# ---------------------------------------------------------------------------
# quiet hours: queue now, flush later
# ---------------------------------------------------------------------------

def test_send_during_quiet_hours_queues_instead(iso):
    set_quiet_around_now(iso)
    out = cli("notify", "send", "--title", "Hello", "--body", "World")
    assert "queued" in out
    assert iso.backend_calls == []
    queued = queue_records(iso)
    assert len(queued) == 1
    assert queued[0]["title"] == "Hello"


def test_flush_after_quiet_hours_delivers_queued(iso):
    set_quiet_around_now(iso)
    cli("notify", "send", "--title", "Hello", "--body", "World")
    assert len(queue_records(iso)) == 1
    clear_quiet(iso)
    out = cli("notify", "flush")
    assert "Delivered: Hello" in out
    assert "Delivered 1 queued notification(s)." in out
    assert len(iso.backend_calls) == 1
    assert queue_records(iso) == []


def test_due_deliver_during_quiet_queues_then_flush_delivers(iso):
    seed_tracker(iso, [interview_app()])
    set_quiet_around_now(iso)
    out = cli("notify", "due", "--deliver")
    assert "[queued/skipped]" in out
    assert "Sent 0 of 2 due item(s)." in out
    assert iso.backend_calls == []
    assert len(queue_records(iso)) == 2
    clear_quiet(iso)
    out = cli("notify", "flush")
    assert "Delivered 2 queued notification(s)." in out
    assert len(iso.backend_calls) == 2


# ---------------------------------------------------------------------------
# snooze
# ---------------------------------------------------------------------------

def test_snooze_queues_send_unsnooze_flush_delivers(iso):
    out = cli("notify", "snooze", "--for", "1h")
    assert "Snoozed until" in out
    out = cli("notify", "send", "--title", "Ping", "--body", "Pong")
    assert "queued" in out
    assert iso.backend_calls == []
    out = cli("notify", "unsnooze")
    assert "Snooze cleared." in out
    out = cli("notify", "flush")
    assert "Delivered 1 queued notification(s)." in out
    assert len(iso.backend_calls) == 1


# ---------------------------------------------------------------------------
# disabled category / master switch
# ---------------------------------------------------------------------------

def test_disabled_category_followups_skipped_not_queued(iso):
    seed_tracker(iso, [stale_applied_app()])  # -> quiet_applied, "followups"
    cli("notify", "prefs", "--set", "categories.followups=false")
    out = cli("notify", "due", "--deliver")
    assert "[queued/skipped]" in out
    assert "Sent 0 of 1 due item(s)." in out
    # disabled categories are skipped outright: no backend call, no queue
    # entry, and the reminder is NOT marked sent.
    assert iso.backend_calls == []
    assert queue_records(iso) == []
    assert not N.was_sent("followup-quiet_applied-beta")


def test_master_switch_disabled_send_skips(iso):
    cli("notify", "prefs", "--set", "enabled=false")
    out = cli("notify", "send", "--title", "T", "--body", "B")
    assert "skipped" in out
    assert iso.backend_calls == []
    assert queue_records(iso) == []


# ---------------------------------------------------------------------------
# misc flows
# ---------------------------------------------------------------------------

def test_send_delivers_immediately_outside_quiet(iso):
    out = cli("notify", "send", "--title", "Hi", "--body", "Yo")
    assert "delivered" in out
    assert iso.backend_calls == [
        ["notify-send", "--urgency=normal", "Hi", "Yo"]]
    assert queue_records(iso) == []


def test_flush_empty_queue(iso):
    out = cli("notify", "flush")
    assert "Delivered 0 queued notification(s)." in out


def test_prefs_set_quiet_hours_roundtrip(iso):
    cli("notify", "prefs", "--set", "quiet_start=23:00",
        "--set", "quiet_end=07:30")
    prefs = json.loads(cli("notify", "prefs"))
    assert prefs["quiet_start"] == "23:00"
    assert prefs["quiet_end"] == "07:30"
    assert N.is_quiet(datetime.now().replace(hour=2, minute=0))
    assert not N.is_quiet(datetime.now().replace(hour=12, minute=0))

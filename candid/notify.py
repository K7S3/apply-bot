"""Cross-platform desktop notification engine for candid.

Public API (used by candid.notify_reminders and the `candid notify` CLI):

    notify(title, body, *, category="general", urgency="normal") -> bool
    get_prefs() -> dict
    save_prefs(prefs) -> None
    set_pref(key, value) -> dict
    is_quiet(dt=None) -> bool
    snooze(duration: timedelta) -> datetime
    snoozed_until() -> datetime | None
    clear_snooze() -> None
    queue_notification(title, body, category="general", urgency="normal") -> dict
    flush_queue() -> list[dict]
    mark_sent(notification_id: str) -> None
    was_sent(notification_id: str) -> bool

Behavior: a notification is delivered only when notifications are enabled,
its category is enabled, we are outside quiet hours, and we are not snoozed.
Otherwise it is queued for later (flush_queue) or skipped outright when the
category / master switch is disabled. All OS backend calls use subprocess
with a timeout and never raise out of notify().
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta

from candid import config as _config

#: Categories with per-category enable flags in prefs.
CATEGORIES = ("interviews", "deadlines", "followups", "watchlist", "system")

URGENCIES = ("low", "normal", "critical")

#: Sent-log entries older than this are pruned.
SENT_LOG_TTL = timedelta(days=30)

_BACKEND_TIMEOUT = 10


def _prefs_path():
    return _config.CONFIG_DIR / "notify.json"


def _queue_path():
    return _config.CONFIG_DIR / "notify_queue.json"


def _sent_path():
    return _config.CONFIG_DIR / "notify_sent.json"


def _default_prefs() -> dict:
    return {
        "enabled": True,
        "quiet_start": "22:00",
        "quiet_end": "08:00",
        "categories": {c: True for c in CATEGORIES},
        "snoozed_until": None,
    }


def _read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# preferences
# ---------------------------------------------------------------------------

def get_prefs() -> dict:
    """Load notification prefs, merged over defaults."""
    prefs = _default_prefs()
    stored = _read_json(_prefs_path(), {})
    if isinstance(stored, dict):
        prefs.update(stored)
        cats = _default_prefs()["categories"]
        if isinstance(stored.get("categories"), dict):
            cats.update(stored["categories"])
        prefs["categories"] = cats
    return prefs


def save_prefs(prefs: dict) -> None:
    """Persist the full prefs dict."""
    _write_json(_prefs_path(), prefs)


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _parse_hhmm(value: str) -> tuple[int, int]:
    try:
        hh, mm = value.strip().split(":")
        h, m = int(hh), int(mm)
    except (ValueError, AttributeError):
        raise ValueError(f"Bad time {value!r}: expected HH:MM (24h)")
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Bad time {value!r}: expected HH:MM (24h)")
    return h, m


def set_pref(key: str, value) -> dict:
    """Set one pref and persist. Returns the updated prefs dict.

    Keys: enabled, quiet_start, quiet_end, categories.<name>.
    """
    prefs = get_prefs()
    if key == "enabled":
        prefs["enabled"] = _coerce_bool(value)
    elif key in ("quiet_start", "quiet_end"):
        h, m = _parse_hhmm(str(value))
        prefs[key] = f"{h:02d}:{m:02d}"
    elif key.startswith("categories."):
        name = key.split(".", 1)[1]
        if name not in CATEGORIES:
            raise ValueError(
                f"Unknown category {name!r}; expected one of {', '.join(CATEGORIES)}")
        prefs["categories"][name] = _coerce_bool(value)
    else:
        raise ValueError(
            "Unknown pref key {!r}; expected enabled, quiet_start, quiet_end, "
            "or categories.<name>".format(key))
    save_prefs(prefs)
    return prefs


# ---------------------------------------------------------------------------
# quiet hours / snooze
# ---------------------------------------------------------------------------

def is_quiet(dt: datetime | None = None) -> bool:
    """True when dt (default: now) falls inside the quiet-hours window.

    Handles overnight windows (e.g. 22:00-08:00). When start == end there
    is no quiet window.
    """
    dt = dt or datetime.now()
    prefs = get_prefs()
    try:
        sh, sm = _parse_hhmm(prefs.get("quiet_start", "22:00"))
        eh, em = _parse_hhmm(prefs.get("quiet_end", "08:00"))
    except ValueError:
        return False
    start, end = (sh, sm), (eh, em)
    if start == end:
        return False
    now = (dt.hour, dt.minute)
    if start < end:
        return start <= now < end
    return now >= start or now < end


def snooze(duration: timedelta) -> datetime:
    """Snooze notifications for `duration` from now. Returns the end time."""
    until = datetime.now() + duration
    prefs = get_prefs()
    prefs["snoozed_until"] = until.isoformat(timespec="seconds")
    save_prefs(prefs)
    return until


def snoozed_until() -> datetime | None:
    """Return the active snooze end time, or None if not snoozed."""
    raw = get_prefs().get("snoozed_until")
    if not raw:
        return None
    try:
        until = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if until <= datetime.now():
        clear_snooze()
        return None
    return until


def clear_snooze() -> None:
    """Cancel any active snooze."""
    prefs = get_prefs()
    prefs["snoozed_until"] = None
    save_prefs(prefs)


def _snoozed() -> bool:
    return snoozed_until() is not None


# ---------------------------------------------------------------------------
# queue
# ---------------------------------------------------------------------------

def _read_queue() -> list[dict]:
    data = _read_json(_queue_path(), [])
    return data if isinstance(data, list) else []


def queue_notification(title: str, body: str, category: str = "general",
                       urgency: str = "normal") -> dict:
    """Append a notification to the pending queue. Returns the record."""
    record = {
        "id": uuid.uuid4().hex,
        "title": title,
        "body": body,
        "category": category,
        "urgency": _norm_urgency(urgency),
        "queued_at": datetime.now().isoformat(timespec="seconds"),
    }
    queue = _read_queue()
    queue.append(record)
    _write_json(_queue_path(), queue)
    return record


def flush_queue() -> list[dict]:
    """Deliver queued notifications when not quiet/snoozed.

    Returns the records that were delivered. Items that fail to deliver
    stay in the queue.
    """
    if is_quiet() or _snoozed():
        return []
    queue = _read_queue()
    delivered: list[dict] = []
    remaining: list[dict] = []
    for record in queue:
        if _deliver(record["title"], record["body"], record.get("urgency", "normal")):
            mark_sent(record["id"])
            delivered.append(record)
        else:
            remaining.append(record)
    _write_json(_queue_path(), remaining)
    return delivered


# ---------------------------------------------------------------------------
# dedup log
# ---------------------------------------------------------------------------

def _read_sent() -> dict:
    data = _read_json(_sent_path(), {})
    return data if isinstance(data, dict) else {}


def _prune_sent(sent: dict) -> dict:
    cutoff = datetime.now() - SENT_LOG_TTL
    pruned = {}
    for nid, raw in sent.items():
        try:
            ts = datetime.fromisoformat(raw)
        except (ValueError, TypeError):
            continue
        if ts >= cutoff:
            pruned[nid] = raw
    return pruned


def mark_sent(notification_id: str) -> None:
    """Record a notification id as delivered (prunes entries older than 30 days)."""
    sent = _prune_sent(_read_sent())
    sent[notification_id] = datetime.now().isoformat(timespec="seconds")
    _write_json(_sent_path(), sent)


def was_sent(notification_id: str) -> bool:
    """True if the id was recorded as sent and is still within the 30-day window."""
    sent = _prune_sent(_read_sent())
    return notification_id in sent


# ---------------------------------------------------------------------------
# OS backends
# ---------------------------------------------------------------------------

def _norm_urgency(urgency: str) -> str:
    u = str(urgency).lower()
    return u if u in URGENCIES else "normal"


def _run(cmd: list[str]) -> bool:
    """Run a backend command; True on success, False on any failure."""
    try:
        subprocess.run(cmd, timeout=_BACKEND_TIMEOUT, check=True,
                       capture_output=True)
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def _applescript_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _notify_macos(title: str, body: str, urgency: str) -> bool:
    # Prefer terminal-notifier when installed; it supports icons and actions.
    if shutil.which("terminal-notifier"):
        return _run(["terminal-notifier", "-title", title, "-message", body])
    if not shutil.which("osascript"):
        return False
    script = ('display notification "{}" with title "{}"'.format(
        _applescript_escape(body), _applescript_escape(title)))
    return _run(["osascript", "-e", script])


def _notify_linux(title: str, body: str, urgency: str) -> bool:
    if shutil.which("notify-send"):
        return _run(["notify-send", f"--urgency={urgency}", title, body])
    if shutil.which("gdbus"):
        return _run([
            "gdbus", "call", "--session",
            "--dest", "org.freedesktop.Notifications",
            "--object-path", "/org/freedesktop/Notifications",
            "--method", "org.freedesktop.Notifications.Notify",
            "candid", "0", "", title, body, "[]", "{}", "5000",
        ])
    return False


def _notify_windows(title: str, body: str, urgency: str) -> bool:
    try:
        from winsdk.windows.data.xml.dom import XmlDocument
        from winsdk.windows.ui.notifications import (
            ToastNotification, ToastNotificationManager)
    except ImportError:
        return False
    try:
        xml = f"""<toast><visual><binding template="ToastGeneric">""" \
              f"""<text>{_xml_escape(title)}</text>""" \
              f"""<text>{_xml_escape(body)}</text>""" \
              f"""</binding></visual></toast>"""
        doc = XmlDocument()
        doc.load_xml(xml)
        notifier = ToastNotificationManager.create_toast_notifier("candid")
        notifier.show(ToastNotification(doc))
        return True
    except Exception:
        return False


def _xml_escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def _backend() -> str:
    """Platform key for the backend in use (for tests/introspection)."""
    sys_platform = platform.system().lower()
    if sys_platform == "darwin":
        return "macos"
    if sys_platform == "windows":
        return "windows"
    if sys_platform == "linux":
        return "linux"
    return "unsupported"


def _deliver(title: str, body: str, urgency: str = "normal") -> bool:
    """Attempt OS delivery. Returns True on success, False otherwise."""
    urgency = _norm_urgency(urgency)
    backend = _backend()
    try:
        if backend == "macos":
            return _notify_macos(title, body, urgency)
        if backend == "linux":
            return _notify_linux(title, body, urgency)
        if backend == "windows":
            return _notify_windows(title, body, urgency)
        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------

def notify(title: str, body: str, *, category: str = "general",
           urgency: str = "normal") -> bool:
    """Send a desktop notification.

    Returns True when the notification was delivered to the OS. Returns
    False (and queues for later) when quiet hours or a snooze are active,
    or when the OS backend fails. Returns False without queueing when
    notifications are disabled or the category is disabled.
    """
    prefs = get_prefs()
    if not prefs.get("enabled", True):
        return False
    if not prefs.get("categories", {}).get(category, True):
        return False
    if is_quiet() or _snoozed():
        queue_notification(title, body, category=category, urgency=urgency)
        return False
    try:
        delivered = _deliver(title, body, urgency)
    except Exception:
        delivered = False
    if delivered:
        return True
    queue_notification(title, body, category=category, urgency=urgency)
    return False

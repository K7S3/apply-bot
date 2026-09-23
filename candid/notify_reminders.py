"""Due-reminder collection for OS-native notifications.

Gathers due notifications from candid data sources (tracker notes,
nudges, an optional watchlist module) and hands them to candid.notify
for delivery.

Every collector is pure and fully defensive: unparsable text, missing
modules, and malformed tracker records can never raise. candid.notify
is imported lazily (inside functions) so this module imports cleanly
even when candid/notify.py is momentarily absent.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time

from candid import nudges as _nudges
from candid import tracker as _tracker

HIGH, NORMAL, LOW = "high", "normal", "low"


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def _as_now(now) -> datetime:
    """Normalize the `now` argument to a datetime. Never raises."""
    if isinstance(now, datetime):
        return now
    if isinstance(now, date):
        return datetime(now.year, now.month, now.day)
    try:
        return datetime.now()
    except Exception:
        return datetime(2000, 1, 1)


def _safe_apps() -> list[dict]:
    try:
        apps = _tracker.list_apps()
    except Exception:
        return []
    if not isinstance(apps, list):
        return []
    return [a for a in apps if isinstance(a, dict)]


def _scan_interview_dates(app: dict) -> list[date]:
    """Defensive import of candid.nudges._scan_text_for_interview_dates."""
    try:
        from candid.nudges import _scan_text_for_interview_dates as scan
    except ImportError:
        return []
    try:
        out = scan(app)
    except Exception:
        return []
    return [d for d in (out or []) if isinstance(d, date)]


def _safe_extract_dates(text: str) -> list[date]:
    """Reuse nudges' date extraction; [] on any failure."""
    try:
        from candid.nudges import _extract_dates as extract
    except ImportError:
        return []
    try:
        out = extract(text or "")
    except Exception:
        return []
    return [d for d in (out or []) if isinstance(d, date)]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def _extract_times(text: str) -> list[time]:
    """Pull times-of-day out of free text. Never raises."""
    out: list[time] = []
    t = text or ""
    try:
        for m in re.finditer(r"\b(\d{1,2}):(\d{2})\s*([ap])\.?m\.?\b", t, re.I):
            h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3).lower()
            if ap == "p" and h < 12:
                h += 12
            if ap == "a" and h == 12:
                h = 0
            if 0 <= h <= 23 and 0 <= mi <= 59:
                out.append(time(h, mi))
        for m in re.finditer(r"\b(\d{1,2})\s*([ap])\.?m\.?\b", t, re.I):
            h, ap = int(m.group(1)), m.group(2).lower()
            if not 1 <= h <= 12:
                continue
            if ap == "p" and h < 12:
                h += 12
            if ap == "a" and h == 12:
                h = 0
            out.append(time(h, 0))
        for m in re.finditer(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", t):
            out.append(time(int(m.group(1)), int(m.group(2))))
    except Exception:
        pass
    seen, uniq = set(), []
    for tm in out:
        key = (tm.hour, tm.minute)
        if key not in seen:
            seen.add(key)
            uniq.append(tm)
    return uniq


def _dedupe(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        nid = it.get("id") if isinstance(it, dict) else None
        if not nid or nid in seen:
            continue
        seen.add(nid)
        out.append(it)
    return out


def _was_sent(nid: str) -> bool:
    """True if candid.notify reports this id as already sent. Never raises."""
    try:
        from candid import notify as notify_mod
        fn = getattr(notify_mod, "was_sent", None)
        return bool(fn(nid)) if callable(fn) else False
    except Exception:
        return False


# --------------------------------------------------------------------------
# 1. interview reminders
# --------------------------------------------------------------------------

def interview_reminders(now=None) -> list[dict]:
    """Reminders for interviews in the next 24h (status selected_for_interview).

    Emits id ``interview-<app_id>-<date>-24h`` for each interview date within
    the next 24h, plus a sharper ``-1h`` variant when the interview is
    imminent (<= 1h, or same-day when no time-of-day could be parsed).
    """
    now_dt = _as_now(now)
    today = now_dt.date()
    out: list[dict] = []
    for app in _safe_apps():
        try:
            if (app.get("status") or "") != "selected_for_interview":
                continue
            app_id = str(app.get("id", "unknown"))
            company = str(app.get("company", "") or "")
            role = str(app.get("role", "") or "")
            notes = app.get("notes", "") or ""
            times = _extract_times(notes)
            dates = sorted(set(_scan_interview_dates(app)))
            for d in dates:
                delta_days = (d - today).days
                if delta_days < 0 or delta_days > 1:
                    continue  # date-only granularity: today/tomorrow ~= 24h
                if times:
                    dts = [datetime(d.year, d.month, d.day, tm.hour, tm.minute)
                           for tm in times[:3]]
                    secs = [ (dt - now_dt).total_seconds() for dt in dts ]
                    secs = [s for s in secs if s >= 0]
                    if not secs:
                        continue
                    soonest = min(secs)
                    within_1h = soonest <= 3600
                    when_txt = dts[secs.index(soonest)].strftime("%-I:%M %p")
                else:
                    within_1h = delta_days == 0  # unknown time, same day: be loud
                    when_txt = None
                when_word = "today" if delta_days == 0 else (
                    "tomorrow" if delta_days == 1 else d.isoformat())
                urgency = HIGH if within_1h else NORMAL
                title = f"Interview {when_word}: {company} - {role}"
                body = f"Interview {when_word} ({d.isoformat()}" + \
                    (f" at {when_txt}" if when_txt else "") + \
                    f") for {role} @ {company}."
                base_id = f"interview-{app_id}-{d.isoformat()}"
                out.append({
                    "id": f"{base_id}-24h",
                    "title": title,
                    "body": body,
                    "category": "interviews",
                    "urgency": urgency,
                })
                if within_1h:
                    out.append({
                        "id": f"{base_id}-1h",
                        "title": title,
                        "body": body + " Starting within the hour.",
                        "category": "interviews",
                        "urgency": HIGH,
                    })
        except Exception:
            continue  # one bad record must never break the batch
    return _dedupe(out)


# --------------------------------------------------------------------------
# 2. deadline reminders
# --------------------------------------------------------------------------

_DEADLINE_RX = re.compile(
    r"(?i)(deadline|deadlines|closes?|closing|apply\s+by|due(?:\s+date)?)\s*:?\s*"
)


def deadline_reminders(now=None, days: int = 3) -> list[dict]:
    """Reminders for deadline-like dates in notes within `days`. Never raises."""
    now_dt = _as_now(now)
    today = now_dt.date()
    try:
        days = max(0, int(days))
    except Exception:
        days = 3
    out: list[dict] = []
    for app in _safe_apps():
        try:
            notes = app.get("notes", "") or ""
            if not isinstance(notes, str):
                notes = str(notes)
            dates: list[date] = []
            for m in _DEADLINE_RX.finditer(notes):
                snippet = notes[m.start():m.start() + 100]
                dates.extend(_safe_extract_dates(snippet))
            app_id = str(app.get("id", "unknown"))
            company = str(app.get("company", "") or "")
            role = str(app.get("role", "") or "")
            for d in sorted(set(dates)):
                delta = (d - today).days
                if delta < 0 or delta > days:
                    continue
                when = "today" if delta == 0 else (
                    "tomorrow" if delta == 1 else f"in {delta} days")
                out.append({
                    "id": f"deadline-{app_id}-{d.isoformat()}",
                    "title": f"Deadline {when}: {company} - {role}",
                    "body": (f"Application deadline {when} "
                             f"({d.isoformat()}) for {role} @ {company}."),
                    "category": "deadlines",
                    "urgency": HIGH if delta == 0 else NORMAL,
                })
        except Exception:
            continue
    return _dedupe(out)


# --------------------------------------------------------------------------
# 3. follow-up reminders (from nudges)
# --------------------------------------------------------------------------

_KIND_TITLES = {
    "interview_soon": "Interview coming up",
    "follow_up_due": "Follow-up due",
    "quiet_applied": "Application gone quiet",
    "stale_saved": "Saved job going stale",
}
_KIND_URGENCY = {
    "interview_soon": HIGH,
    "follow_up_due": NORMAL,
    "quiet_applied": LOW,
    "stale_saved": LOW,
}


def followup_reminders(now=None) -> list[dict]:
    """Map candid.nudges.pending_nudges() entries to notifications."""
    now_dt = _as_now(now)
    try:
        nudges = _nudges.pending_nudges(today=now_dt.date())
    except Exception:
        return []
    out: list[dict] = []
    for n in nudges or []:
        try:
            if not isinstance(n, dict):
                continue
            kind = str(n.get("kind", "nudge") or "nudge")
            company = str(n.get("company", "") or "")
            role = str(n.get("role", "") or "")
            slug = _slug(company) or "unknown"
            title = _KIND_TITLES.get(kind, "Nudge")
            title = f"{title}: {company}" if company else title
            out.append({
                "id": f"followup-{kind}-{slug}",
                "title": title,
                "body": str(n.get("message", "") or "").strip() or
                f"{kind} for {role} @ {company}".strip(),
                "category": "followups",
                "urgency": _KIND_URGENCY.get(kind, NORMAL),
            })
        except Exception:
            continue
    return _dedupe(out)


# --------------------------------------------------------------------------
# 4. watchlist alerts (optional module)
# --------------------------------------------------------------------------

def _watchlist_to_notifs(items) -> list[dict]:
    out: list[dict] = []
    if not isinstance(items, (list, tuple)):
        return []
    for i, m in enumerate(items):
        try:
            if not isinstance(m, dict):
                m = {"title": str(m)}
            title = str(m.get("title") or m.get("job_title") or
                        m.get("company") or "Watchlist match")
            company = str(m.get("company") or "")
            out.append({
                "id": f"watchlist-{i}-{_slug(company or title) or 'match'}",
                "title": f"Watchlist: {title}",
                "body": str(m.get("summary") or m.get("url") or title),
                "category": "watchlist",
                "urgency": NORMAL,
            })
        except Exception:
            continue
    return out


def watchlist_alerts() -> list[dict]:
    """Alerts from candid.watchlist if the module exists; [] otherwise."""
    try:
        import importlib
        W = importlib.import_module("candid.watchlist")
    except ImportError:
        return []
    except Exception:
        return []
    try:
        for attr in ("new_matches", "unread_matches", "alerts",
                     "check", "digest"):
            fn = getattr(W, attr, None)
            if not callable(fn):
                continue
            try:
                matches = fn()
            except TypeError:
                continue  # wrong signature; try the next entry point
            except Exception:
                continue
            notifs = _watchlist_to_notifs(matches)
            if notifs:
                return _dedupe(notifs)
        for attr in ("MATCHES", "matches", "results"):
            items = getattr(W, attr, None)
            notifs = _watchlist_to_notifs(items)
            if notifs:
                return _dedupe(notifs)
    except Exception:
        return []
    return []


# --------------------------------------------------------------------------
# 5/6. collect + deliver
# --------------------------------------------------------------------------

def collect_due(now=None) -> list[dict]:
    """Combine all collectors, dedupe by id, drop already-sent ids."""
    items: list[dict] = []
    collectors = (
        lambda: interview_reminders(now),
        lambda: deadline_reminders(now),
        lambda: followup_reminders(now),
        watchlist_alerts,
    )
    for collect in collectors:
        try:
            items.extend(collect() or [])
        except Exception:
            continue
    items = _dedupe(items)
    return [it for it in items
            if isinstance(it, dict) and it.get("id")
            and not _was_sent(it["id"])]


def deliver_due(now=None) -> int:
    """Deliver due, unsent notifications via candid.notify.

    Returns the number delivered. candid.notify is imported lazily; if it
    is unavailable, nothing is delivered and 0 is returned.
    """
    try:
        from candid import notify as notify_mod
    except ImportError:
        return 0
    notify_fn = getattr(notify_mod, "notify", None)
    mark_fn = getattr(notify_mod, "mark_sent", None)
    if not callable(notify_fn) or not callable(mark_fn):
        return 0
    delivered = 0
    for item in collect_due(now):
        try:
            nid = str(item.get("id", "") or "")
            if not nid or _was_sent(nid):
                continue
            notify_fn(
                str(item.get("title", "") or ""),
                str(item.get("body", "") or ""),
                category=str(item.get("category", "general") or "general"),
                urgency=str(item.get("urgency", NORMAL) or NORMAL),
            )
            mark_fn(nid)
            delivered += 1
        except Exception:
            continue  # one failed delivery must not stop the rest
    return delivered

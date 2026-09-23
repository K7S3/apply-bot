# Notifications

`candid notify` sends OS-native desktop notifications and collects due
reminders (interviews, deadlines, follow-ups, watchlist hits) from your
tracker. Everything is local: prefs and the pending queue live in your
config dir (`~/.config/candid`, or wherever `CANDID_CONFIG_DIR` points).

## Setup

No setup is required on most desktops. candid picks a backend automatically:

| OS | Backend (first available wins) |
|---|---|
| macOS | `terminal-notifier` (install with `brew install terminal-notifier`), else `osascript` |
| Linux | `notify-send` (e.g. `apt install libnotify-bin`), else `gdbus` |
| Windows | Windows toast via `winsdk` (optional dependency) |

If no backend is available (or delivery fails for any reason), the
notification is **queued**, not lost. Run `candid notify flush` later to
deliver queued items.

## Commands

Send a one-off notification:

```
python -m candid notify send --title "Interview" --body "Acme loop at 2pm"
python -m candid notify send --title "Deadline" --body "Apply by Friday" \
    --category deadlines --urgency critical
```

List what is due right now, and optionally deliver it:

```
python -m candid notify due            # list only
python -m candid notify due --deliver  # send each due reminder once
```

`due` collectors: interviews in the next 24h (`selected_for_interview`
apps with a date in notes), deadline-like dates in notes (next 3 days),
nudges from `candid nudges` (follow-ups due, quiet applications, stale
saved jobs), and watchlist matches when the optional `candid.watchlist`
module is present. Delivered reminder ids are recorded for 30 days, so a
second `--deliver` run sends nothing new.

Preferences:

```
python -m candid notify prefs                                   # show
python -m candid notify prefs --set enabled=false
python -m candid notify prefs --set quiet_start=23:00 --set quiet_end=07:00
python -m candid notify prefs --set categories.watchlist=false
```

Snooze and queue:

```
python -m candid notify snooze --for 2h        # or --minutes 30, or --until 09:00
python -m candid notify unsnooze
python -m candid notify flush                 # deliver queued notifications now
```

## Categories

First-class categories with per-category enable flags: `interviews`,
`deadlines`, `followups`, `watchlist`, `system`. Ad-hoc sends may use any
category string (including the default `general`); unknown categories are
treated as enabled.

When the master switch (`enabled=false`) or a notification's category is
disabled, the notification is **skipped** - not queued, not sent.

## Quiet hours

`quiet_start` / `quiet_end` are `HH:MM` in 24h local time. Overnight
windows work (e.g. `22:00`-`08:00`); setting start equal to end disables
quiet hours entirely. Defaults: `22:00`-`08:00`.

While quiet hours (or a snooze) are active, `notify()` **queues** the
notification instead of delivering it. `flush` delivers queued items once
the quiet window / snooze has passed; if still quiet or snoozed, `flush`
delivers nothing and the items stay queued.

## Cron recipe

Check for due reminders every 15 minutes and deliver them:

```
*/15 * * * * cd /path/to/candid && /usr/bin/python3 -m candid notify due --deliver
```

Use absolute paths: cron runs with a minimal `PATH` and a different
working directory, so `cd` to the checkout first. During your quiet
hours, `--deliver` queues the reminders instead of delivering them. The
first `--deliver` run after the window ends delivers them fresh and
marks each reminder sent (so they will not repeat). Run
`candid notify flush` instead if you want the queued copies delivered -
but not both back-to-back, or you will see each reminder twice.

## Headless behavior

On a machine with no notification daemon (SSH session, server, CI), the
OS backend fails and every notification is queued to
`notify_queue.json` in the config dir. Nothing raises, nothing is lost:
run `candid notify flush` on a machine with a desktop session to deliver
the backlog.

## Preferences reference

Stored in `<config dir>/notify.json` (merged over defaults on load):

| Key | Type | Default | Notes |
|---|---|---|---|
| `enabled` | bool | `true` | Master switch; `false` skips everything |
| `quiet_start` | `HH:MM` | `"22:00"` | Quiet window start (24h local) |
| `quiet_end` | `HH:MM` | `"08:00"` | Quiet window end; start == end disables |
| `categories.<name>` | bool | `true` | Per-category flag for `interviews`, `deadlines`, `followups`, `watchlist`, `system` |
| `snoozed_until` | ISO timestamp or `null` | `null` | Managed by `snooze` / `unsnooze`; do not edit by hand |

Related files in the config dir: `notify_queue.json` (pending items),
`notify_sent.json` (delivered reminder ids, pruned after 30 days).

Urgency levels for `send`: `low`, `normal`, `critical` (default `normal`).

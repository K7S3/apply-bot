# Watching company career pages

`candid watch` polls the career pages of companies you care about and raises
an **alert** for every new posting that matches your profile. The dashboard's
Watchlist section turns that state into per-company monitor cards, a
new-postings feed, and per-company posting timelines.

## Setup

Watching is **opt-in and local**. Nothing is fetched until you add a
company, and every fetch hits the company's public careers endpoint directly
— no accounts, no keys, no logins, same as `jobs curate` (see
[adding_sources.md](adding_sources.md)).

```bash
# add a company (positionals + one source flag)
python -m candid watch add Acme --greenhouse acme
python -m candid watch add Initech --lever initech
python -m candid watch add Hooli --rss https://hooli.com/careers/feed.xml

# list / poll / remove
python -m candid watch list
python -m candid watch run                 # fetch all boards, diff, match, alert
python -m candid watch status              # last run per company + alert counts
python -m candid watch remove Acme
```

`watch add` fails with the exact next command to run if the source type is
unknown or the board slug is missing — same CLI style as the rest of candid.

## Source types

| Flag | What it polls | Identifier |
|---|---|---|
| `--greenhouse BOARD` | The public Greenhouse boards API for the board slug | board slug, e.g. `acme` |
| `--lever SITE` | The public Lever postings API for the company slug | site name, e.g. `initech` |
| `--rss URL` | Any careers RSS/Atom feed URL | full feed URL |

All three are public, no-login JSON/XML endpoints with polite request
behavior (one request per source per run, a real `User-Agent`). Company
career pages that need login, JavaScript rendering, or an API key are out of
scope by design — candid never scrapes behind auth.

## Thresholds

Alerts are **match-gated**, not time-gated: a new posting only becomes an
alert when it passes `passes_gate` — verdict is GO/CONDITIONAL, or its
match score is at or above the threshold (default **60**).

```bash
python -m candid watch threshold 70   # only alert on strong matches
python -m candid watch threshold 60   # back to the default
```

Postings below the threshold are still recorded in the monitor history
(they show up in the dashboard timeline as open postings) — they just don't
create alerts.

Reposts are flagged, not hidden: a posting whose title+location matches a
recently closed one, or whose id reappears after being closed, is marked
`repost: true` and creates a `kind: "repost"` alert ("Reposted: … is back
on the board").

Feed health is reported per source (`ok` / `failing` / `skipped`): after
too many consecutive fetch failures a source is skipped for a while and the
dashboard card shows **error** with the last error message.

## The alert workflow

1. `watch run` fetches every watched company's sources, diffs against the
   previous snapshot (new / closed / reposts), scores the new postings
   against your profile, and creates one alert per posting that passes the
   threshold gate. Nothing is written to your tracker automatically.
2. `watch alerts` (or `--unread`) lists them; the dashboard's **New
   postings** panel shows unread alerts with their match score, verdict,
   an **Apply ↗** link straight to the posting, and a **Mark read** button.
3. `watch alerts-read 3` (or the dashboard's Mark read / Mark all read)
   acknowledges alerts after you've triaged them.
4. Clicking a company card in the dashboard opens the **posting timeline**:
   open postings with their `first_seen` dates, recently closed postings
   (most recent 25), and repost flags — so you can tell at a glance whether
   a "new" alert is genuinely new or a relisted role.

Alerts, runs, and monitor history live under `candid_data/` next to
everything else candid learns about you; they never leave your machine.

## Dashboard integration (for contributors)

The dashboard reads watch state through `candid/dashboard.py`, which
imports `candid/monitors.py` and `candid/alerts.py` **defensively** — the
panels degrade to a "not configured" state when those modules are absent,
and never crash on a broken module. It prefers the native API and falls
back to probing alternate function names:

| Purpose | Native | Fallbacks probed |
|---|---|---|
| list companies | `list_companies` | `list_monitors`, `get_monitors`, `companies`, … |
| feed health | `health` | — (card-level `health`/`feed_health` fields) |
| posting history | `get_history` | `timeline`, `company_timeline`, `postings`, … |
| unread alerts | `get_pending_alerts` | `unread`, `unread_alerts`, `list_unread`, … |
| mark alert read | `mark_read` | `ack`, `ack_alert`, `dismiss_alert`, … |
| alert threshold | `get_threshold` | — |

Endpoints: `GET /api/watch` (cards), `GET /api/watch/alerts` (unread alerts
+ threshold), `POST /api/watch/alerts/<id>/read` (404 for unknown ids),
`GET /api/watch/company?name=...` (404 for unknown companies).

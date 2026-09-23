# Warm intros

Rank your job search by the strength of your own network, and work the
outreach like a pipeline. Everything here runs offline on exports you
supply yourself: candid never connects to LinkedIn, Gmail, or any account.

## Data flow

```
LinkedIn data-export ZIP (Connections.csv)
        |
        v
candid.warm.load_connections()      1st-degree connections only
        |                           (email addresses are never imported)
        v
warmth_score(connection)            per-person warmth, 0-100
        |
        v
connection_strength(company)        aggregated per company, 0-100
        |
        +---> rank_jobs()           jobs scored by warm_score(strength, match)
        |
        +---> insider_map()         insiders grouped: hiring / recruiting /
        |                           engineering / other
        +---> draft_intro()         intro-request message in your voice
        |
        v
warm.json outreach state            none / asked / introduced / applied
        |                           per company, via `warm status`
        v
`warm link <company> --app ID`      ties the company to a tracker app id
        |
        v
`track list` intro column           read-only display of the warm status
dashboard "Warm intros" section     top-10 companies, read-only
```

The tracker is never written by outreach actions: `warm status ... applied`
records outreach state only. The only bridge to the tracker is the explicit
`warm link` command.

## The honesty rule: 1st-degree only

The LinkedIn data export contains **only your 1st-degree connections**
(Connections.csv). candid never claims 2nd-degree visibility, mutual
connections, or anything beyond "you are directly connected to this person".

- `intro_path()` describes a one-hop path: `You -> Jane Doe (Engineering
  Manager @ Acme)`. It never implies a mutual or 2nd-degree hop.
- `insider_map()` buckets connections by title keywords into hiring /
  recruiting / engineering / other. Buckets are "likely useful for", not
  "is a decision maker".
- `draft_intro()` writes a request *you* send to *your* connection. It
  states the relationship as it is ("we connected in ...") and never
  invents a shared history.

## The warm_score formula

### Per-connection warmth: `warmth_score(conn)` -> 0-100

```
warmth = 0.4 * recency + 0.6 * seniority
```

- **recency** (0.4 weight): 100 for a connection made today, decaying
  linearly to a floor of 20 at 10 years. An unknown connection date is
  neutral: 50.
- **seniority** (0.6 weight), from the title:
  - vp: 95, director: 95/90, head / recruiter: 85, manager: 80,
    lead: 75, senior / staff / principal: 65, plain IC or unknown: 50,
    intern: 35.

  Recruiters score well on purpose: they are the fastest path to an intro.

### Per-company strength: `connection_strength(conns)` -> 0-100

The strongest connection counts fully; each additional connection
contributes half as much as the previous one (diminishing returns), and
the total is capped at 100. One warm senior contact beats five lukewarm
ones.

### Job ranking: `warm_score(strength, match)` -> 0-100

```
warm_score = (strength + match) / 2        when a match score is given
warm_score = strength                     when match is None
```

This ranks jobs with real warm intros against jobs that are merely a good
profile fit. `rank_jobs()` sorts by this score descending; jobs with no
connections are included at the bottom.

## Outreach tracking (warm.json)

`warm status <company> <none|asked|introduced|applied> [--contact NAME]`
records outreach state in `warm.json`, keyed by normalized company name:

```json
{
  "acme": {
    "contact": "Jane Doe",
    "status": "asked",
    "asked_on": "2026-09-22",
    "app_id": 3
  }
}
```

- `asked_on` is set to today whenever the status is anything but `none`.
- A provided contact name is stored; otherwise the previous contact is kept.
- `app_id` is set only by `warm link <company> --app ID`, which validates
  the tracker application id first and merges it into the existing record
  without touching contact / status / asked_on.

`track list` gains an **intro** column showing the warm status for each
application's company. It is read-only display: nothing about the tracker
changes when you record outreach.

## Outreach timing: last contact

`candid/warm_timing.py` exposes `get_last_contact(name, mbox_path)`, the
hook for the queue's "last contact" column. It scans a Gmail Takeout mbox
(using `candid/gmail.py`'s mbox discovery; headers are read with stdlib
`mailbox` because the parsed dicts drop To/Cc) for messages where the
connection's full name appears in From/To/Cc, and returns the most recent
message date.

Name matching is defensive on purpose:

- full-name substring, case-insensitive, over display name and address,
- blank name -> None,
- no match -> None,
- **ambiguous match -> None, never a guess** (more than one distinct
  contact identity matches, e.g. two different people sharing a name),
- matched messages with no parseable Date are skipped.

The queue can show this date next to each contact so you space out intro
requests sensibly.

## Dashboard

The local dashboard (127.0.0.1 only) has a read-only **Warm intros**
section: top-10 companies by connection strength, each with its top
connection, outreach status, contact, asked-on date, and linked tracker
app. It is served by `dashboard.warm_intros()` at `GET /api/warm`.

Strengths come from an optional connections snapshot at
`candid_data/connections.json` (a JSON list of connection dicts as
produced by `load_connections`, dates as ISO strings). Create it with:

```
python - <<'EOF'
import json
from candid import config as C, warm as W
snap = [{k: (v.isoformat() if hasattr(v, "isoformat") else v)
         for k, v in c.items()}
        for c in W.load_connections("LinkedIn-export.zip")]
(C.DATA_DIR / "connections.json").write_text(json.dumps(snap, indent=2))
EOF
```

Without the snapshot the section still shows outreach statuses, ordered
by outreach progress, with strengths at 0. The section never writes
anything.

## Commands

| Command | What it does |
|---|---|
| `warm rank --export LinkedIn-export.zip` | Rank saved jobs by warm_score (strength blended with match) |
| `warm queue --export LinkedIn-export.zip` | Prioritized outreach queue, one row per company |
| `warm map "Acme" --export LinkedIn-export.zip` | Insiders at a company, grouped by role |
| `warm draft "Acme" --export LinkedIn-export.zip` | Draft an intro-request message |
| `warm status "Acme" asked --contact "Jane Doe"` | Record outreach status |
| `warm link "Acme" --app 3` | Store tracker app id 3 in warm.json for Acme |
| `track list` | Shows the intro column per company (read-only) |

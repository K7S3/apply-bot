# Conference & meetup finder (`candid events`)

candid ships a curated dataset of public tech conferences and recurring
meetups (`candid/data/events.json`) — no login, no scraping, no paid API.
Use it to find events worth your time, rank them against your profile,
plan your networking, and follow up afterwards.

## Quick start

```bash
# what's on, filterable by city / topic / cost / format / recency
python -m candid events list --city "New York" --free --days 60

# ranked by fit to YOUR profile (role 35 · skills 35 · seniority 10 · logistics 20)
python -m candid events rank --limit 10

# detail card for one event
python -m candid events show kubecon-eu-2027

# networking-goal planner: goals, who to meet, conversation starters,
# elevator pitch, session strategy, pre-event checklist — saved to
# candid_data/event_plans/<id>.md
python -m candid events plan kubecon-eu-2027 --contacts 8 --goal "find a referral"

# park it in the tracker, or keep a watchlist of maybes
python -m candid events save kubecon-eu-2027
python -m candid events watch add kubecon-eu-2027
python -m candid events upcoming --days 90 --watched-only

# after the event: draft follow-up emails for everyone you met
python -m candid events debrief nyc-python-meetup \
    --contacts "Jane Doe, Engineer, Acme, loved her Airflow talk; Sam Lee"

# export to your calendar, or check the budget
python -m candid events calendar --out events.ics
python -m candid events budget reinvent-2026 --travel 400 --nights 4 --hotel 180 --budget 3000

# what topics are covered?
python -m candid events topics
```

## How ranking works

`events rank` scores each upcoming event 0–100 with a GO / CONDITIONAL /
SKIP verdict:

| Component | Weight | What it measures |
|---|---|---|
| Role fit | 35 | Event's target roles vs your headline, target roles, and past titles |
| Skill/topic fit | 35 | Event topics vs your skills, domains, and resume bullets |
| Seniority fit | 10 | Event audience (all-levels / mid-senior / senior…) vs your seniority |
| Logistics | 20 | Virtual/hybrid bonus, in-your-city bonus, ticket cost, planning window |

Every score prints its "why" bullets, so you can audit it.

## Honest date coverage

Each event carries `date_confidence`:

- **verified** — dates were checked against the organizer's site
  (e.g. re:Invent 2026: Nov 30–Dec 4, Las Vegas).
- **typical** — the event recurs annually; dates follow its usual season
  but are **not verified**. The CLI flags these with `*` and tells you to
  confirm on the organizer site before booking.
- **recurring** — a repeating local meetup; the date is the next expected
  occurrence, not a confirmed one.

candid never pretends to know dates it hasn't verified. See
[adding_events.md](adding_events.md) to extend the dataset.

## Files

- `candid/data/events.json` — the curated dataset (versioned, reviewable)
- `candid_data/event_plans/<id>.json` / `.md` — saved networking plans
- `candid_data/event_plans/<id>_debrief.md` — post-event follow-up drafts
- `candid_data/events_watch.json` — your watchlist
- Tracker entries with status `saved` and role `Attendee (<edition>)`
  for events you park via `events save`

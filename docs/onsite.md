# Onsite day planner

`python -m candid onsite` turns an interview invitation into a runnable day:
the schedule, the logistics, the energy plan, and the follow-through.

All data lives in `candid_data/onsite.json` (git-ignored). Everything is
offline and deterministic — every time shown is computed from the schedule
you enter, nothing is invented.

## The workflow

```bash
# 1. Create the day
python -m candid onsite plan --company Acme --role "Data Scientist" \
    --date 2026-10-05 --mode onsite --commute-min 40

# 2. Add rounds: "START KIND MINUTES [TITLE...]", 24h times
python -m candid onsite add-round --round "10:00 coding 45" \
    --interviewer "Jane Doe" --where "Room 4B"
python -m candid onsite add-round --round "11:00 behavioral 45"
python -m candid onsite add-round --round "12:00 lunch 45"
python -m candid onsite add-round --round "13:00 system-design 60"

# 3. See the day
python -m candid onsite timeline     # schedule + gap flags
python -m candid onsite prep         # what to review per round
python -m candid onsite energy        # sleep, meals, breaks, caffeine
python -m candid onsite morning       # wake-up / leave-by / arrive

# 4. Work the checklist
python -m candid onsite checklist
python -m candid onsite check --item-id 3

# 5. During / after the day
python -m candid onsite notes --round-id 1 --text "Asked about caching"
python -m candid onsite summary --out /tmp/acme-day.md
```

Omit `--plan-id` everywhere and the latest plan is used.

## Round kinds

`coding`, `system-design`, `behavioral`, `hiring-manager`, `recruiter`,
`presentation`, `lunch`, `break`, `tour` — each with a sensible default
duration (overridable in the round spec) and its own prep reminders and
questions-to-ask bank. Overlapping rounds are rejected; rounds that touch
exactly (one ends at 10:45, next starts at 10:45) are fine.

## Subcommands

| Subcommand | What it does |
|---|---|
| `plan` | Create the day: company, role, date, mode (`onsite`/`virtual`/`hybrid`), location, commute. Generates the logistics checklist for the mode. |
| `plans` | List day plans, newest first. |
| `add-round` / `remove-round` | Add (with overlap detection) or remove rounds. |
| `timeline` | Printable timeline with computed end times, gaps, and flags for back-to-back rounds (<10m gaps) and missing lunch windows. |
| `checklist` / `check` | Mode-aware logistics checklist (documents, tech, comfort, research, prep, logistics); check items off, `--undo` to reopen. |
| `prep` | Per-round prep reminders keyed off round kind. |
| `energy` | Sleep target, meal windows (scheduled lunch or best midday gap), real breaks vs 2-minute resets, caffeine cutoff 6h before bed. |
| `morning` | Reverse timeline from the first round: bedtime the night before, wake-up, leave-by (commute + 15m buffer), 15m-early arrival. |
| `questions` | Questions to ask the interviewer — `--kind` for one round type, or the whole plan per round. |
| `notes` | Free-text notes for the day or one round. |
| `summary` | Export Markdown: timeline, notes, checklist state, follow-up reminders. |
| `delete` | Delete a plan (requires an explicit `--plan-id`). |

## How the times are computed

- **Wake-up:** first round minus 90 minutes (onsite/hybrid) or 60 (virtual).
- **Bedtime:** wake-up minus 8 hours, the previous evening.
- **Leave-by:** first round minus 15m early arrival, minus commute, minus 15m buffer.
- **Lunch:** a `lunch` round if scheduled, else the longest gap of 30m+ whose midpoint falls between 11:00 and 14:00, else a flag to eat a big breakfast.
- **Caffeine cutoff:** 6 hours before bedtime.

# `python -m candid ritual` - pre-interview confidence routine

Ten small subcommands that wrap an interview day: what to do before, calm
yourself down, know who's across the table, and capture what happened after.

The per-interview subcommands (logistics, materials, dossier, interviewers,
cooldown) take `--company X --role Y` and share one interview id derived
from the two, so everything for one interview lands together:

- panels: `candid_data/rituals/<company-role>/interviewers.json`
- debriefs: `candid_data/debriefs/<company-role>.json`

The standalone routines (timeline, warmup, techcheck, calm, countdown) do
not need `--company/--role`.

## The day before / day of

### `ritual logistics` - day-of logistics checklist

A checklist tuned to the round type: virtual (join link, backup device,
camera/mic), onsite (address, arrival buffer, ID, printed resumes), or
phone (quiet room, charged phone). Check items off as you go.

```
python -m candid ritual logistics --company Acme --role "Data Scientist" \
    --date 2026-09-25 --round-type virtual
python -m candid ritual logistics --check 1 --ritual-id acme-data-scientist-2026-09-25
```

### `ritual timeline` - backwards interview-day timeline

Working backwards from the interview start time: wake up, breakfast,
materials review, warm-up, tech check, calm slot, join early, debrief.

```
python -m candid ritual timeline --start "2026-09-25 14:00" --round-type virtual
```
Add `--timezone America/New_York`, `--wake 07:30`, `--duration 90`, or `--json`.

### `ritual materials` - materials checklist

Resume copies, your questions for them, notes from the prep pack, pen,
water, charger.

```
python -m candid ritual materials --company Acme --role "Data Scientist"
```

### `ritual dossier` - company / interviewer dossier

One-glance dossier: the company research checklist from your prep pack
plus anything you recorded about the panel.

```
python -m candid ritual dossier --company Acme --role "Data Scientist"
```

### `ritual warmup` - warm-up drills

A timed warm-up before the interview: one easy coding problem, one
behavioral question (self-rated), one technical flashcard. Gentle framing,
warm-up not an exam.

```
python -m candid ritual warmup
```
Add `--minutes 10`, `--seed 7`, or `--no-wait` to skip pacing pauses.

### `ritual techcheck` - video-interview tech check

Advisory checks for remote rounds: Python and key libraries, disk space,
network reachability, plus a round-specific reminder checklist
(camera/mic, screen-share, IDE, quiet room). Warnings are never fatal.

```
python -m candid ritual techcheck --round-type virtual
```
`--round-type` is virtual, onsite (coding), or phone. Add `--no-net` to skip the probe.

### `ritual calm` - pre-interview calming exercise

A short calming routine for nerves: box-breathing timer, 5-4-3-2-1
grounding, affirmations built only from your real profile strengths,
and reframe prompts for catastrophic thoughts. A routine, not treatment.

```
python -m candid ritual calm
```
Add `--cycles 6` or `--no-wait` for an instant run.

### `ritual countdown` - T-24h countdown plan

The day before, hour by hour: lay out clothes and docs, charge devices,
light review only ("nothing new after 9pm"), back-calculated bedtime,
morning walk, real breakfast, join-early buffer. Plus paste-ready reminders.

```
python -m candid ritual countdown --start "2026-09-25 14:00"
```
Add `--json` for machine-readable output.

## `ritual interviewers` - know who's across the table

Record the panel, then see likely question angles for each interviewer:

```
python -m candid ritual interviewers --company Acme --role "Data Scientist" \
    --add "Jane Doe, Hiring Manager" --round "1"
python -m candid ritual interviewers --company Acme --role "Data Scientist" \
    --add "Sam Lee, Senior Engineer"
python -m candid ritual interviewers --company Acme --role "Data Scientist" --list
```

`--list` prints a quick-glance card per interviewer: name, title, round,
likely angle (e.g. behavioral / leadership for managers, coding / system
design for engineers, background screen for recruiters), and three sample
questions pulled from the real prep question bank (`candid.prep_questions.
GENERIC_BANKS`).

The angles are labeled as **general guidance** - they are never claimed to
be asked at this company, unless `QUESTIONS_DB` actually has verified
questions for it, in which case the card says so explicitly.

## `ritual cooldown` - post-interview cooldown + debrief

After the interview, run the guided 5-minute cooldown (breathe, reset),
then answer the debrief prompts: what they asked, what stumped you, weak
spots in your answers, the vibe, and next steps.

```
python -m candid ritual cooldown --company Acme --role "Data Scientist"
```

This saves `candid_data/debriefs/<company-role>.json`:

```json
{
  "company": "Acme",
  "role": "Data Scientist",
  "date": "2026-09-22",
  "questions_asked": ["Tell me about yourself", "Design a URL shortener"],
  "stumped_by": ["SQL window function question"],
  "weak_spots": ["Rambled on the motivation answer"],
  "vibe": "warm",
  "next_steps": ["Email recruiter Friday"]
}
```

That schema is what the debrief loop consumes, so keep it stable: plain
lists of strings, `vibe` a short free-text string, `date` as `YYYY-MM-DD`.

The cooldown ends by reminding you to send thank-you notes:

```
python -m candid followup thank-you --person "Jane Doe" \
    --role "Data Scientist" --company Acme
```

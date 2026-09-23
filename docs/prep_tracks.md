# Prep Tracks — role-family interview preparation

`python -m candid tracks ...` gives you a curated, self-contained study guide
for one of six role families. Each track bundles the typical interview loop
(rounds + time budgets), concept deep-dives, a question bank, timed drills,
and suggested mock sessions.

## The six tracks

| ID | Title | Rounds |
|----|-------|--------|
| `mle` | Machine Learning Engineer | ML coding, ML system design, ML fundamentals, behavioral |
| `backend` | Backend / Systems Engineer | Coding, system design, systems deep-dive, behavioral |
| `frontend` | Frontend Engineer | Coding (JS/DOM), frontend system design, web fundamentals, behavioral |
| `data-science` | Data Scientist | Statistics & experimentation, SQL / data case, ML modeling, behavioral |
| `pm` | Product Manager | Product sense, metrics / analytical, execution / behavioral, technical fluency |
| `em` | Engineering Manager | People management, execution & delivery, system design (leadership lens), behavioral / values |

## Commands

```bash
# discover
python -m candid tracks list
python -m candid tracks show mle                 # full track: loop, concepts, questions, drills, mocks
python -m candid tracks show pm --deep-dives     # include full concept deep-dive text

# questions: filter or take a deterministic sample
python -m candid tracks questions --track backend --difficulty medium
python -m candid tracks questions --track mle --category ml --round design
python -m candid tracks questions --track frontend --sample 5 --seed 42

# concepts (deep-dives come from candid.prep_concepts)
python -m candid tracks concepts --track data-science
python -m candid tracks concepts --track mle --deep-dives

# drills: timed exercises with self-check checklists
python -m candid tracks drills --track backend
python -m candid tracks drills --track em --kind qna

# N-day study plan (drills scheduled whole, concepts/questions fill the budget)
python -m candid tracks plan --track data-science --days 14
python -m candid tracks plan --track pm --days 7 --hours 2

# progress: mark concepts (by tag), questions (qN), drills (by id) done
python -m candid tracks done --track mle --kind concept --key ml_system_design
python -m candid tracks done --track backend --kind drill --key be-design-45
python -m candid tracks done --track pm --kind question --key q3
python -m candid tracks progress --track mle
python -m candid tracks undone --track mle --kind concept --key ml_system_design
python -m candid tracks reset --track mle

# mock presets aligned to the track's loop
python -m candid tracks mock --track data-science

# suggest tracks from match-gap text (e.g. from `candid match` gaps)
python -m candid tracks suggest --gaps "Missing must-have skill: sql; Seniority gap: leadership"
```

Progress persists in `candid_data/track_progress.json` (honors `CANDID_DATA_DIR`).

## Content conventions

- **Questions are general preparation**, not questions reported at any specific
  company. Company-verified questions live in `candid/prep_questions.py` and
  are surfaced by `candid prep` packs instead. Never present track questions
  as "asked at company X".
- Every concept `tag` must exist in `candid.prep_concepts.CONCEPTS`
  (enforced by `tests/test_prep_tracks.py`).
- Every question's `round` must match one of the track's loop rounds.
- Question entries: `q`, `category`, `difficulty` (easy/medium/hard), `round`.
- Drill entries: `id`, `name`, `minutes`, `kind` (design/coding/qna),
  `instructions`, `checklist` (3+ items).

## Adding or editing a track

Edit the `TRACKS` dict in `candid/prep_tracks.py`, then run the track tests:

```bash
python -m pytest tests/test_prep_tracks.py -q
```

To add a new role family, add a new entry to `TRACKS` with the same shape
(title, tagline, loop, concepts, questions, drills, mock) and add its id to
the `EXPECTED_IDS` tuple in the test file.

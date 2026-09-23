# Take-home assignment planner (`candid assign`)

The planner turns a take-home assignment and a deadline into an organized
plan of attack: a structure template, dated milestones, a day-by-day
time-boxed schedule, a workload fit check, and a self-review rubric.

**The boundary, stated plainly:** candid plans and organizes the work. It
never does the work for you. Templates contain phase guidance, file maps,
and checklists - never solution code, never answer sketches. `assign solve`
exists only to say so out loud. This is deliberate: a take-home only means
something if the work is yours, and reviewers can tell when it isn't.

## Quick start

```bash
# 1. Pick a structure template (or get one suggested from the prompt text)
python -m candid assign templates
python -m candid assign suggest --text "Build a REST API with three endpoints"

# 2. Look at the template: phases, file map, README skeleton, rubric
python -m candid assign show rest-api

# 3. Build the plan against your real deadline and real availability
python -m candid assign plan --template rest-api \
    --company Acme --role "Backend Engineer" \
    --deadline 2026-09-29 --hours-per-day 3

# 4. Work the plan
python -m candid assign schedule --id 1   # day-by-day time boxes
python -m candid assign done --id 1 --milestone m1
python -m candid assign status --id 1

# 5. Before submitting, run the rubric honestly
python -m candid assign review --id 1
python -m candid assign check --id 1 --item prompt-reread

# 6. Keep a copy of the plan
python -m candid assign export --id 1 --out plan.md
```

## Templates

Six archetypes, each with a typical hour budget, phased breakdown with
hour shares, a suggested project layout (file names only), a README
skeleton, and a template-specific review rubric on top of the global items:

| Template | Typical hours | For |
|---|---|---|
| `data-pipeline` | 12 | ETL/ELT style ingest-transform-serve work |
| `rest-api` | 10 | A small HTTP service with endpoints |
| `web-app` | 14 | A front-end (plus backend) for a user task |
| `ml-model` | 12 | Train and evaluate a model on given data |
| `algorithm-pack` | 6 | A set of timed coding problems |
| `generic` | 10 | Anything else |

## How the planning math works

- **Milestones.** Each phase becomes a milestone with an hour estimate
  (`typical_hours * share`, rounding absorbed by the last phase) and a due
  date spread across the window by cumulative share. The last milestone is
  always due on the deadline.
- **Fit check.** Available hours = days * hours-per-day. 10% is held back
  as a submission buffer, so work hours = available * 0.9. The verdict is
  `ok` (required <= work), `tight` (within 25% over), or `over` (beyond
  that), each with concrete suggestions: trim scope, raise hours-per-day,
  or negotiate the deadline. Never eat the buffer: submitting narrower
  tested work reads better than submitting wider untested work.
- **Time-boxing.** Milestone hours are laid across the days at your
  hours-per-day rate, in order. Leftover capacity - including the 10%
  buffer - becomes buffer blocks for final self-review, packaging, and
  submission.
- **Replan.** `assign replan --id N --deadline YYYY-MM-DD` recomputes the
  dates when the deadline moves. Completed milestones keep their done flag;
  only dates change.

## The self-review rubric

Every plan gets the global items (re-read the prompt, stayed in the time
box, no secrets in the submission) plus template-specific ones (e.g. the
REST API rubric checks endpoint documentation, error codes, and a clean
checkout run). Check them off with `assign check`; the rubric only works
if you are honest with it.

## Data

Plans live in `candid_data/assignments.json` (git-ignored, overridable via
`CANDID_DATA_DIR`). `assign delete --id N --yes` removes one.

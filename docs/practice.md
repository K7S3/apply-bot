# Live-coding practice harness (`practice`)

Timed, distraction-free coding sessions on the problems in the local bank
(`candid/data/problems/`, see [adding_problems.md](adding_problems.md)).
Everything runs locally - the only thing the harness judges is your code,
with the same sandboxed judge as `mock`.

## Quick start

```bash
# 45-minute focused session on a medium problem
python -m candid practice start --difficulty medium --minutes 45 --focus

# a specific problem, no focus lock (hints allowed), custom phase split
python -m candid practice start --problem max-subarray --minutes 30 \
    --no-focus --phases plan:15,code:55,test:20,review:10

# built-in routines: warmup, interview-sim, dp-drill
python -m candid practice routine --action run --name interview-sim
```

## Inside a session

- **Countdown timer** with warnings at 25 / 50 / 75 / 90 % of your budget,
  plus a live `time` command. When the clock expires the session finalizes
  with your last submitted code (outcome `timed_out`).
- **Phases** (default split plan 10 / code 60 / test 20 / review 10 %): the
  harness announces phase changes so you budget like a real interview.
- **Focus mode** (on by default): `hint` and `solution` are locked while the
  clock runs. Pass `--no-focus` for untimed-style drilling.
- **Think-aloud prompts** every N minutes (`--think-every 10`, `0` disables):
  narrate your thinking out loud, then type a one-line note. The notes are
  saved in the session transcript.
- **Attempts**: `run` judges against visible tests only (fast feedback);
  `done` runs the full suite (visible + hidden) for the official verdict.

Commands during a session: `run` | `done` | `hint` | `solution` |
`think` | `time` | `quit`.

## After a session

Every finished session gets:

1. **A structured review** - auto-derived observations (time usage, attempt
   count, hint reliance, think-aloud coverage) plus your answers to 4
   reflection questions. Redo or view later with
   `practice review --session <id>`.
2. **Pattern tags** - automatic: `topic:<topic>`, `diff:<difficulty>`, and
   behavioral tags derived from how you did (`first-try-solve`,
   `hint-dependent`, `debug-heavy`, `time-pressure`, `gave-up-early`,
   `narrated-well`, `reviewed`). Add your own:
   `practice tag --session <id> --add needs-drill`.

Then:

```bash
python -m candid practice list --tag topic:dp --outcome solved
python -m candid practice show --session p20260922_101500
python -m candid practice stats                    # solve rate, avg time, streak, per-tag
python -m candid practice stats --tag topic:arrays
python -m candid practice queue                    # spaced-repetition revisits
```

## Revisit queue (spaced repetition)

Sessions you gave up on, timed out on, or solved weakly (2+ hints or 4+
coding attempts) are scheduled for revisits on a 1 / 3 / 7 / 14 / 30-day
ladder. `practice queue` shows what's due, most overdue first. Re-attempt
with `practice start --problem <id>`; a clean solve retires the schedule.

## Routines

Named multi-problem plans, run back to back with breaks:

```bash
python -m candid practice routine --action list
python -m candid practice routine --action save --name my-drill \
    --steps max-subarray:20,climbing-stairs:25
python -m candid practice routine --action run --name my-drill
python -m candid practice routine --action delete --name my-drill
```

Built-ins: `warmup` (1 easy, 20 min), `interview-sim` (2 mediums, 45 min
each), `dp-drill` (easy + medium dp). A step can also be a pick spec instead
of a fixed problem id.

## Data

Sessions live in `candid_data/practice_sessions/<id>.json` with an index at
`candid_data/practice_index.json` and routines at
`candid_data/practice_routines.json`. All honor `CANDID_DATA_DIR`, so tests
and experiments never touch your real history.

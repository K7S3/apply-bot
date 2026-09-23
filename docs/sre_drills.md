# SRE drills and war-room simulator

`candid/sre_drills.py` implements the two DevOps/SRE training commands for the
top-level `sre` group: `drill` and `warroom`. Everything runs locally and
offline except an optional Gemini AI incident commander (same surrogate
credential handling as `candid mock ai`; never hardcodes keys).

## sre drill

Timed, multiple-choice incident-response drills built as decision trees.

```
python -m candid sre drill --list
python -m candid sre drill --scenario latency-spike
python -m candid sre drill --scenario disk-full-cascade --no-timer
python -m candid sre drill --scenario bad-deploy --auto --answers 1,2,3,2
```

- At each step you get the situation plus 3-4 action choices.
- Each choice is scored (0-100) and explained; the tree branches on your pick.
- Default: 60 seconds per decision. `--no-timer` disables the timer.
- `--auto` is non-interactive (for tests/CI): answers come from `--answers`
  (comma-separated 1-based choice numbers); steps without a scripted answer
  take the best choice.
- Final score, letter grade (A-F), strengths, and gaps are printed, and the
  full result is saved as JSON to `candid_data/sre_drills/`.

### Scenarios

| id | title | steps |
|----|-------|-------|
| latency-spike | Latency spike on the checkout API | 4 |
| disk-full-cascade | Disk-full cascade on the API fleet | 3 |
| bad-deploy | Bad deploy: error rate spike after release | 4 |
| dns-outage | DNS outage: the site is unreachable | 4 |

Each scenario ends with a "harden" step: the durable fix that prevents the
next occurrence (replica routing, log caps, canary gates, active-active DNS).

## sre warroom

A simulated incident war room. An incident commander and teammates drive the
incident; you respond as the on-call engineer and each reply is scored by
keyword coverage against what a good on-call would say.

```
python -m candid sre warroom --scenario dns-outage
python -m candid sre warroom --scenario bad-deploy --auto
python -m candid sre warroom --scenario latency-spike --auto \
    --replies "scope the p99|||kill the stuck queries"
```

- Interactive: type replies at the `you:` prompt; `quit` ends early.
- `--auto` uses `--replies` (`|||`-separated) or the built-in model replies.
- `--use-ai` enables the Gemini AI incident commander, which reacts to your
  replies in character as IC Rhea. It uses the exact same credential flow as
  `candid mock ai` (`dynamic_credentials` surrogate for
  `custom.google-gemini`); if the network or credential is unavailable it
  silently falls back to the scripted simulation. Omit the flag for a fully
  offline run.
- Missed keywords print a hint plus a model reply for study.
- The transcript (every beat, your reply, per-beat scores, overall grade) is
  saved as JSON to `candid_data/sre_drills/`.

## For developers

- `SCENARIOS` / `WARROOMS`: plain data dicts, easy to extend with new trees.
- Pure, testable core: `run_drill_scripted(name, answers)`,
  `run_warroom_scripted(name, replies)`, `score_reply(reply, expect)`,
  `grade(pct)`, `best_choice_index(step)`. The interactive CLI wrappers
  (`cmd_drill`, `cmd_warroom`) are thin.
- `register(subparsers)` adds `drill` and `warroom` (each with
  `p.set_defaults(func=dispatch)`); `dispatch(args)` reads `args.sre_cmd`.
- Results dir is resolved lazily from `C.DATA_DIR`, so tests can override it
  with `CANDID_DATA_DIR`.
- Timer uses a daemon thread + `_input_with_timeout`; a timeout counts as a
  missed step and follows the first choice's branch.

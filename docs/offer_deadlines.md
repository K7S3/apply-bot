# Offer deadline manager (`candid offer deadline`)

Attach a decision deadline to each offer so exploding offers never sneak up
on you, and rank competing offers with a weighted decision framework when
the money alone does not decide it.

Deadlines live in a sidecar file, `candid_data/offer_deadlines.json`, keyed
by offer id. `candid/offer.py` is never modified — deadlines are read
alongside offers via `offer.list_offers()`.

## Commands

```bash
# set a decision deadline (YYYY-MM-DD) on offer #1
python -m candid offer deadline set --id 1 --date 2026-10-15

# clear it again
python -m candid offer deadline set --id 1 --date 2026-10-15 --clear

# countdown, most urgent first (exploding offers flagged)
python -m candid offer deadline list

# weighted decision framework across two or more offers
python -m candid offer deadline decide --weights comp=5,growth=4,team=3,location=2,stability=3 \
    --scores '1:{"growth":8,"team":7,"location":6,"stability":7},2:{"growth":9,"team":8,"location":5,"stability":6}'
```

## Countdown

`offer_deadlines.list_deadlines()` merges deadlines with offer records and
sorts by urgency. Each entry carries `days_left`; fewer than
`EXPLODING_DAYS` (7) sets `exploding: True`. `render_countdown()` prints the
list with `EXPLODING OFFER` flags and a nudge to negotiate an extension or
decide now.

## Weighted decision framework

`score_offers(weights, scores)` ranks offers on five criteria:

| Criterion | Score source |
|---|---|
| `comp` | derived from `offer.normalize()` (`normalized_annual`), scaled 0-10 so the best offer scores 10 |
| `growth` | your gut score, 0-10 |
| `team` | your gut score, 0-10 |
| `location` | your gut score, 0-10 |
| `stability` | your gut score, 0-10 |

Weights are user-supplied (missing criteria default to 1). The total is a
weighted average on a 0-10 scale. `render_decision()` prints a ranked table
with each offer's decision deadline, then a **"what would change my mind"**
section: for each runner-up, the one or two criterion-score bumps (e.g.
"raise team from 7/10 to 8.4/10") that would let it tie the winner. If no
single 0-10 score change closes the gap, it says so — the winner wins on
the merits you weighted.

Before deciding, the render asks you to pressure-test the weights: would
you still pick it if comp counted half as much?

## Python API

```python
from candid import offer_deadlines as OD

OD.set_deadline(offer_id=1, deadline="2026-10-15")  # dict record
OD.get_deadline(1)                                  # dict | None
OD.remove_deadline(1)                               # True if one existed
OD.list_deadlines(today=date(2026, 9, 22))           # urgency-sorted
print(OD.render_countdown())

rows = OD.score_offers({"comp": 5, "growth": 4, "team": 3,
                        "location": 2, "stability": 3},
                       scores={1: {"growth": 8, "team": 7,
                                   "location": 6, "stability": 7}})
print(OD.render_decision(weights, scores=scores))
```

Every public function takes optional `data_dir` (and `offers_path`) params
so tests can use tmp dirs. Errors are `OfferDeadlineError` with clean
messages that end in the next command to run.

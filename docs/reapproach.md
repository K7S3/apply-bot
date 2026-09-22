# Re-approach tracker (`candid reapproach`)

Some companies say no for timing reasons, not fit reasons. The re-approach
tracker keeps a small watchlist of companies worth retrying later:
company, last-contact date, suggested retry dates computed 6 and 12 months
out, a note on why it is worth retrying, and a status.

Stored at `candid_data/reapproach.json` (git-ignored). Stdlib only.

## Commands

```bash
# add a company to the watchlist
python -m candid reapproach add --company Acme --last-contact 2026-09-01 \
    --reason "hiring freeze, recruiter said retry in spring"

# full watchlist, soonest retry date first
python -m candid reapproach list

# companies whose retry date has arrived
python -m candid reapproach due

# after reaching out (or to snooze/escalate)
python -m candid reapproach mark Acme --status re-approached
python -m candid reapproach mark Acme --status due

# drop an entry
python -m candid reapproach remove Acme
```

## Statuses

| Status | Meaning |
|---|---|
| `watching` | default; on the radar, retry date not yet here |
| `due` | you have decided it deserves attention (retry date may or may not have arrived) |
| `re-approached` | you reached back out; stamps `reapproached_on` and drops out of `due` |

## `due` semantics

`reapproach.due()` returns entries whose 6-month or 12-month retry date has
arrived (entries already `re-approached` are excluded), most overdue first.
Each entry is annotated with:

- `due_horizon` — `"6mo"` or `"12mo"` (whichever arrived; if both, the 12mo one)
- `due_date` — the retry date that arrived
- `days_overdue` — 0 means due today

`render_due()` prints this with the "why retry" note and the exact
`mark --status re-approached` command to run after you reach out.

## Date math

Retry dates are computed with calendar-correct month arithmetic:
2025-08-31 + 6 months = 2026-02-28 (clamped to end of February), not
an invalid date. All dates are ISO `YYYY-MM-DD` strings and are validated
on input.

## Python API

```python
from candid import reapproach as R

rec = R.add("Acme", "2026-09-01", reason="hiring freeze lifted")
R.list_companies()                 # soonest retry first
R.due(today=date(2026, 9, 22))     # arrived retry dates, most overdue first
R.mark("Acme", "re-approached")    # stamps reapproached_on
R.remove("Acme")
print(R.render_list())
print(R.render_due())
```

`mark` and `remove` accept either the numeric id or the company name
(case-insensitive). Every public function takes an optional `data_dir`
param so tests can use tmp dirs. Errors are `ReapproachError` with clean
messages that end in the next command to run.

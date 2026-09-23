# Timing analysis

Best-time-to-apply analysis mined from *your* tracker history. Every number
is descriptive of your past applications  -  the module never predicts an
outcome for a posting, never invents data to fill a gap, and labels small
samples as small.

## The honest-data policy

- **Minimum sample (`MIN_SAMPLE = 5`).** Rates and guidance are only
  derived when at least 5 applications carry the needed timing info.
  Below that, commands print per-bucket counts (rates marked `n/a`) plus
  a one-line honesty note, e.g.
  `Not enough data yet (need 5+ applications with timing info; currently 3).`
- **Guidance is data-only.** `timing analyze` writes 2-4 plain-language
  lines from your history (e.g. "your response rate is 3x higher when
  applying within 3 days of posting (n=12 vs n=9)"). When the compared
  buckets are small it hedges: "treat this as a hint, not a rule."
- **`--json`** is available on every subcommand for scripting.

## Tracker timing fields

Purely additive  -  old records without them keep working.

| Field | Meaning | Set via |
|---|---|---|
| `posted_date` | When the job was posted | `track add --posted-date` / `track update --posted-date` |
| `applied_date` | When you applied (falls back to `date_added`) | `track add --applied-date` / `track update --applied-date` |
| `deadline` | Application deadline, if posted | `track add --deadline` / `track update --deadline` |
| `first_response_date` | First substantive company response | `track update --first-response-date` |

All are stored as ISO `YYYY-MM-DD` strings; invalid dates are rejected at
write time.

```bash
python -m candid track add --company Acme --role "Data Scientist" \
    --status applied --posted-date 2026-09-18
python -m candid track update 3 --first-response-date 2026-09-24
```

A "positive" outcome for response rates = `selected_for_interview` or
`offer` (see `POSITIVE_STATUSES` in `candid/timing.py`).

## Subcommands

### `timing curve`
Response rate by posting age at apply time: buckets `0-3`, `4-7`, `8-14`,
`15-30`, `31+` days. Prints a table (`bucket | n | rate`) with ASCII bars;
below the minimum sample, counts are shown with rates marked `n/a`.

```bash
python -m candid timing curve
python -m candid timing curve --json
```

### `timing analyze`
The full timing report: overall response rate, the best and worst posting-age
windows (each with its sample size), and 2-4 guidance lines derived only
from your data. `--json` emits `overall`, `best_bucket`, `worst_bucket`,
`guidance`, `enough_data`, and `honesty_note`.

```bash
python -m candid timing analyze
python -m candid timing analyze --json
```

### `timing advise`
Per-posting advice: given a posting's posted date (and optional deadline),
recommend when to apply based on your historical windows.

```bash
python -m candid timing advise --posted-date 2026-09-20 --deadline 2026-10-15
python -m candid timing advise --company Acme --role "Data Scientist" --posted-date 2026-09-20
```

### `timing reposts`
Scan your history for postings that were reposted and report how
reposted listings perform for you vs first-run listings.

```bash
python -m candid timing reposts
```

### `timing weekday`
Response rate by the day of the week you applied (Monday-Sunday).

```bash
python -m candid timing weekday
```

### `timing deadline`
Deadline-pressure analysis: how response rate changes as the apply date
approaches the posting's deadline.

```bash
python -m candid timing deadline
```

### `timing calendar`
Upcoming application deadlines and best apply windows over the next N days
(default 14).

```bash
python -m candid timing calendar
python -m candid timing calendar --days 30
```

### `timing seasons`
Seasonal trends: response rate by month/quarter from your history.

```bash
python -m candid timing seasons
```

### `timing followups`
Follow-up timing: how the gap between applying (or interviewing) and your
first response relates to outcomes, and when nudges pay off.

```bash
python -m candid timing followups
```

## For contributors

`candid/timing.py` is the shared core  -  keep its public API stable (other
feature modules import it):

- `POSITIVE_STATUSES`, `MIN_SAMPLE`, `BUCKETS`
- `load_applications(path=None)`  -  defensive tracker read
- `get_posted_date` / `get_applied_date` (falls back to `date_added`) /
  `get_first_response_date` / `get_deadline`  -  all `date | None`
- `is_positive`, `posting_age_days` (`(applied - posted).days`, None when
  either date is missing), `bucket_posting_age`
- `response_rate` (None when empty), `enough_data(apps, n=MIN_SAMPLE)`,
  `honesty_note(apps)`
- `dispatch(a)`  -  deferred-imports the five feature modules and routes
  `a.timing_cmd` (`curve`/`analyze` -> `timing_curve`, `advise`/`reposts` ->
  `timing_advise`, `weekday`/`deadline` -> `timing_patterns`,
  `calendar` -> `timing_calendar`, `seasons`/`followups` -> `timing_trends`);
  unknown commands print the valid list and return 2.

Feature handlers take the parsed args namespace (`a.timing_cmd`, plus each
subcommand's flags like `a.json` / `a.days`) and print to stdout, returning
`None` on success or an int exit code.

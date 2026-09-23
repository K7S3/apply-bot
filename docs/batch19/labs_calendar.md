# Lab/PI Watchlist + Academic Hiring-Season Calendar

Two new candid features (batch-19): `candid/labs.py` and `candid/academic_calendar.py`.

## Lab/PI watchlist

Track labs, PIs, and fellowships you care about; scan curated jobs for them.

```bash
python -m candid labs add "Geoffrey Hinton" --affiliation "U Toronto"
python -m candid labs list
python -m candid labs remove "Geoffrey Hinton"
python -m candid labs check
python -m candid labs check --text forwarded_ad.txt cfp_email.txt
```

- Watchlist lives at `candid_data/watched_labs.json` (git-ignored). Names are
  deduped case-insensitively; `remove` is case-insensitive too.
- `labs check` scans the latest curated jobs in `candid_data/jobs.json` and
  any text files passed via `--text`. If `jobs.json` is missing (or still
  being built by the academic-feeds worker), `check` reports no hits instead
  of crashing.
- Matching is case-insensitive **substring with word awareness**: "Lab" matches
  "the AI Lab" but NOT "collaborate" (no false positives on substrings buried
  inside larger words). Multi-word names tolerate any whitespace between words
  (so line-wrapped text still matches). Matching covers job title, company,
  description, and lab/fellowship-flavored fields (`lab`, `lab_name`,
  `fellowship`, `fellowship_name`, `sponsor`).
- Hits report the matched field plus a context snippet and URL.
- Programmatic hook: `check_labs(jobs: list[dict]) -> list[dict]`, so the
  coordinator can run it over any job list (e.g. inside `jobs refresh`).

## Academic hiring-season calendar

A curated **typical/approximate** timeline of the academic job market.
Everything is labeled typical or approximate on purpose: the real market runs
on department and field timelines, not exact dates, and postdoc hiring is
year-round.

```bash
python -m candid academic calendar            # current month
python -m candid academic calendar --month 10
python -m candid academic season-status
```

Conventional shape encoded:

| Track         | Typical timing              |
|---------------|-----------------------------|
| Faculty apps  | peak ~Sep-Nov               |
| Interviews    | ~Dec-Feb                    |
| Offers        | ~Feb-Apr                    |
| Postdocs      | year-round, fall/spring bumps |
| Fellowships   | by program, no single season |

- `academic calendar [--month N]` renders one month's typical timeline.
- `academic season-status` describes where "now" falls; overlapping phases
  (e.g. February: interview tail + offer start) are listed together rather
  than forced into one label.
- Programmatic hook: `season_reminders(now=None) -> list[str]` returns
  reminder strings for the nudges system (e.g. "faculty market opens next
  month: finalize research statement"). Each reminder is framed as
  typical/approximate.

## Honest limits

- The calendar knows nothing about your field's actual deadlines; always
  check the specific program, department, or posting.
- `labs check` can only see jobs already curated into `jobs.json` (or text
  files you hand it); it is not a live board crawler.

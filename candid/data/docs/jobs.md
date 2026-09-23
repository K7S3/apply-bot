# Jobs: curated discovery

Instead of scrolling job boards, tell candid what you want and get a
scored shortlist. The best matches are saved straight into your tracker as
`saved` rows, ready for `match` and `tailor`.

## The commands

```bash
python -m candid jobs curate --role "Data Scientist" --location "New York" --remote
python -m candid jobs curate --role "Data Scientist" --level senior --limit 10
python -m candid jobs refresh --role "ML Engineer" --limit 10
python -m candid jobs list
python -m candid jobs list --json
```

## Subcommands

- `curate` — discover jobs, score them against your profile, save the best.
- `refresh` — re-run curation; reports only *new* jobs since last time.
- `list` — show the curated pipeline (tracker rows with status `saved`),
  with match scores and sources; `--json` for scripting.

## Flags (curate / refresh)

- `--role` — **required**. The wanted title, e.g. `"Data Scientist"`.
- `--location` — e.g. `"New York"`.
- `--remote` — prefer remote roles.
- `--level` — `entry`, `junior`, `mid`, `senior`, `lead`, `staff`, or
  `principal`.
- `--limit` — how many to consider (default 15).
- `--sources` — subset of sources, e.g. `--sources arbeitnow remoteok`.
- `--days` — only postings from the last N days (postings with unparseable
  dates are kept).
- `--min-score` — only save to the tracker when the match score is >= N
  (default 0 = save everything found).

## The weekly loop

1. Monday: `jobs refresh --role "Your Title" --remote --limit 15`.
2. For anything interesting: `match --app-id <id>` to check fit.
3. High fit: `tailor resume --app-id <id>`, apply, then
   `track update <id> --status applied`.

## Tips

- Keep `--role` stable week to week so `refresh` diffs are meaningful.
- Use `--min-score` once you know what a "worth applying" score looks like
  for you; start at 0 and calibrate from your `match` results.
- `jobs list` is your shortlist view; promote rows to `applied` as you
  submit.

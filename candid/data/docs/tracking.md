# Tracking: your application pipeline

The tracker is the home base. Every application you care about gets a row
with company, role, status, and notes; other commands (`match --app-id`,
`tailor --app-id`, `prep --app-id`) read from it.

## The commands

```bash
python -m candid track add --company Acme --role "Data Scientist" --status applied
python -m candid track list
python -m candid track update 3 --status selected_for_interview
python -m candid track stats
python -m candid track search acme
python -m candid track export-csv tracker.csv
```

## Subcommands

- `add` — add an application. `--company` and `--role` are required;
  `--jd-link`, `--status` (default `saved`), `--notes` are optional.
  Adding the same company/role twice does not duplicate: it tells you the
  existing id.
- `list` — list applications (newest first, up to `--limit`, default 25).
  Filter with `--status` or `--company`; `--json` for scripting.
- `update` — `python -m candid track update 3 --status applied` or
  `--notes "met hiring manager at meetup"`. Setting a status of
  `selected_for_interview` prints the exact `prep` command to run next.
- `remove` — `python -m candid track remove 3`.
- `stats` — funnel stats and conversion rates (applied -> interview ->
  offer).
- `search` — free-text search over company, role, and notes.
- `export-csv` — `python -m candid track export-csv tracker.csv`.

## Statuses

Common values: `saved`, `applied`, `selected_for_interview`, `interviewing`,
`offer`, `rejected`, `withdrawn`, `accepted`. Use them consistently so
`stats` gives you an honest funnel.

## Workflows that use the tracker

- **Curated discovery**: `jobs curate` saves promising jobs directly as
  `saved` rows (see `jobs`).
- **Gmail proposals**: `gmail import` proposes tracker entries from your
  Takeout mbox; you `confirm` or `reject` each (see `imports`).
- **Match/tailor/prep shortcut**: pass `--app-id N` instead of repeating
  `--company`/`--role`/`--jd`.

## Keeping it clean

Review the list weekly. Move stale `saved` rows to `withdrawn` or remove
them; your funnel stats are only as honest as your data entry.

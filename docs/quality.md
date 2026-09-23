# Data quality (`candid quality`)

`python -m candid quality` scans your tracker (`tracker.json`) and profile
(`profile.json`) for data problems and prints a report grouped by severity,
plus a 0–100 quality score.

```bash
python -m candid quality                        # text report + score
python -m candid quality --json                  # machine-readable issue list
python -m candid quality --min-severity warning  # hide info-level noise
python -m candid quality --fix --dry-run         # preview safe fixes
python -m candid quality --fix                   # apply safe fixes + save
```

## How it works

`candid/quality/__init__.py` is the engine: it loads the tracker and profile
(a missing or invalid `profile.json` is treated as `{}`, never an error),
builds a context dict (`data_dir`, `profile`, `today`), then imports and runs
each module listed in the `CHECKS` registry. Every module exposes
`run(apps, ctx) -> list[Issue]`, where an `Issue` carries:

- `check` - machine name, e.g. `duplicate_applications`
- `severity` - `error`, `warning`, or `info`
- `record_id` - tracker id, or `None` for global issues
- `message` - human-readable description
- `suggestion` - human-readable fix suggestion
- `auto_fix` - key naming a safe auto-fix (honored by `--fix`), or `None`
- `fix_args` - extra arguments for the fix

A check module that isn't installed is skipped (the registry is pluggable);
one that fails to import or has no `run()` raises `QualityError`, reported
cleanly with no traceback.

## Checks

| Module | What it flags |
|---|---|
| `candid.quality.duplicates` | duplicate / near-duplicate applications in the tracker |
| `candid.quality.consistency` | statuses not in the tracker schema, date or field contradictions |
| `candid.quality.completeness` | missing company / role / dates / JD links, empty profiles |
| `candid.quality.staleness` | stale `date_updated`, aging statuses, unused prep packs |

See each module's docstring for the exact check names, severities, and
suggestions it emits. To add a check: create the module, expose
`run(apps, ctx)`, and append it to `CHECKS`.

## Severities and score

- **error** (−10): broken data that affects other commands (e.g. exact duplicates)
- **warning** (−3): suspicious data worth reviewing (e.g. near-duplicates, odd statuses)
- **info** (−1): mild hygiene notes (e.g. a missing optional field)

The score starts at 100 and subtracts per severity, floored at 0.
`--min-severity {error,warning,info}` keeps only issues at or above the
given severity (`--min-severity warning` hides info-level noise).

## Safe auto-fixes (`--fix`)

Only field-level normalizations are ever auto-applied - fixes **never delete
or merge records** and never invent data. The known fixes
(`candid/quality/fixes.py`):

| Key | Behavior |
|---|---|
| `strip_whitespace` | trims `company`, `role`, `notes`, `jd_link` |
| `normalize_status` | case-insensitive match into the tracker statuses (`saved`, `applied`, `selected_for_interview`, `rejected`, `offer`, `withdrawn`); anything else is left alone |
| `fill_date_updated` | copies `date_added` when `date_updated` is missing or empty |

- `--fix --dry-run` (or `--dry-run` alone) prints what would change and saves nothing.
- `--fix` applies the fixes and saves via the tracker's `_save`, then prints the log.
- An issue whose `auto_fix` key is unknown, or whose record no longer exists,
  is logged and skipped - never applied blindly.

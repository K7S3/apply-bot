# Pipeline kanban + deadline countdowns

Two dashboard features (batch-4, workstream B), both stdlib-only.

## Pipeline kanban

`GET /api/kanban` → `dashboard.kanban_board()` returns one column per
status in `C.STATUSES`, each with a `label` and `cards` list. Every card:

| field            | source                                   |
|------------------|------------------------------------------|
| id, company, role| tracker record                           |
| days_in_stage    | whole days since `date_updated` (≥ 0)    |
| next_action      | `tracker.NEXT_ACTIONS[status]`            |
| deadline         | tracker record (`""` when unset)         |
| days_remaining   | days until `deadline` (negative = overdue, `None` = unset) |

Unknown statuses found in data are skipped (the view never 500s).

The UI (`candid/data/dashboard.html`, "Pipeline kanban" section) renders
one column per status. Moving a card:

- **Drag & drop**: HTML5 drag of a card onto a column → `POST /api/apps/<id>`
  with `{"status": <column status>}` (the pre-existing `update_status` route).
- **Dropdown on the card**: same endpoint, click-to-move.
- **Date picker on the card**: `POST /api/apps/<id>/deadline` with
  `{"deadline": "YYYY-MM-DD"}` → `dashboard.set_deadline()` →
  `tracker.update(app_id, deadline=...)`. Clearing the picker clears the
  deadline (sends `""`). 404 for unknown ids, 400 for bad date format.

## Deadline countdowns

### Data model

Tracker records may carry an optional `deadline` (ISO `YYYY-MM-DD`
string). Set via:

- `T.update(app_id, deadline="2026-10-01")` — validated by
  `tracker._validate_deadline()`; raises `TrackerError` on anything that
  is not a strict `YYYY-MM-DD` calendar date. Empty string clears it;
  `None` (omitted) leaves it untouched. Records created before this
  feature simply lack the key (`.get()`-safe everywhere).

### `dashboard.deadline_alerts(today=None)`

Lists applications *with* deadlines, sorted by urgency:

1. `overdue` — days_remaining < 0
2. `due_3d` — 0..3 days left
3. `due_7d` — 4..7 days left
4. `later` — 8+ days left

Each entry: `app_id, company, role, status, deadline, days_remaining,
bucket`. Within a bucket, entries sort by `days_remaining` ascending.
`today` is injectable for tests.

### Dashboard banner

`GET /api/deadlines` feeds the "Deadline alerts" banner section at the
top of the dashboard, colored by bucket (red = overdue, amber = ≤3d,
blue = ≤7d, green = later).

### CLI

`python -m candid deadlines [--days N]` lists upcoming deadlines from
`deadline_alerts()`, `--days N` filters to `days_remaining <= N`.

`python -m candid track update ID --deadline YYYY-MM-DD` sets a
deadline; `python -m candid track update ID --deadline ""` clears it.

## Testing

`python3 -m pytest tests/test_kanban_deadlines.py -q` — 21 tests covering
deadline validation (valid/strict-invalid/clear/omitted/unknown id),
urgency buckets + sort order + boundaries, kanban shaping
(columns == `C.STATUSES`, card fields, days_in_stage floor of 0, unknown
status safety), the HTTP routes (`GET /api/kanban`, `GET /api/deadlines`,
`POST /api/apps/<id>/deadline` 200/400/404, move-via-existing-route),
and HTML validity (parses; kanban/deadline hooks present).

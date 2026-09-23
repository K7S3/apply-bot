# Batch-19 (worker 5): NIH NRSA stipends + academic digest

Two features shipped, both additive. Nothing existing was modified except
append-only additions to `candid/salary.py`.

## 1. NIH NRSA postdoc stipends

Committed dataset: `candid/data/nrsa_stipends.json` - the Ruth L. Kirschstein
NRSA postdoctoral stipend levels by years of experience (0 through 7+).

### Verification status: VERIFIED

Numbers were verified against the real published NIH table at build time
(2026-09-22):

- Source: NIH Guide Notice **NOT-OD-26-044**, "Ruth L. Kirschstein National
  Research Service Award (NRSA) Stipends, Tuition/Fees and Other Budgetary
  Levels Effective for Fiscal Year 2026"
- URL: https://grants.nih.gov/grants/guide/notice-files/NOT-OD-26-044.html
- Fiscal year: FY2026, effective for awards made on or after October 1, 2025
  (supersedes NOT-OD-25-105)

Verified FY2026 postdoctoral levels (annual / monthly):

| Yrs exp | Annual   | Monthly |
|---------|----------|---------|
| 0       | $63,480  | $5,290  |
| 1       | $63,900  | $5,325  |
| 2       | $64,380  | $5,365  |
| 3       | $66,948  | $5,579  |
| 4       | $69,180  | $5,765  |
| 5       | $71,748  | $5,979  |
| 6       | $74,424  | $6,202  |
| 7+      | $77,076  | $6,423  |

Each dataset entry notes the fiscal year and source (NIH). The dataset is
marked `"verified": true` with `verified_on` and `verified_against` fields.

### Code (additive, in `candid/salary.py`)

- `nrsa_lookup(years: int) -> dict` - stipend for N years of experience.
  Years >= 7 map to the top ("7 or more") level, per the NIH structure.
  Negative or non-integer input raises `SalaryError`. The returned dict
  carries fiscal year, notice number, source URL, and an explicit note that
  this is the NIH NRSA scale, not a market pay rate.
- `render_nrsa(result)` / `render_nrsa_table()` - text rendering.
- `add_parsers(salary_subparsers)` - extends the existing `salary lookup`
  subparser with `--postdoc` / `--years` (no new subcommand).
- `handle_postdoc_lookup(a) -> bool` - one-line hook for the coordinator.

### Commands (after the coordinator wires the hooks in `__main__.py`)

```bash
python -m candid salary lookup --postdoc --years 2   # one level
python -m candid salary lookup --postdoc             # full table
```

Coordinator wiring (two lines, in `__main__.py`, not done by this worker):

```python
# in build_parser(), after the salary subcommands are created:
S.add_parsers(salary_subparsers)
# in cmd_salary(), at the top of the `lookup` branch:
if S.handle_postdoc_lookup(a):
    return
```

## 2. Academic digest

New module: `candid/academic_digest.py`. One command producing a
Markdown briefing:

```bash
python -m candid academic-digest          # Markdown briefing
python -m candid academic-digest --json   # raw dict for scripting
```

Sections:

1. **Upcoming fellowship deadlines** - from `candid.fellowships`
   (`upcoming()`; falls back to other likely APIs, module-level data, or
   `DATA_DIR/fellowships.json`). Renders with the sibling's own
   `render_upcoming` when available.
2. **Watched-lab hits in latest curated jobs** - from `candid.labs`
   (`load_curated_jobs()` + `check_labs()` over `DATA_DIR/jobs.json`).
3. **This month's hiring-season milestones** - from
   `candid.academic_calendar` (`season_status()` + `season_reminders()`).

Each section degrades independently to a "not configured" / "no data" line
when its source module or data is absent. Sibling modules are imported
lazily via `importlib` (never at module top level), so a missing or
half-written sibling can never break the digest. Public API:

- `build_digest(now: date | None = None) -> dict`
- `render_digest(digest) -> str`
- `add_parsers(subparsers)` - wires the top-level `academic-digest` command
  (the coordinator calls `AD.add_parsers(top_level_subparsers)`)
- `cmd_academic_digest(a)`

## Tests

`tests/test_academic_digest.py` - 29 tests, zero network, tmp
`CANDID_DATA_DIR`. Covers: JSON dataset validity against the verified NIH
table, `nrsa_lookup` for every level plus out-of-range high (maps to 7+)
and negative/non-integer (raises), existing salary behavior regression
(`add_range`/`lookup` roundtrip, `parse_posted_range`, empty DB,
`import_lca` missing-file error), the `add_parsers` CLI surface and
`handle_postdoc_lookup` hook, digest with all sources present (incl. the
real fellowships module shape), digest with each source missing or
unreadable, no-data degradation lines, Markdown structure, and `--json`
serializability.

Regression: `python -m pytest tests/test_prep_offer.py -q` - 21 passed.

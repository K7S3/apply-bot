# Bulk JD import (`candid bulk`)

Score many job descriptions at once and get a ranked shortlist instead of
scoring JDs one by one.

## Usage

```bash
python -m candid bulk --jd-dir ./jds/
python -m candid bulk --jd-files a.txt b.txt --top 10
python -m candid bulk --jd-dir ./jds/ --manifest meta.csv --min-score 60 --json
python -m candid bulk --jd-dir ./jds/ --json > ranked.json   # scripting
```

All scoring is the same `candid.match.score_match` used by `candid match`
(skills / seniority / domain / title fit, 0-100) - bulk only collects,
ranks, and renders.

## How company/role are resolved

1. `--manifest meta.csv` wins. The CSV needs `file,company,role` header
   columns (`filename` and `title` are accepted aliases); `file` is matched
   by basename, so it can be a bare name or a relative path.
2. Otherwise the filename is guessed: `AcmeCorp__Data-Scientist.txt`
   becomes company "AcmeCorp", role "Data Scientist". A bare
   `data-scientist.txt` becomes role "data scientist" with no company.
3. Otherwise the fields stay blank ("-" in the table).

## Options

- `--jd-dir DIR` - scan a directory of `.txt`/`.md` files (non-recursive,
  sorted). May be combined with `--jd-files`.
- `--jd-files a.txt b.txt` - explicit file list (any extension).
- `--top N` - show only the top N results.
- `--min-score N` - only show results scoring at least N (0-100).
- `--json` - print `{"results": [...], "warnings": [...]}` as JSON for
  scripting. Each result has `file`, `company`, `role`, `score`, `verdict`,
  and `missing_must_haves` (up to 3 missing must-have skills).

## Failure behavior

- A directory that doesn't exist, an empty directory, or no files given at
  all raises `BulkError` with the exact next command to run.
- Unreadable or too-short files are **skipped with a warning on stderr**;
  the run continues and remaining JDs are still scored and ranked.
- A malformed manifest raises `BulkError` naming the expected
  `file,company,role` header columns.
- The table prints even when some files were skipped; `--min-score` high
  enough to filter everything prints a hint to lower it.

## Example

```
$ python -m candid bulk --jd-dir ./jds/ --top 3
SCORE  VERDICT      COMPANY   ROLE                 MISSING MUST-HAVES
-----  -------      -------   ----                 ------------------
78.2   GO           AcmeCorp  Senior Data Scientist  dbt
61.4   CONDITIONAL  Beta      ML Engineer          kubernetes, spark
32.1   NO-GO        OtherCo   Frontend Developer   -

3 JD(s) ranked (top 3); highest score 78.2.
```

See also: `candid match` (single-JD scoring with full breakdown),
`candid jobs curate` (discover open postings from public feeds and save the
best to the tracker).

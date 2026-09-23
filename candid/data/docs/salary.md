# Salary: pay intelligence

Know the market before you name a number. candid keeps a local salary
database with three sources: looked-up ranges, posted ranges you capture
from JDs, and imported DOL H-1B LCA disclosure data.

## Look up a range

```bash
python -m candid salary lookup --company Acme --title "Data Scientist"
python -m candid salary lookup --company Acme --title "Data Scientist" --location "New York"
python -m candid salary lookup --company Acme --title "Data Scientist" --json
```

Flags: `--company`, `--title`, `--location`, `--json` (machine-readable).

## Import DOL H-1B LCA data

The Department of Labor publishes H-1B Labor Condition Application records
with actual offered salaries. Import a CSV export:

```bash
python -m candid salary import-lca dol_h1b.csv
python -m candid salary import-lca dol_h1b.csv --limit 5000
```

`file` is the CSV path; `--limit` caps how many rows are read. This is
real filed data, not self-reported, so it is one of the most reliable
anchors you have.

## Capture a posted range

Many states require pay ranges in postings. Save what you see:

```bash
python -m candid salary parse-range --company Acme --role "Data Scientist" --jd jd.txt
python -m candid salary parse-range --company Acme --role DS --text "Pay range $120k-$150k"
```

`--company` and `--role` are required; the text comes from `--jd` (a file)
or `--text` (pasted), plus optional `--location`.

## How to use the numbers

1. Before applying: `lookup` to sanity-check whether the role is in your
   band.
2. Before the recruiter screen: pull the posted range (`parse-range`) and
   the LCA data so your first number is anchored in reality.
3. At offer time: feed the range into `offer compare` and the `negotiate`
   playbook — never negotiate from vibes.

LCA data reflects filed H-1B wages; it skews toward larger sponsors and
does not include equity. Treat it as a base-salary anchor, not total comp.

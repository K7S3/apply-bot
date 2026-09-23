# JD change detection (`jdwatch`)

Job postings are moving targets. Companies quietly edit requirements,
move the salary band, flip remote to hybrid, or repost the same role under
a new title with altered requirements — usually without telling you.
`jdwatch` tracks all of that, locally and deterministically (stdlib only,
no network, no paid APIs).

## The workflow

```bash
# 1. Snapshot the JD when you first see the role
python -m candid jdwatch snapshot --company "Acme Corp" --role "Data Scientist" \
    --jd jd-v1.txt --url "https://example.com/jobs/123"

# 2. Later, snapshot the (possibly updated) posting again
python -m candid jdwatch snapshot --company "Acme Corp" --role "Data Scientist" \
    --jd jd-v2.txt
# → "Status: CHANGED (material) — salary band $150,000-$180,000/yr -> ..."
# → ALERT #1: material change recorded.

# 3. See exactly what changed
python -m candid jdwatch diff --company "Acme Corp" --role "Data Scientist"

# 4. Review alerts, history, and weekly digest
python -m candid jdwatch alerts --unread
python -m candid jdwatch timeline --company "Acme Corp" --role "Data Scientist"
python -m candid jdwatch digest --days 7
```

`--jd` accepts a file path, a URL, pasted text, or `-` for stdin,
everywhere a JD is accepted.

## Features

| # | Feature | Command |
|---|---------|---------|
| 1 | **JD snapshots** — content-addressed (sha256 of normalized text) store per company+role; re-snapshotting identical text is a no-op (`unchanged`) | `jdwatch snapshot` |
| 2 | **Normalization** — HTML/markdown/whitespace folding, so trivial markup edits never count as changes | automatic |
| 3 | **Change detection** — structured old-vs-new comparison: salary band, location, employment type, requirements, body text | `jdwatch snapshot`, `jdwatch diff` |
| 4 | **Requirement diff** — bullet/heading extraction with *added / removed / reworded* reporting | `jdwatch diff` |
| 5 | **Diff rendering** — unified diff of any two snapshots (`--v1`, `--v2`; default: last two) | `jdwatch diff` |
| 6 | **Repost detection** — fuzzy similarity across postings finds roles reposted with altered requirements (or byte-identical reposts) | `jdwatch reposts [--company X] [--min-sim 0.75]` |
| 7 | **Severity classification** — every change is `cosmetic` / `minor` / `material` with reason codes (see below) | automatic |
| 8 | **Alerts** — recorded when a tracked role's JD changes at/above a severity threshold; unread/read tracking, no duplicates | `jdwatch alerts [--unread] [--mark-read]` |
| 9 | **Change timeline** — per-role chronological history with severity and summary | `jdwatch timeline` |
| 10 | **Salary-band deltas** — reuses `salary.parse_posted_range`; reports band moves with % deltas | in change summaries |
| 11 | **Digest** — markdown summary of every JD change in a window | `jdwatch digest [--days 7]` |
| 12 | **Watch list** — explicitly mark roles to watch | `jdwatch watch` / `unwatch` / `list` |

## Severity rules

Highest-severity reason wins.

- **material**: salary band changed/added/removed, location changed,
  employment type changed (e.g. full-time → contract), any requirement
  added or removed, posting substantially rewritten.
- **minor**: requirements reworded without additions/removals, body text
  edited.
- **cosmetic**: only markup/whitespace/punctuation-level differences.
- **unchanged**: normalized text identical — no new snapshot is even stored.

The alert threshold defaults to `minor` (alerts on minor + material).
Override per snapshot with `--threshold material`, or globally with
`CANDID_JDWATCH_THRESHOLD=material`.

## Data files

All in the candid data dir (`CANDID_DATA_DIR` overrides):

- `jd_snapshots.jsonl` — one row per snapshot: key, company, role, url,
  source, sha256, captured_at, full text.
- `jd_watch.json` — explicitly watched company+role pairs.
- `jdwatch_alerts.jsonl` — emitted alerts with severity, reasons, summary,
  and read state.

A posting's identity is its normalized `company + role` pair, so
`--company "acme"` and `--company "Acme"` hit the same record.

## Repost detection details

`jdwatch reposts` compares the latest snapshot of every tracked posting
pair (optionally limited to `--company`). Pairs with similarity in
`[--min-sim, 1.0]` are reported with the requirement delta between them,
so a repost that quietly dropped "5+ years experience" stands out.
Similarity-1.0 pairs are labeled `IDENTICAL repost`.

## Scripting

`snapshot`, `diff`, `reposts`, `timeline`, and `alerts` all accept
`--json` for machine-readable output.

## Limits (honest)

- Field extraction is heuristic (regexes over the JD text), not an LLM:
  exotic salary formats or locations phrased unusually may be missed.
  When in doubt, `jdwatch diff` shows you the raw text diff.
- Change detection only sees what you snapshot — candid never scrapes
  postings on its own. Re-snapshot a tracked role whenever you revisit it.
- Requirement extraction looks for bullets and Requirements/Qualifications
  headings; prose-style JDs with no lists yield no requirement delta
  (body-text comparison still applies).

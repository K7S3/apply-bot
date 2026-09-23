# Academic track: postdoc kinds + fellowship database

Two features for academic job seekers, shipped in batch-19 (worker-2).

## 1. Postdoc application kind in the tracker

Applications now carry a `kind`: `industry` (default) or `postdoc`.
Legacy records without a kind are treated as `industry`, so nothing
existing changes.

### CLI

```bash
# add a postdoc application
python -m candid track add --kind postdoc --company MIT --role "Postdoc Researcher" \
  --pi "Dr. Ada Lovelace" --lab "AI Lab" \
  --funding-source "NIH F32" --deadline 2026-12-01 --start-date 2027-01-15

# list only postdoc applications
python -m candid track list --kind postdoc

# update postdoc fields later
python -m candid track update 3 --pi "Dr. Grace Hopper" --deadline 2027-01-15
```

`track list --kind` is validated (`industry` | `postdoc`, unknown kinds
are rejected). Search also covers the new fields: `track search "lovelace"`
finds by PI.

### Postdoc-aware next actions

`track list` shows academic hints for postdoc records:

- deadline within 30 days → "draft research statement"
- named PI → "email PI (<name>)"
- named lab → "contact the lab"
- unparseable deadlines are ignored silently (bad dates never crash)

Nudges also fire: a postdoc application with a deadline in the next
14 days produces a `postdoc_deadline` nudge ("Draft research statement +
email the PI").

## 2. Fellowship database

A curated list of 12 well-known postdoc/doctoral fellowships lives in
`candid/data/fellowships.json`. Every URL was verified with a live HTTP
request on 2026-09-22; the Damon Runyon Fellowship was dropped because
its fellowship page could not be verified (its `/apply/` page 404'd and
the award page timed out).

### Commands

```bash
python -m candid fellowships list               # all 12, with eligibility + deadlines
python -m candid fellowships upcoming           # deadlines in next 60 days
python -m candid fellowships upcoming --days 30
```

Exact cycle dates are rarely published far in advance, so `upcoming`
projects the next deadline from each fellowship's **typical cycle month**
(day 1 of the month) and labels it APPROXIMATE; confirm the exact date
on the funder's page. Rolling fellowships (Humboldt) are always listed.

### The 12 fellowships

| Fellowship | Org | Typical deadline month(s) | Source |
|---|---|---|---|
| Ruth L. Kirschstein Postdoctoral Individual NRSA (F32) | NIH | Apr / Aug / Dec | https://researchtraining.nih.gov/career-development/f32 |
| Postdoctoral Research Fellowships in Biology (PRFB) | NSF | Nov | https://www.nsf.gov/funding/opportunities/prfb-postdoctoral-research-fellowships-biology |
| Postdoctoral Fellowships | HFSP | Sep | https://www.hfsp.org/funding/hfsp-funding/postdoctoral-fellowships |
| EMBO Postdoctoral Fellowships | EMBO | Feb / Aug | https://www.embo.org/funding/fellowships-grants-and-career-support/postdoctoral-fellowships/ |
| Marie Sklodowska-Curie Postdoctoral Fellowships | European Commission (Horizon Europe) | Sep | https://marie-sklodowska-curie-actions.ec.europa.eu/actions/postdoctoral-fellowships |
| Newton International Fellowships | Royal Society / British Academy / Academy of Medical Sciences | Mar | https://royalsociety.org/grants/newton-international |
| AI in Science Postdoctoral Fellowship | Schmidt Sciences | annual cycle, see site | https://www.schmidtsciences.org/ai-in-science/ |
| Hanna H. Gray Fellows Program | HHMI | Dec | https://www.hhmi.org/programs/hanna-h-gray-fellows |
| Miller Institute Postdoctoral Fellowship | UC Berkeley | Oct | https://millerinstitute.berkeley.edu/fellowship |
| Humboldt Research Fellowship (postdocs) | Alexander von Humboldt Foundation | rolling | https://www.humboldt-foundation.de/en/apply/sponsorship-programmes/humboldt-research-fellowship |
| LSRF Fellowship | Life Sciences Research Foundation | Oct | https://www.lsrf.org/apply/ |
| Early-Career Awards | Wellcome | multiple rounds/year, see site | https://wellcome.org/grant-funding/schemes/early-career-awards |

### Nudges hook

`candid.fellowships.fellowship_deadlines(days=30)` returns nudge-shaped
dicts for fellowships due in the next 30 days. `candid.nudges.pending_nudges`
consumes it automatically (defensively: fellowship data problems never
break the nudge list), so `python -m candid nudges`-style flows surface
upcoming fellowship deadlines with no extra wiring.

## Implementation notes

- `candid/tracker.py` (additive only): `KINDS`, `kind_of`, `parse_deadline`,
  `postdoc_next_action`, `next_action`; new kwargs on `add`/`update`,
  `kind` filter on `list_apps`, extended `search` haystack,
  `add_parsers(track_subparsers)` for the CLI flags. `C.STATUSES` untouched.
- `candid/fellowships.py` (new): `load_fellowships`, `upcoming`,
  `fellowship_deadlines`, `render_list`, `render_upcoming`,
  `add_parsers(top_subparsers)`, `cmd_fellowships`.
- `candid/nudges.py` (additive only): `postdoc_deadline` nudges for tracked
  postdoc applications + `fellowship_deadline` nudges from the hook.

`candid/__main__.py` is intentionally untouched: the parent orchestrator
must wire the hooks with two one-liners documented in the module
docstrings (`T.add_parsers(track_subparsers)` + thread `a.kind`/`a.pi`/
`a.lab`/`a.funding_source`/`a.deadline`/`a.start_date` through
`cmd_track`, and `F.add_parsers(top_level_subparsers)`).

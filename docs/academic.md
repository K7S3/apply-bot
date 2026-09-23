# Academic track: university and research job search

Batch 19 of the candid roadmap. Everything here is local-first, free, and needs no logins or API keys.

--- consolidated from docs/batch19/feeds.md ---

# Academic and research job feeds (batch 19, worker 1)

Two features, one module (`candid/academic_feeds.py`):

1. **A generic RSS/Atom fetcher** (stdlib `xml.etree` only - no feedparser,
   no extra dependencies) plus a **user-managed registry** of university
   career-board feeds at `DATA_DIR/academic_feeds.json`.
2. **A built-in Nature Careers adapter**, registered as an opt-in source for
   `jobs curate`.

## Commands

The coordinator wires these into `__main__.py`; the module exposes
`add_parsers(subparsers)` plus `cmd_feeds*` handlers.

```bash
# list the registry (5 verified seeds ship by default)
python -m candid feeds list
python -m candid feeds list --json

# add a feed - verified with a live fetch before it is saved
python -m candid feeds add "MIT Careers" https://example.edu/jobs.rss
python -m candid feeds add "Some Board" https://example.edu/feed --no-verify  # skip check

# remove by name or URL (seeds are remembered as removed, not deleted)
python -m candid feeds remove "MIT Careers"
```

The registry feeds become the **`academic`** source for curation, and the
built-in research board is **`naturecareers`** - both are opt-in only, so
the default `jobs curate` run is unchanged:

```bash
python -m candid jobs curate --role "Postdoc" --sources naturecareers academic --limit 10
python -m candid jobs curate --role "Lecturer" --sources academic --location "Boston"
```

`jobs curate --sources` accepts any mix of the default sources
(`arbeitnow`, `remoteok`) and these opt-in ones; unknown names error out
with the full available list.

## What shipped (all verified live on 2026-09-22)

Every URL below was fetched with a real HTTP request at build time and
returned a parseable feed with actual job entries. Anything that 404'd,
required JS/login, or came back empty was dropped.

**Built-in adapter:**

| `--sources` name | Board | Feed URL | Entries at verification |
|---|---|---|---|
| `naturecareers` | Nature Careers | `https://www.nature.com/naturecareers/jobsrss/` | 20 |

**Seeded registry feeds** (`python -m candid feeds list` out of the box):

| Name | Feed URL | Entries at verification |
|---|---|---|
| Nature Careers | `https://www.nature.com/naturecareers/jobsrss/` | 20 |
| Inside Higher Ed Careers | `https://careers.insidehighered.com/jobsrss/` | 20 |
| THE UniJobs | `https://www.timeshighereducation.com/unijobs/jobsrss/` | 20 |
| HigherEdJobs - Science Faculty | `https://www.higheredjobs.com/rss/categoryFeed.cfm?catID=108` | 38 |
| HigherEdJobs - Engineering Faculty | `https://www.higheredjobs.com/rss/categoryFeed.cfm?catID=120` | 73 |

Live re-check at ship time: `academic` returned 171 normalized jobs across
all five seeds; `naturecareers` returned 20.

## What was evaluated and dropped

- **Science Careers** - dropped. No public job RSS exists: science.org
  blocks non-browser clients (403), the Atypon `showFeed` endpoints 404,
  and the one feed that does resolve
  (`showFeed?jc=science&type=etoc&feed=rss`) is the *Science* journal table
  of contents (research articles), not jobs.
- **jobs.ac.uk** - dropped. `/search/rss/` returns HTTP 500 with and without
  query parameters, and the site advertises no feed link anywhere
  (homepage and search pages checked).
- **Individual university career boards (MIT, Stanford, Oxford, Cambridge,
  UCL, ...)** - dropped. Nearly all run on Symplicity/Workday/PeopleAdmin
  behind logins or JavaScript; none of the probed ones expose a public
  job RSS (Cambridge's `/rss/` serves the site's HTML shell, not a feed).
  This is why the registry exists: if your target university publishes a
  feed, `feeds add` it yourself.

## Honest coverage limits

- The Madgex boards (Nature Careers, Inside Higher Ed, THE UniJobs) cap
  their RSS at the **20 most recent postings** - great for freshness, not
  for exhaustive search. Filter client-side with `--role` / `--days`.
- RSS entries rarely carry structured location, salary, or employer fields.
  The module applies per-feed heuristics: Madgex titles are split on
  `"Employer: Title"`; HigherEdJobs descriptions of the form
  `"Employer (City, ST)"` are parsed into company/location; a trailing
  `"(City, Country)"` is pulled off titles. Fields that cannot be
  recovered are left blank rather than guessed.
- `posted_at` is normalized to `YYYY-MM-DD` when the feed date parses;
  unparseable dates are kept raw (the curator's recency filter keeps jobs
  with unknown dates rather than dropping them).
- Feeds are fetched once per `curate` run with a 20s timeout and a polite
  User-Agent. A failing feed records a source error and the run continues
  with the others; `fetch_registry` also echoes failures to stderr.
- Job dicts follow the standard schema in `docs/adding_sources.md` and
  are deduplicated via stable `source_id`s (`sha1` of the feed guid/URL).

## Files

- `candid/academic_feeds.py` - fetcher, parser, registry, adapters, CLI
- `candid/jobs.py` - additive only: `EXTRA_ADAPTERS` registration and
  `curate()` source resolution (opt-in sources never run by default)
- `tests/test_academic_feeds.py` - 35 tests, all network mocked

--- consolidated from docs/batch19/fellowships.md ---

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

--- consolidated from docs/batch19/labs_calendar.md ---

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

--- consolidated from docs/batch19/academic_docs.md ---

# Academic CV + Research Statement (batch-19)

Two new grounded, profile-driven modules for academic / research job applications.
Nothing is ever invented: every section comes from your stored candid profile,
and sections with no data are omitted, never fabricated.

## `candid academic-cv`

Export an academic CV from your profile.

```bash
python -m candid academic-cv                 # LaTeX to stdout
python -m candid academic-cv --tex cv.tex    # write LaTeX file
python -m candid academic-cv --text          # plain text to stdout
```

Sections produced (only when the profile has data):

| Section            | Profile source        |
|--------------------|-----------------------|
| Education          | `education`           |
| Appointments       | `experience` (roles + bullets) |
| Publications       | `publications` (omitted if absent) |
| Teaching           | `teaching` (omitted if absent) |
| Grants and Service | `grants` + `service` (omitted if absent) |
| Skills             | `skills`              |

Notes:

- `publications`, `teaching`, `grants`, `service` are optional profile keys
  (strings or dicts). If they are missing or empty, the section is skipped
  cleanly — no empty headings.
- The LaTeX output is a complete `article`-class document, ASCII-safe, with
  all special characters (`& % $ # _ { } ~ ^ \`) escaped. Compile with
  `pdflatex cv.tex`.
- The module defines its own private `_latex_escape`; `candid.tailor` has no
  such helper in this worktree.

Example with a publication in the profile:

```json
// candid_data/profile.json (excerpt)
{"publications": [
  {"authors": "A. Rivera, B. Chen", "title": "Sparse attention at scale",
   "venue": "Proc. of MLConf", "year": "2023"}
]}
```

renders in LaTeX as:

```latex
\section*{Publications}
\begin{itemize}[leftmargin=*,itemsep=2pt]
\item A. Rivera, B. Chen (2023) "Sparse attention at scale." Proc. of MLConf
\end{itemize}
```

## `candid research-statement`

Generate a grounded research-statement draft from your profile.

```bash
python -m candid research-statement
python -m candid research-statement --lab "Vision Lab" --pi "Dr. Rao"
python -m candid research-statement --lab "Vision Lab" --out statement.md
```

The draft has four parts:

1. **Framing** — one paragraph; `--lab` / `--pi` tailor it to the target lab.
2. **Past Research** — bullets distilled ONLY from your profile's
   publications, projects, and experience bullets. Each bullet carries a
   *Source* tag (e.g. "experience: Research Scientist — Meridian AI Lab").
3. **Current Direction** — a synthesis of your summary, skills, domains, and
   most recent role. No future plans are stated here.
4. **Future Directions — SCAFFOLD** — clearly-marked prompts labeled
   **TODO: personalize**. These are questions for you to answer yourself
   before sending; they are never pre-filled with invented plans.

Groundedness rule: if a fact is not in your profile, it is not in the draft.
Add publications/projects to `candid_data/profile.json` to enrich sections 2
and 3.

## Wiring

Both modules expose `add_parsers(subparsers)` so the main CLI can register
them; e.g. in `candid/__main__.py`:

```python
from candid import academic_cv, research_statement
academic_cv.add_parsers(sub)
research_statement.add_parsers(sub)
```

## Tests

```bash
python3 -m unittest tests.test_academic_cv -v
```

18 tests, no network, temporary profile dir: full-profile section coverage,
graceful omission for minimal profiles, LaTeX escaping (no unescaped special
chars), ASCII safety, balanced braces, zero-invented-claims checks for the
research statement (scaffold TODOs present, no fabricated titles), and CLI
parser/file-output wiring.

--- consolidated from docs/batch19/stipends_digest.md ---

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


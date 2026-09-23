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

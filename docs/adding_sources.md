# Adding a job source

`candid/jobs.py` discovers jobs through small adapter functions registered in
`ADAPTERS`. Each adapter returns a list of normalized job dicts:

```python
{
    "source": "myboard",            # short source key (matches ADAPTERS key)
    "source_id": "myboard:12345",   # stable unique id, used for deduping
    "title": "Senior Data Scientist",
    "company": "Acme Corp",
    "location": "New York, NY",      # or "Remote"
    "url": "https://…",             # apply link
    "posted_at": "2026-09-20",      # ISO date string when available
    "description": "plain text…",    # strip HTML before returning
    "salary_text": "$150k-$180k",   # raw posted range text, optional
    "remote": False,
    "extras": {"stage": "seed"},     # optional board-specific metadata
}
```

`extras` is the escape hatch for board-specific metadata: the Wellfound and
Built In adapters put the startup stage there (`extras.stage`), which is what
`jobs curate --stage seed` matches. Adapters that don't supply a field simply
leave it out — the board-aware filters ignore missing metadata silently (see
below).

## Rules

1. **Public, no-login, no-key sources only.** If it needs auth, a key, or
   scraping behind JS, it doesn't belong here.
2. **Be polite.** One request per run, a real `User-Agent` (see `USER_AGENT`),
   and respect the source's terms of service.
3. **Normalize defensively.** Strip HTML from descriptions, trim whitespace,
   and never crash the whole run — raise `JobsError("…")` on failure; the
   curator records it and continues with the other sources.
4. **Fix mojibake.** Some feeds double-encode UTF-8. Pass human-readable
   fields through `_fix_mojibake()` (see the RemoteOK adapter).
5. **Keep `source_id` stable** across runs — that's what powers refresh
   deduping (`jobs.json` → `seen`) and the reposted detection below.

## Wiring it up

```python
def _adapt_myboard() -> list[dict]:
    payload = _get_json("https://example.com/api/jobs")  # 30s timeout, UA set
    return [ { …normalized… } for j in payload ]

ADAPTERS["myboard"] = _adapt_myboard
```

Then verify:

```
python3 -m candid jobs curate --role "data scientist" --sources myboard --limit 5
python3 -m unittest discover -s tests
```

## What happens downstream (dedupe + freshness)

Adapters are intentionally dumb; the intelligence lives in `jobs.py` and is
adapter-agnostic, so it works the same whether 2 or 10 boards are registered:

- **Cross-board dedupe** (`dedupe_cross_board`, runs right after fetch):
  listings with the same normalized title+company collapse to one. The
  keeper is the listing with the richest data — `salary_text` present wins,
  then longer description; exact ties keep the first-seen copy. The merged
  board names are recorded on the keeper as `also_seen_on`.
- **Freshness tracking** (`_record_sightings` + `jobs freshness`): every run
  stamps per-listing `first_seen` / `last_seen` in `candid_data/jobs.json`
  (keyed on normalized title+company). `jobs freshness` reports:
  - **new** — first seen during the latest run,
  - **reposted** — same normalized (title, company) sighted under a new
    `source_id` (`reposted_at` set),
  - **stale** — not seen in the last 30 days.
- **Board-aware filters** (`jobs curate --stage / --min-salary / --tech-only`):
  each is opt-in and only applies where adapters supply the metadata — jobs
  without `extras.stage`, without parseable `salary_text`, etc. pass through
  untouched. Document in `--help` exactly this behavior; never let a filter
  imply coverage the boards don't have.
- **Saved searches** (`jobs search-save / search-list / search-run`):
  curation params persist in `jobs.json` under `saved_searches`.

## Current coverage (honest)

- `arbeitnow` — Arbeitnow API (general postings, has a `/job-board-api` feed). Live and verified.
- `remoteok` — RemoteOK API (remote tech jobs). Live and verified.
- `builtin` — Built In (builtin.com) tech/startup listings. No public JSON
  API exists (probed 2026-09-22), so the adapter parses the public
  server-rendered `/jobs` page: embedded schema.org ItemList JSON-LD plus
  the job cards (company, work mode, location, salary, seniority). One
  request per run. Company size/stage and funding are not on the listing
  page (detail pages only, which we don't fetch). Live-verified 2026-09-22
  (26 listings). Captures extras `work_mode`/`seniority`/`industry`.
- `remotive` — Remotive public JSON API (`https://remotive.com/api/remote-jobs`,
  optional `?search=` param), no key, no login — remote-only roles. Salary
  captured verbatim where present; category/job type appended to the
  description. Live-verified 2026-09-22. Neither source supports server-side
  location filtering.
- `weworkremotely` — We Work Remotely public RSS feeds (programming,
  devops/sysadmin, product categories), parsed with stdlib xml only.
  Company parsed from the "Company: Title" feed convention. No salary data
  in the feeds; all listings are remote. Live-verified 2026-09-22 (56 items).
- `wellfound` — Wellfound (wellfound.com, formerly AngelList Talent).
  Currently returns no listings: there is no clean public JSON/API
  endpoint, and the public server-rendered `/jobs/search` page is a
  client-rendered Next.js shell whose embedded `__NEXT_DATA__` carries
  only viewer/feature-flag state — no job data (verified 2026-09-22).
  Results load via JS (Apollo GraphQL), which is out of scope. The
  adapter re-checks the embedded payload every run, so if Wellfound ever
  server-renders listings again they will be picked up automatically —
  but nothing is ever invented.
- `authenticjobs` — Authentic Jobs public RSS feed
  (`https://authenticjobs.com/?feed=job_feed`), no key, no login. Design and
  dev roles. Honest limits: the feed publishes only the 10 most recent
  listings, carries no salary data (`salary_text` is always empty), and
  `remote` is inferred from the location text (e.g. "Remote (US)"). Stable
  per-posting GUIDs power deduping. Live-verified 2026-09-22 (10 listings).
- `dice` — dice.com, tech jobs. Checked 2026-09-22: **no public no-login,
  no-key search endpoint exists.** The official Jobs API was shut down
  ~2017; the old public RSS feed (`dice.com/jobs/rss`) now serves the HTML
  search page instead of RSS; direct requests from programmatic clients are
  blocked. The registered adapter is therefore a documented no-op: it
  returns zero listings and never invents any. If Dice ever publishes a
  public feed again, re-enabling it is a one-line change. Scraping the
  JS-driven search page is out of scope per rule 1.
- `fourdayweek` — 4dayweek.io public JSON feed
  (`https://4dayweek.io/api/jobs`, paginated `?page=N`, 25/page), no key, no
  login — 4-day-week / reduced-hours roles. Paginates until 100 postings
  (`MAX_PER_SOURCE`) or `has_more=False`; expired postings are skipped.
  Honest limits: the list feed carries no descriptions or salary, so
  `description` is a short summary (schedule/arrangement/category/work-life
  score) and `salary_text` is blank — nothing is scraped or invented. Job
  page URLs (`https://4dayweek.io/job/{slug}`) verified 2026-09-22.
  Live-verified (100 jobs fetched).
- `remoteco` — Remote.co public RSS feed
  (`https://remote.co/remote-jobs/feed/`), parsed with stdlib
  `xml.etree` only, no key, no login — remote-only roles. Honest limit,
  checked 2026-09-22: the feed URL is public, but the server silently drops
  automated requests — every fetch from our network times out with zero
  bytes (an independent June 2026 probe recorded the same timeout for this
  exact URL). There is no login or key path, so when the feed is unreachable
  the adapter returns `[]` instead of failing the run; it still parses real
  RSS when the feed does respond, and raises `JobsError` on malformed
  feeds. Expect this source to be empty until Remote.co's feed is reachable.

Company career pages and aggregators that require login/keys are out of
scope by design — the README says so, and the CLI should never imply
coverage the boards don't have.

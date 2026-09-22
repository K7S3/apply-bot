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
}
```

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
   deduping (`jobs.json` → `seen`).

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

## Current coverage (honest)

- `arbeitnow` — Arbeitnow API (general postings, has a `/job-board-api` feed)
- `remoteok` — RemoteOK API (remote tech jobs)

That's it. Two public feeds, not the whole internet. Company career pages
and aggregators that require login/keys are out of scope by design — the
README says so, and the CLI should never imply otherwise.

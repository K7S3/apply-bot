# Adding events to the dataset

The event dataset lives at `candid/data/events.json` — a plain JSON array
you can edit with any text editor. No scraping, no API keys: entries are
curated by hand (or by you) from public organizer pages.

## Entry format

```json
{
  "id": "my-conf-2027",
  "name": "My Conference",
  "edition": "2027",
  "city": "New York",
  "country": "USA",
  "format": "in-person",
  "start": "2027-06-10",
  "end": "2027-06-11",
  "date_confidence": "verified",
  "topics": ["python", "data"],
  "roles": ["Data Scientist", "Data Engineer"],
  "audience": "mid-senior",
  "cost_usd": 500,
  "cost_note": "early-bird; workshops extra",
  "url": "https://example.com/my-conf",
  "cfp": true,
  "networking": ["hallway track", "expo"],
  "description": "One or two sentences on what it is."
}
```

Required fields: `id`, `name`, `city`, `start`, `end`, `topics`, `roles`,
`url`. Everything else has sensible defaults.

### Field guide

- **`id`**: unique, lowercase, hyphenated (`pycon-us-2027`).
- **`format`**: `in-person`, `virtual`, or `hybrid`.
- **`date_confidence`**: `verified` (you checked the organizer's site),
  `typical` (annual event, usual season, not verified), or `recurring`
  (repeating meetup, next expected date). Be honest here — unverified
  dates are flagged in every listing.
- **`topics`**: pick from the existing taxonomy where possible
  (`python`, `data`, `ai-ml`, `llm`, `mlops`, `devops`, `cloud`,
  `kubernetes`, `frontend`, `web`, `security`, `open-source`,
  `career`, `startups`, `research`, …). Run `events topics` to see it.
  New topics are fine; they just won't have networking archetypes yet —
  add one in `_ARCHETYPE_BY_TOPIC` in `candid/events.py` if you like.
- **`roles`**: job titles this event serves ("Data Scientist",
  "ML Engineer", …). Used by the ranker.
- **`audience`**: `all-levels`, `early-career`, `mid-senior`, or `senior`.
- **`cost_usd`**: ticket price in USD, `0` for free.
- **`cfp`**: whether there's an open call for proposals (speaking is the
  best networking hack there is).

## Validation

After editing, run the test suite — `load_events()` validates every
entry (unique ids, date formats, known confidence values):

```bash
python3 -m pytest tests/test_b62_events.py -q
```

## Keeping it fresh

Conference dates go stale. A good cadence: once a quarter, run
`events list --all`, check anything marked `typical` against the
organizer site, flip verified ones to `date_confidence: "verified"`,
and drop editions that already happened.

# Federal hiring tools (`federal`)

USAJOBS.gov search plus offline GS-grade tools: map your background to a
GS grade band, find matching federal occupation series, check eligibility,
look up federal pay, get federal-resume notes, and score your profile
against an announcement.

## Honest notes

- **Live search needs the free USAJOBS API key.** Sign up at
  https://developer.usajobs.gov/SignUp (free, ~2 minutes, no approval wait),
  then `export CANDID_USAJOBS_KEY=<your key>`. Without a key, `federal search`
  prints a friendly error pointing at signup — never a traceback.
- **Everything else works fully offline** with no key, no account, no login.
- `--samples` on `federal search` shows the bundled fictional demo
  announcements (clearly labeled) when you just want to see the output shape.
- Grade translations and series matches are **rough self-assessment
  estimates**, not official determinations. OPM and the agency's HR office
  make the official call for each posting.
- Pay figures are the OPM 2026 GS base tables with locality adjustments;
  confirm current-year numbers on OPM's salary-table pages before using them
  in an application or negotiation.

## Commands

```bash
# Live search (needs CANDID_USAJOBS_KEY) or demo with fictional samples
python -m candid federal search --keyword "data scientist" --samples
python -m candid federal search --keyword "data scientist" --location "New York" --limit 10
python -m candid federal search --keyword engineer --series 1550 --grade 12-13

# GS-grade translation for your background
python -m candid federal translate --title "Software Engineer" --years 5
python -m candid federal translate --title "Data Scientist" --years 3 --salary 140000

# Occupation series matching from your profile skills
python -m candid federal series

# Eligibility checklist — only what you state is used; everything else
# becomes a "confirm" action item. Nothing is assumed.
python -m candid federal eligibility
python -m candid federal eligibility --citizenship us_citizen --veteran no
python -m candid federal eligibility --citizenship us_citizen --veteran yes --federal-employee

# GS pay lookup (2026 OPM tables)
python -m candid federal pay --grade 13 --step 5
python -m candid federal pay --grade 12 --locality "New York-Newark, NY-NJ-CT-PA"

# Federal-resume checklist from your profile
python -m candid federal resume-notes

# Score your profile against an announcement (JSON dict, raw USAJOBS item,
# or plain text all accepted)
python -m candid federal score --file announcement.json

# Parse a raw USAJOBS API item into a readable announcement
python -m candid federal announce --file samples/federal_sample.json
```

Every command also accepts `--json` for machine-readable output (except
`eligibility`, which prints the plain-text checklist).

## `jobs curate` integration

`usajobs` is registered as an **opt-in** source for job curation:

```bash
python -m candid federal search --keyword "data scientist" --samples   # preview
export CANDID_USAJOBS_KEY=<your key>
python -m candid jobs curate --role "data scientist" --sources usajobs --limit 10
```

The curate role is threaded through as the USAJOBS search keyword.
Without the key, the source records the friendly signup message in the
run's errors and continues with the other sources — the run never crashes.

## Modules

- `candid/usajobs.py` — USAJOBS API search, result normalization,
  announcement parsing, opt-in curate adapter, `sample_announcements()`.
- `candid/federal.py` — GS-grade translation, occupation-series matching,
  eligibility checklist.
- `candid/fedpay.py` — GS pay tables (2026) + locality adjustments.
- `candid/fedresume.py` — federal-resume notes and announcement fit scoring.

## Tests

`tests/test_federal_cli.py` covers every `federal` subcommand at the CLI
level (mocked network; no key needed).

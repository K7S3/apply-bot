# Recruiter relationship manager

`python -m candid recruiter --help`

Candid keeps a local, private CRM for the recruiters who contact you. All
data lives in your git-ignored `candid_data/` directory (`recruiters.json`,
`recruiter_threads.json`, `recruiter_links.json`). Nothing is sent anywhere,
ever: every draft is copy-paste text for you to send yourself.

## Profiles

```bash
python -m candid recruiter add --name "Priya Shah" --company Acme --kind inhouse --tags "ml,warm"
python -m candid recruiter add --name "Bob Lee" --company Acme --kind agency --agency "TechTalent" --channel linkedin
python -m candid recruiter list
python -m candid recruiter list --kind agency --json
python -m candid recruiter update 1 --notes "prefers email over LinkedIn"
```

- `kind` is `inhouse` (company recruiter) or `agency` (staffing firm); agency
  profiles require an `--agency` name.
- Re-adding the same name + company returns the existing record instead of
  duplicating, mirroring the `track` duplicate convention.
- `block` / `unblock` maintains a do-not-engage list with reasons. Blocked
  recruiters are hidden from `list` unless you pass `--include-blocked`.

## Touch log and Gmail proposals

```bash
python -m candid recruiter touch --name "Priya Shah" --channel email \
  --summary "intro sent about the ML role" --replied
python -m candid recruiter replied 4
python -m candid recruiter thread --name "Priya Shah"
python -m candid recruiter from-gmail --file ~/Downloads/takeout.mbox
```

- `touch` records each email, LinkedIn message, or call. Add `--replied` when
  the recruiter wrote back, or mark it later with `replied <touch-id>`.
- `from-gmail` scans *your own* Gmail Takeout mbox and proposes recruiter
  profiles. The company is a heuristic **guess** and is always labeled as
  unconfirmed. Nothing is saved until you run `recruiter add` yourself.

## Who is worth replying to

```bash
python -m candid recruiter score --name "Priya Shah"
python -m candid recruiter rank --limit 10
python -m candid recruiter agency-vs-inhouse
```

- `score` shows response rate (fraction of touches that got a reply),
  touch volume, recency, and a 0-100 **worth-replying** score.
- The score is transparent and deterministic: up to 50 points for response
  rate, 20 for recency (decays over 90 days), +15 for in-house recruiters,
  and up to 15 for history volume (confidence, capped at 10 touches).
  See `candid/recruiter_scoring.py` for the exact formula.
- `agency-vs-inhouse` compares average response rates and scores so you can
  see which channel actually converts for you.

## Pipeline links, funnels, and stale threads

```bash
python -m candid recruiter link --name "Priya Shah" --app-id 3
python -m candid recruiter funnel --name "Priya Shah"
python -m candid recruiter stale --days 14
python -m candid recruiter draft --name "Priya Shah" --kind interested \
  --role "ML Engineer" --company Acme
python -m candid recruiter dupes --role "ML Engineer" --company Acme
```

- `link` ties a recruiter to a tracked application (the app must exist;
  `track` data is never modified). `funnel` shows that recruiter's
  applied-to-response/interview/offer conversion.
- `stale` flags recruiters with no touch in N days (default 14) and no
  active linked application, each with a suggested next action.
- `draft` builds reply drafts (`interested`, `not_interested`,
  `need_details`, `schedule_call`) with subject, body, and timing advice.
- `dupes` is the double-submission guard: it warns when two different
  recruiters pitched you the same company + role.

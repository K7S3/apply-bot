# schedule — interview scheduling helper

Two jobs: parse a pasted interview invite into structured fields, and draft a
reply proposing your available time slots. Stdlib only, no calendar/ICS
dependency.

## Parsing (honest, not clever)

`schedule parse` extracts dates, times, timezone hints, interviewer names,
video links, and duration with regexes — and tells you exactly what it found
versus what it couldn't:

```bash
python -m candid schedule parse --file invite.txt
cat invite.txt | python -m candid schedule parse
python -m candid schedule parse "Interview with Jane Doe on Sep 24 at 2:30 PM ET ..."
```

Output shows each parsed field plus explicit "please confirm" flags for
anything ambiguous — a year-less date (assumed to be the next occurrence),
weekday mentions with no calendar date, missing timezone, no interviewer
name, a virtual meeting with no video link, or no duration. It never guesses:
ambiguity becomes a flag, not a hallucination.

## Reply drafting

```bash
python -m candid schedule reply --company Acme --role "ML Engineer" \
  --person "Jane Doe" \
  --slots "Tue 2-4pm ET" "Wed 10am-12pm ET" "Fri 1-3pm ET"
```

Proposes 2–3 slots (your words, exactly as given). Pass the invite too and
the draft echoes back what it parsed so the recruiter can spot a mismatch:

```bash
python -m candid schedule reply --file invite.txt --slots "Tue 2-4pm ET" "Wed 10am-12pm ET"
```

Slots are free-form — include the timezone yourself (e.g. "Tue 2-4pm ET").

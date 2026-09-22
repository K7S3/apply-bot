# refreq — referral request workflow

Track who you've asked for a referral, what you asked for, and where each
request stands. Nothing is ever sent — you copy the draft and send it yourself.

Storage: `candid_data/referral_requests.json` (git-ignored).

## Lifecycle

`drafted` → `sent` → `reminded` → `connected` / `declined`

## Commands

```bash
# Add a request (starts as drafted; prints the ask draft so you can send it)
python -m candid refreq add --contact "Priya Nair" --company Acme \
  --role "ML Engineer" --connection "your team builds the ranking stack"

# List requests (optionally --status sent)
python -m candid refreq list

# Mark it sent after you send the draft yourself
python -m candid refreq update 1 --status sent

# Later: who owes you a nudge (sent, quiet > 7 days by default)
python -m candid refreq remind
python -m candid refreq remind --days 10

# After nudging, or when they reply
python -m candid refreq update 1 --status reminded
python -m candid refreq update 1 --status connected --note "referred 2026-09-22"
```

`refreq add` returns the existing record instead of duplicating when the same
contact + company + role is already tracked. `refreq update` stamps
`date_sent` / `date_reminded` / `date_closed` as the status moves.

`refreq remind` lists `sent` requests quieter than `--days` (default 7) and
prints a nudge draft in `followup.check_in`'s concise tone plus the command
to mark the request `reminded` once you've nudged.

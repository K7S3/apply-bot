# thanks — post-interview thank-you sequencer

One step per interviewer, per application: interviewer name, round, a draft
(via `followup.thank_you`), timing guidance ("same evening"), and a
pending/sent status. Nothing is ever sent — you copy the draft and send it
yourself.

Storage: `candid_data/thankyou_sequences.json` (git-ignored), keyed by app_id.

## Commands

```bash
# Plan a sequence for app #3 (use `track list` for ids)
python -m candid thanks plan --app-id 3 --company Acme --role "ML Engineer" \
  --person "Jane Doe: phone screen" --person "Sam Reed: onsite" \
  --topics "the ranking stack" --standout "my latency win"

# See all sequences, or just the ones with pending steps
python -m candid thanks list
python -m candid thanks list --status pending
python -m candid thanks list --app-id 3

# After you send each note yourself
python -m candid thanks mark-sent --app-id 3 --step 1
```

`--person` takes `"Name"` or `"Name: round"` (repeatable). `--topics` and
`--standout` feed the draft for the first-listed interviewer; for later
steps, edit the generated draft yourself.

`thanks plan` prints the full sequence with a rendered draft per step, so you
can copy and send immediately. Timing guidance on every step: send the same
evening as the interview (within 24h); next morning at the latest.
Re-planning an app_id replaces the existing sequence.

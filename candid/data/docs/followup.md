# Follow-up: emails after the interview

Most candidates never follow up; the ones who do get remembered. candid
drafts the three emails that matter, in your tone, from your profile.

## The commands

```bash
python -m candid followup thank-you --person "Jane Doe" --role "Data Scientist" --company Acme
python -m candid followup check-in --person "Jane Doe" --role "Data Scientist" --company Acme
python -m candid followup referral --person Sam --role "Data Scientist" --company Acme
```

## Subcommands

- `thank-you` — post-interview thank-you. `--person` (interviewer name),
  `--role`, `--company` required; `--topics` (what you discussed),
  `--standout` (your memorable moment, e.g. "my churn model"), `--tone`
  (`warm` default, `formal`, `concise`).
- `check-in` — nudge after applying or after silence. Same required flags;
  `--last-contact` (e.g. `"2026-09-01"`) grounds the timeline; `--tone`
  as above.
- `referral` — ask a contact for a referral. `--topics` here means your
  connection to them ("we worked together at BetaCorp").

All three share `--tone`: `warm` (default), `formal`, `concise`.

## Timing rules of thumb

- Thank-you: within 24 hours of the interview, one per interviewer,
  referencing something specific from your conversation.
- Check-in: 7-10 days after applying with no response; 5-7 days after an
  interview if they gave no timeline.
- Referral ask: before you apply, not after — a referral attached to the
  application beats one chasing it.

## Always personalize

The drafts give you structure and tone. Add one genuine detail the draft
could not know (a specific thing they said, why the team excites you)
before sending. A templated-feeling note is worse than a short sincere one.

# Negotiation email sequences (`negoseq`)

The `negotiate` command gives you the playbook and individual scripts.
`negoseq` turns an offer into a **planned, timed sequence of emails** so you
never wonder what to send next or when to send it.

## The sequence

1. **Counter-offer email** - your first ask: appreciative, specific, market-backed, with multiple paths to yes.
2. **Silence nudge** - one polite re-open after ~3 business days of quiet.
3. **Call request** - when email stalls, ask for 15 minutes with times.
4. **Deadline reply** - answer an exploding deadline calmly, with a firm date you control.
5. **Acceptance** - accept in writing, restate the agreed terms (paper trail), confirm start date.
6. **Gracious decline** - decline warmly, keep the bridge and the referral door open.

## Quick start

```bash
# Full plan: steps, timing, BATNA points, drafts
python -m candid negoseq plan --company Acme --role SWE \
  --offer-date 2026-09-22 --deadline 2026-09-30 --tone warm \
  --batna competing_offer

# One draft in a specific tone
python -m candid negoseq draft --step counter --tone assertive \
  --company Acme --role SWE --person Jane --target '$190k base'

# When should each email go out? (skips weekends)
python -m candid negoseq timing --offer-date 2026-09-22 --deadline 2026-09-30

# Track what you've sent and get the next action
python -m candid negoseq track --op start --company Acme --role SWE \
  --offer-date 2026-09-22 --deadline 2026-09-30
python -m candid negoseq track --op log --seq-id 1 --step counter --status sent
python -m candid negoseq track --op status --seq-id 1
```

## Feature reference

| Command | What it does |
|---|---|
| `plan` | Renders the whole plan as Markdown: steps + send dates, BATNA talking points, all drafts. |
| `draft --step ...` | One email (counter, nudge, call_request, deadline_reply, accept, decline) in warm / professional / assertive tone. |
| `timing` | Business-day-aware send dates: counter 1 business day after the offer (24-48h), nudge after 3 quiet business days, call request 2 days later, deadline reply 1 business day before the deadline. |
| `batna` | Talking points tuned to your BATNA kind (competing_offer, current_role, other_finals, search_only, none), with a strength rating and honesty cautions. |
| `anchor` | First-ask calculator: ~6% above your target, rounded to $1k, capped at the market band top. Errors if your target is below your walk-away. |
| `pushback` | Reply draft + tactic for: band_max, need_approval, firm_deadline, budget_freeze, other_candidate, verbal_only. |
| `accept` / `decline` | Closer drafts; acceptance restates terms, decline keeps the relationship warm. |
| `tradeoffs` | The 8 negotiable levers (base, sign-on, equity, level, early review, start date, remote, relocation), orderable by `--priorities`. |
| `package` | Compose a full package ask: `negoseq package --set base='$190k' --set sign_on='$25k'`. |
| `call` | Live-call script (open, name the ask once, trade levers, BATNA, close with a date, never accept on the call) or `--voicemail` for a 30-second message. |
| `track` | `start` / `log` / `status` / `list` sequences in `candid_data/negoseq/sequences.json`; `status` always tells you the next action. |
| `export` | Write the full plan to a Markdown file. |

## Rules the module enforces

- Never invent or inflate a competing offer; the BATNA cautions say this on every kind.
- Nothing is real until it's in writing (`pushback --kind verbal_only`, acceptance restating terms).
- Never accept on the call; always take terms away and decide by a firm date.
- Tones change the framing (opener, closers), never the facts.

This is generic educational guidance, not legal or financial advice. Read every
draft before sending; adapt the bracketed details to your situation.

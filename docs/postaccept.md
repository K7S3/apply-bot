# Post-accept milestone tracker (`postaccept`)

The job search ends at the signature; the money calendar starts there. The
`postaccept` command tracks everything between "offer accepted" and "fully
vested".

All data lives in `candid_data/postaccept.json` (git-ignored, honors
`CANDID_DATA_DIR`). Nothing is estimated from the network - every number
comes from the offer you enter.

## Workflow

```bash
# 1. Record the signed offer (start date, cash, equity grant)
python -m candid postaccept record --company Acme --role "Data Scientist" \
  --start 2026-10-05 --base 180000 --bonus-pct 15 --sign-on 20000 \
  --shares 480 --schedule 25/25/25/25 --cliff-months 12

# 2. See the cliff, the vesting calendar, and the first-year checklist
python -m candid postaccept cliff
python -m candid postaccept vest
python -m candid postaccept milestones

# 3. Check things off as you go; add your own
python -m candid postaccept done --id day-30
python -m candid postaccept add-milestone --title "Finish bootcamp" --due 2026-10-20

# 4. Track refresher grants alongside the initial grant
python -m candid postaccept refreshers --label "2027 refresher" \
  --grant-date 2027-10-05 --shares 150
python -m candid postaccept refreshers   # list

# 5. The daily driver: one sorted list of what's due
python -m candid postaccept reminders --days 60
python -m candid postaccept dashboard
```

## Features

1. **Acceptance record** (`record`) - company, role, level, start date, base,
   bonus target, sign-on, share count, grant value, vest years, yearly
   schedule (`25/25/25/25`, `40/30/20/10`, ...), cliff length. Re-recording
   refreshes the milestone template but keeps custom milestones.
2. **Cliff date** (`cliff`) - start + N months with end-of-month clamping
   (Jan 31 + 1 month = Feb 28), plus a days-remaining countdown.
3. **Vesting calendar** (`vest`) - every vesting event for the initial grant.
   Months up to the cliff accrue and pay as one lump on the cliff date;
   later months vest monthly. Totals always sum exactly to the grant.
4. **Refresher grants** (`refreshers`) - annual refreshers with their own
   grant date, share count, and schedule; they vest monthly with no cliff
   and merge into the same calendar.
5. **First-year milestones** (`milestones`) - 30/60/90-day, 6-month, and
   1-year checklist items generated from the start date, each with a short
   "what good looks like" note.
6. **Milestone tracking** (`done`, `add-milestone`) - check off milestones
   (`--undo` reopens), add custom ones (auto-slugged ids).
7. **Promotion check-ins** (`promo`) - 6/9/12-month prompts: self-review
   groundwork, the direct manager conversation, and the 12-month packet.
8. **Reminders** (`reminders`) - one sorted nudge list: upcoming vests,
   milestones due or overdue, the cliff (flagged inside 60 days), and promo
   check-ins. Pure read - nothing is sent anywhere.
9. **Tenure** (`tenure`) - days/weeks/months since the start date.
10. **Comp realization** (`comp --price N`) - vested vs unvested shares and
    dollar value at a share price, with a per-year breakdown.
11. **Dashboard** (`dashboard`) - one-screen text summary of all of the
    above.

## Notes and limits

- Vesting math is a model of the standard "1-year cliff, then monthly"
  RSU schedule, not payroll advice. Confirm withholding and exact vest
  dates with your employer's stock-plan documents.
- Share counts keep 4-decimal precision; yearly and monthly splits are
  adjusted so totals sum exactly.
- The tax note in `offer` still applies: RSUs are taxed as ordinary income
  when they vest.

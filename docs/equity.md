# Equity deep-dives

`python -m candid equity <subcommand>` — educational explainers and math
helpers for equity compensation. **Educational only: not tax, legal, or
financial advice.** Every output carries that disclaimer; talk to a qualified
tax professional before exercising options, selling shares, or deciding on an
offer.

## Explainers (reading material)

| Subcommand | What it covers |
|---|---|
| `equity types [--kind rsu\|options\|iso\|nso]` | RSU vs stock options vs ISO vs NSO cards: what each is, when it has value, tax shape, typical at, watch-outs |
| `equity lifecycle --kind rsu\|options` | Grant -> vest -> exercise -> sell walkthrough with a worked example |
| `equity iso-nso` | ISO vs NSO tax basics: exercise treatment, the 2-year/1-year holding periods, qualifying vs disqualifying dispositions, AMT, the classic traps |
| `equity glossary [--term WORD]` | 16-term glossary: vesting, cliff, strike, spread, 409A, AMT, double-trigger, fully diluted, and more |
| `equity checklist` | 12 questions to ask about equity in an offer (kind, share count, schedule, cliff, strike, 409A date, exercise window, refreshers, double-trigger, fully-diluted count, liquidation preference) |

## Calculators

| Subcommand | Example |
|---|---|
| `equity vest` | `equity vest --total 200000 --price 50 --schedule 25/25/25/25 --frequency monthly --cliff-months 12 --start 2026-01-01` — vesting timeline with dates, shares, and values; supports annual/quarterly/monthly and cliffs |
| `equity cliff` | `equity cliff --shares 4000 --months 48 --cliff-months 12` — month-by-month table showing the cliff chunk |
| `equity scenarios` | `equity scenarios --kind options --count 10000 --strike 5 --prices 10,25,50` — grant value at different share prices (options show $0 when underwater) |
| `equity exercise` | `equity exercise --count 10000 --strike 5 --fmv 25 --kind nso` — cash cost + spread + estimated tax at exercise (marginal rate is a placeholder you supply) |
| `equity refresh` | `equity refresh --grants 400000:2026:4,100000:2027:4` — how overlapping refresh grants stack year by year |
| `equity dilution` | `equity dilution --your-shares 10000 --fully-diluted 10000000 --new-pool-pct 0.15` — ownership % now and after an option-pool increase |
| `equity quiz` | `equity quiz` to see the questions, `equity quiz --answers 1,2,1,1,1,2` to score yourself (6 questions, answers 0-based) |

`--json` is supported on `types`, `vest`, and `checklist` for scripting.

## Design notes

- Vesting math assumes straight-line vesting within each schedule part and
  values every event at the grant share price (a planning simplification -
  real vests are valued at the price that day).
- `exercise` never claims to compute your tax: the marginal rate is an input
  you supply, clearly labeled a placeholder.
- Tax content sticks to stable concepts (ordinary income at RSU vest, NSO
  spread at exercise, ISO holding periods, AMT existence) and avoids citing
  specific bracket thresholds, which change yearly.

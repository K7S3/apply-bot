# Vesting schedule visualizer

`python -m candid vesting ...` turns an equity grant into a dated vesting
timeline, a cumulative-value chart, and a set of decision-support views.
Everything is driven by grant data you enter (or by offers already recorded
with `offer add`) — nothing is estimated from the network.

## Describing a grant

Every subcommand except `compare` takes a grant described one of three ways:

- `--shares N --grant-price P` — an RSU/option grant of N shares
- `--value V` — a cash-settled grant worth $V at grant
- `--offer-id N` — reuse the equity fields of recorded offer #N

Plus: `--start YYYY-MM-DD` (default today), `--years N` (default 4),
`--freq monthly|quarterly|annual` (default monthly),
`--cliff-months N` (default 12), `--schedule` (default `straight`),
`--label TEXT`.

Schedules (yearly vest percentages):

| Spec | Meaning |
|---|---|
| `straight` | Even split per year (default) |
| `amazon` | Back-loaded 5/15/40/40 (4-year grants) |
| `front` | Front-loaded 40/30/20/10 (4-year grants) |
| `custom:25/25/25/25` | Your own yearly percentages (must sum to 100, one per year) |

Amounts are rounded to whole shares (or cents) with largest-remainder, so
the timeline always sums exactly to the grant total.

## Subcommands

| Subcommand | What it does |
|---|---|
| `timeline` | Vesting event table (date / vested / cumulative / value) with `<-- CLIFF` markers and a cliff summary |
| `chart` | ASCII cumulative vested-value chart; share grants overlay bear/base/bull $/share scenarios (`--growth`, `--bear`, `--bull` are annual %) |
| `compare` | Recorded offers side by side: vested equity $ at 12/24/36/48 months (grant-date $, monthly vest, 12-mo cliff assumed) |
| `depart` | Leave-at-month-N analysis: vested vs forfeited vs vesting-in-next-12mo (`--at-month N`, required) |
| `handcuffs` | Golden handcuffs: unvested-$ remaining over time (the retention incentive your employer holds) |
| `refresher` | Stack refresher grants: `--refresher VALUE:YEARS:START` (repeatable; START is a month offset or YYYY-MM-DD). Refreshers vest straight-line monthly with no cliff |
| `tax` | Each vest as an estimated taxable-income event (RSUs are taxed as ordinary income at vest; estimate, not advice) |
| `export` | Full markdown report: grant, cliff, chart, events, departure snapshot, tax events (`--out`, `--refresher` supported) |

Prices compound monthly from the annual growth rate. For share grants the
price path starts at `--price-start` (default: grant price); dollar grants
are already dollars, so price scenarios do not apply to them.

## Examples

```bash
# timeline with cliff markers for a $200k grant starting 2026-06-01
python -m candid vesting timeline --value 200000 --start 2026-06-01

# back-loaded Amazon-style share grant, cumulative chart with scenarios
python -m candid vesting chart --shares 1000 --grant-price 50 \
  --schedule amazon --freq annual --growth 5 --bear -10 --bull 25

# compare recorded offers on a vesting basis
python -m candid vesting compare

# what do I walk away from if I leave offer #1 at month 18?
python -m candid vesting depart --offer-id 1 --at-month 18

# stack two annual refreshers onto the base grant
python -m candid vesting refresher --value 200000 \
  --refresher 40000:2:12 --refresher 40000:2:24

# full report as markdown
python -m candid vesting export --offer-id 1 --out vesting.md
```

## Assumptions (stated in the output, not hidden)

- Monthly vesting with a 12-month cliff where the CLI infers a schedule
  (offer-backed grants).
- Refreshers vest straight-line monthly with no cliff.
- `compare` uses grant-date dollars (no price change); use `chart` with
  price scenarios to stress-test the $/share path.
- Tax figures are rough US estimates, not advice; ISOs/NSOs differ.

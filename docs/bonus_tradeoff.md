# Sign-on vs base trade-off calculator

`python -m candid tradeoff ...` answers the classic negotiation question:
**"They won't move on base — how much sign-on (or equity) do I need to say
yes?"**

Everything is arithmetic on numbers *you* enter — nothing is scraped or
estimated from the network. All dollar amounts are USD.

## Subcommands

| Subcommand | What it does |
|---|---|
| `equiv` | Sign-on ↔ annual-raise equivalence. `--raise 10000 --years 4` → "a $10k/yr raise for 4 years equals a $35,460 sign-on at 5% discount ($40,000 undiscounted)". Pass `--sign-on` instead to go the other direction. |
| `project` | Year-by-year cash + equity-vesting projection for one offer (compounding raises, bonus at an attainment factor, sign-on in year 1). |
| `breakeven` | Given two offers that differ in base vs sign-on, after how many years does the higher-base offer overtake the higher-sign-on one? |
| `compare` | Multi-year side-by-side of two offers: per-year table, cumulative totals, present value, breakeven, and plain-language verdicts. |
| `counter` | "Base is $X/yr below my target" → the sign-on ask that bridges the gap over your expected tenure, with a one-line negotiation script. |
| `risk` | Guaranteed sign-on vs a probabilistic target bonus: expected-value comparison at your attainment assumption. |
| `report` | Full two-offer comparison exported as markdown. |

Every subcommand takes `--years` (horizon) and `--discount-rate` (decimal,
default 0.05). `project`/`compare`/`report` additionally take `--raise-pct`
(assumed annual base raise %, default 3) and `--attainment` (bonus payout as
a fraction of target, default 1.0).

## Two ways to feed offers in

Recorded offers (from `offer add`) or raw numbers — both work:

```bash
python -m candid offer add --company Acme --role "Data Scientist" \
    --base 180000 --sign-on 30000 --bonus-pct 10 --equity 160000
python -m candid offer add --company Beta --role "Data Scientist" \
    --base 195000 --bonus-pct 10 --equity 160000

python -m candid tradeoff breakeven --offer-a 1 --offer-b 2
python -m candid tradeoff compare --offer-a 1 --offer-b 2 --years 4

# or raw numbers, no recorded offers needed:
python -m candid tradeoff compare \
    --company-a Acme --base-a 180000 --sign-on-a 30000 --bonus-pct-a 10 \
    --company-b Beta --base-b 195000 --bonus-pct-b 10 --years 4
```

## Worked example

```
$ python -m candid tradeoff equiv --raise 10000 --years 4
A $10,000/yr raise for 4 years equals a $35,460 sign-on at a 5.0%
discount rate ($40,000 undiscounted).

$ python -m candid tradeoff breakeven --base-a 180000 --sign-on-a 0 \
    --base-b 165000 --sign-on-b 40000
Offer A's base advantage of $15,000/yr makes up offer B's $40,000 sign-on
lead after about 2.7 years. Stay less than that and B pays more; stay
longer and A pulls ahead.

$ python -m candid tradeoff counter --gap 15000 --years 3
"Base is $15,000/yr below my target. If base is capped by band, a $40,849
sign-on closes that gap over 3 years at 5% — the undiscounted total is
$45,000."
```

## The math (so you can sanity-check it)

- **Equivalence:** a raise of $R/yr for N years = sign-on of
  `R × (1 − (1+d)^−N) / d` (present value of the annuity at discount rate
  d); with d = 0 it is simply `R × N`.
- **Projection:** base compounds at `raise_pct`; bonus = base × target% ×
  attainment; sign-on lands in year 1; equity vests flat per year (or from
  `equity_total / vest_years` for recorded offers).
- **Breakeven:** solves `base_a × n + sign_on_a = base_b × n + sign_on_b`.
  If the bases are equal the curves never cross; if one offer has both the
  higher base and the higher sign-on it wins from day one.
- **Counter bridge:** ask = present value of the annual base gap over your
  expected tenure. Frame it as the bridge, not a bonus — it costs them once,
  while a base increase compounds every year.

## Tax timing, briefly

`compare` and the report include timing notes: a lump sign-on concentrates
income in year 1 and can spike your marginal bracket, while base raises
spread it. These are rough estimates, **not tax or financial advice** —
confirm against the current IRS tables and talk to a tax pro.

## Python API

```python
from candid import bonus_tradeoff as T

T.bonus_raise_equivalence(10_000, 4, discount_rate=0.05)
T.breakeven_years(180_000, 0, 165_000, 40_000)
T.compare_tradeoffs(offer_a_dict, offer_b_dict, years=4)
T.export_report(comp, path="tradeoff.md")
```

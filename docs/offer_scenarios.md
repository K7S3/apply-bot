# Offer scenario modeler

`candid/scenarios.py` answers "what is this offer actually worth if..." by
projecting recorded offers forward under explicit what-if assumptions. It
reads the same offer records as `offer add` (`candid_data/offers.json`), so
there is nothing new to enter - just new ways to look at the numbers.

## The 10 features

1. **Stock-growth presets** - `bear` (-10%/yr), `flat` (0%), `base` (+8%),
   `bull` (+20%), or any custom rate (`--growth 0.12`, `--growth 10%`).
2. **Year-by-year projections** - base (with annual raises), bonus, sign-on,
   equity vest value, and benefits per year over an N-year horizon
   (default 4). Equity slices are valued at the end-of-vest-year price:
   grant value compounded at the growth rate to the vest year. Option grants
   are modeled on grant fair value and flagged as approximate, since real
   option value depends on the strike price.
3. **Vesting-schedule modeling** - parses `vest_schedule` ("40/30/20/10");
   a leading zero encodes a cliff year ("0/34/33/33"). Falls back to
   straight-line vesting over `vest_years`.
4. **Sign-on amortization variants** - 1yr (cash), 2yr (the comparison
   convention from `offer compare`), or 4yr spread.
5. **Bonus payout scenarios** - target bonus scaled by a payout ratio
   (e.g. 80% / 100% / 120%); the guaranteed first-year bonus is used for
   year 1 when set.
6. **After-tax estimates** - per-year take-home using illustrative 2026
   federal single-filer brackets (rounded). Rough estimate, not tax advice;
   state/city tax is ignored.
7. **NPV** - future comp discounted to present value at a chosen rate
   (default 5%), so a back-loaded equity offer can be compared fairly
   against a cash-heavy one.
8. **Break-even analysis** - the first year B's cumulative comp catches A,
   and the stock-growth rate at which B's multi-year total ties A's
   (bisection search over -50%..+100%/yr; reports "none" when one offer
   wins at every plausible rate).
9. **Sensitivity analysis** - one-at-a-time nudges to growth, raises, bonus
   payout, and discount rate, ranked by how much each moves the 4-year NPV.
10. **Scenario comparison matrix** - offers x growth scenarios in one table
    (cells: NPV / 4-yr pre-tax total), exportable to markdown with the full
    assumption set spelled out.

## CLI

```bash
# 4-year projection for one offer (defaults to your top offer)
python -m candid offer scenario --company Acme
python -m candid offer scenario --company Acme --preset bull --raise 0.04
python -m candid offer scenario --company Acme --growth 10% --json --out acme_scenario.md

# offers x growth-scenarios matrix
python -m candid offer compare-scenarios
python -m candid offer compare-scenarios --growths bear,flat,base,bull --export
python -m candid offer compare-scenarios --growths 0,0.1,0.2 --json

# break-even + sensitivity
python -m candid offer breakeven --a Globex --b Acme --growth base
```

All three subcommands accept `--years`, `--raise`, `--payout`, `--discount`,
and `--json`. Exports land in `candid_data/offer_comparisons/`
(git-ignored) unless `--out` gives a path.

## Assumptions are the product

Every table and export prints the assumptions it was computed under
(horizon, growth, raises, bonus payout, discount). Change an assumption,
re-run, and the numbers move - that is the point. The model is deliberately
simple and inspectable; it is a decision aid, not a valuation.

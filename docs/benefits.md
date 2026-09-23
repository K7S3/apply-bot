# Benefits comparator

`python -m candid benefits ...` normalizes every perk into dollars so two
offers can be compared on equal footing. All math is local, from numbers
you enter; nothing is fetched from the network.

## The 13 subcommands

| Subcommand | What it computes |
|---|---|
| `health` | Annual cost of one health plan at a given medical spend (premiums + deductible + coinsurance, capped at the OOP max) |
| `healthcare` | Scenario-weighted expected healthcare cost (default low/mid/high mix, or your own `--scenario prob:spend` pairs) |
| `match` | Annual 401(k) employer match from a tiered formula like `100:3,50:2`, honoring the IRS compensation cap |
| `vesting` | Vested fraction of an employer-match balance under `cliff:N` or `graded:N` schedules |
| `pto` | PTO / sick / holiday days converted to dollars at the daily salary rate |
| `espp` | Estimated annual ESPP gain from discount %, with an optional lookback boost |
| `hsa` | HSA value: employer seed + tax savings on your pre-tax contribution |
| `fsa` | FSA value: tax savings on the election (use-it-or-lose-it caveat included) |
| `commute` | Commuter/parking value: tax savings on pre-tax deductions + employer subsidy |
| `leave` | Paid parental/family leave converted to dollars (full-pay and partial-pay weeks) |
| `stipends` | Sum of named stipends (`--set wellness=1200 --set learning=3000`) |
| `normalize` | Roll a whole package JSON into one annual $ number with a line-item breakdown |
| `compare` | Side-by-side table of two package JSONs with per-line deltas and a winner |

## Examples

```bash
# What does this health plan really cost at $8k of medical spend?
python -m candid benefits health --premium 300 --deductible 1500 \
    --coinsurance 0.2 --oop-max 6000 --spend 8000

# 401(k) match on $150k at 10% contribution, 100% of first 3% + 50% of next 2%
python -m candid benefits match --salary 150000 --contrib-pct 0.10 --formula 100:3,50:2

# What is 20 PTO days + 5 sick days worth on $150k?
python -m candid benefits pto --salary 150000 --pto-days 20 --sick-days 5

# Normalize a full package (see samples/candid/sample_benefits_a.json for the schema)
python -m candid benefits normalize --package samples/candid/sample_benefits_a.json

# Compare two offers' benefits head to head
python -m candid benefits compare \
    --package-a samples/candid/sample_benefits_a.json \
    --package-b samples/candid/sample_benefits_b.json
```

## Package JSON schema

```json
{
  "name": "Acme Corp",
  "salary": 180000,
  "bonus": 18000,
  "marginal_tax_rate": 0.24,
  "health": {"monthly_premium": 180, "deductible": 1500,
             "coinsurance": 0.2, "oop_max": 5000, "annual_spend": 6000},
  "match": {"formula": "100:3,50:2", "employee_contrib_pct": 0.10},
  "pto": {"pto_days": 20, "sick_days": 10, "holidays": 11},
  "espp": {"contribution_pct": 0.10, "discount_pct": 0.15, "lookback": true},
  "hsa": {"employer_seed": 1500, "employee_contribution": 2800},
  "fsa": {"election": 3000},
  "commute": {"monthly_pretax": 150, "monthly_subsidy": 0},
  "leave": {"weeks_full_pay": 16, "weeks_partial_pay": 0},
  "stipends": {"wellness": 1200, "learning": 5000},
  "other_cash": 0
}
```

All keys except `salary` are optional. Health cost is subtracted (money you
pay); everything else adds. The normalized total feeds naturally into
`offer add --benefits <total>` for the full offer comparison.

## Caveats

Estimates, not tax advice: tax figures use a user-supplied marginal rate
and ignore state/local nuance. ESPP lookback gains are modeled with a 1.5x
multiplier on the discount gain, which is a rough average, not a promise.
PTO valuation assumes you would otherwise be paid for those days.

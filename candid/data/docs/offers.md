# Offers: record and compare

When offers arrive, record them in a normalized form so you compare
apples to apples: base, bonus, equity (amortized), sign-on (amortized),
and benefits all roll up to one annualized number.

## The commands

```bash
python -m candid offer add --company Acme --role "Data Scientist" --base 180000 --equity 200000
python -m candid offer add --company Acme --role DS --base 180000 --bonus-pct 15 --equity 200000 --location "New York"
python -m candid offer list
python -m candid offer compare
python -m candid offer export --out offers.md
```

## Subcommands

- `add` — record an offer. `--company` and `--role` required. Optional:
  `--level`, `--location`, `--base`, `--bonus-pct` (target bonus %),
  `--bonus-first` (guaranteed first-year bonus $), `--equity` (total grant
  $), `--equity-type` (default `rsu`), `--vest-years` (default 4),
  `--vest-schedule`, `--benefits` (annual $ value), `--sign-on` (one-time $,
  amortized over 2 years in comparisons), `--start`, `--notes`.
- `list` / `compare` — side-by-side comparison with normalized annual comp.
- `export` — write the comparison as Markdown
  (`--out offers.md`, or the default under `candid_data/offer_comparisons/`).

## What "normalized" means

Equity is spread over the vesting schedule and the sign-on over two years,
so a $200k four-year RSU grant counts as ~$50k/yr against a $40k sign-on
counting as ~$20k/yr. This keeps a big-grant/low-base offer honest next to
a high-base/low-equity one. Check `compare` before you rank offers.

## Workflow

1. `offer add` each offer as the details arrive (update with new numbers as
   they change).
2. `offer compare` to see the true ranking.
3. `negotiate playbook` / `negotiate counter` to improve the winner
   (see `negotiate`).
4. `track update <id> --status accepted` once you sign.

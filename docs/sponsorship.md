# H-1B sponsorship signal

`python -m candid salary sponsor --company X` scores a company's H-1B
sponsorship likelihood 0-100, computed entirely from the DOL H-1B LCA
disclosure rows you imported with `salary import-lca`. No web calls, no
scraping, no invented numbers.

## What it measures

LCA disclosure data is the public record of employers filing Labor Condition
Applications, the first step of H-1B sponsorship. A company that files a lot
of LCAs, gets them certified consistently, and filed recently is more likely
to sponsor than one that files rarely, gets denied, or stopped filing years
ago. The score turns that intuition into a number.

## The formula

For the matched company, let:

- **n** = total recorded filings (all case statuses)
- **approval** = certified / n
- **recency** = recency-weighted certified share. Each filing gets a weight
  from its fiscal year: the newest year in your data counts 1.0, then 0.8,
  0.6, 0.4, and 0.2 for anything 4+ years older or with an unknown year.
  recency = sum(weight x certified) / sum(weight)
- **volume** = min(1, log10(n + 1) / log10(101)), so n = 100 filings reaches 1.0
  and n = 10 reaches about 0.52

```
score = round(100 x (0.45 x approval + 0.30 x recency + 0.25 x volume))
```

Company matching is fuzzy on purpose: "Google" matches "GOOGLE LLC" because
DOL employer names are inconsistent. Every query token must appear in the
employer name. Use the full employer name when you want precision.

## Small samples and no data

- **n = 0** -> the report says "insufficient data" and names the exact import
  command to run. A score is never fabricated.
- **n < 10** -> the score is shown but labeled "small sample - directional
  only, not decisive."

## Where it appears

- `salary sponsor --company X` prints the score with all underlying numbers.
- `jobs curate --min-sponsor N` keeps only jobs from companies scoring >= N.
  Companies with no LCA data are excluded and counted, never guessed at.
  Requires imported LCA data; without it the command errors with the exact
  import command to run.
- `match --company X` appends a one-line sponsorship summary, but only when
  LCA data is actually loaded.

## Limits (read these)

1. **LCA filings are not sponsorships.** An LCA is filed before the H-1B
   petition; certified LCAs can still be withdrawn, and petitions can be
   denied later. This is a likelihood signal, not a guarantee.
2. **It covers H-1B only.** Companies that sponsor via other routes (O-1,
   TN, green cards without H-1B) look worse here than they are.
3. **Employer names are messy.** DOL data has spelling variants and
   subsidiaries ("AMAZON WEB SERVICES INC" vs "AMAZON.COM INC"). Scores
   aggregate what the fuzzy match finds; check the matched filings count.
4. **Stale data decays slowly.** Recency weighting prefers recent filings,
   but a company that stopped sponsoring two years ago still scores on old
   volume. Re-import fresh DOL data yearly.
5. **Volume is not intent.** Big outsourcers file thousands of LCAs; the
   score reflects filing behavior, not whether *your* role would be sponsored.

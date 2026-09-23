# Batch 21: startup ecosystem jobs

Ten features for targeting startups, all local-first. No logins, no keys,
no scraping: hiring signals come from your own `jobs curate` history, and
company facts come from a registry you curate (import a CSV).

## Registry

`python -m candid startups import --csv startups.csv` - columns:
`name, stage, funding_total_usd, employees, url, remote_policy, notes`.
Stage vocabulary: `pre-seed, seed, series-a, series-b, series-c-plus, public`.
Funding accepts `$2.5M`, `500k`, `1,250,000`.

`startups list [--stage seed] [--remote-only] [--preferred] [--json]`,
`startups add`, `startups remove`, and
`startups set-stages --stages seed,series-a` (your preferred stages, used by `rank`).

## Hiring signals

`startups signals [--min-postings 2]` - per-company posting velocity
(postings per 30 days), trend (growing/flat/shrinking vs prior window),
and new-vs-repeat role ratio, computed from `candid_data/jobs.json`.
Empty history prints a plain "no curated postings yet" message.

## Ranking

`startups rank --role "ML Engineer"` - score = keyword fit x stage
preference x hiring signal, with a one-line "why" per row. Companies with
no curated data are treated neutrally, never penalized.

## Filters

`jobs curate --stage seed,series-a --size 1-50` - stage and team-size bands
(`1-10, 11-50, 51-200, 201-500, 501+`) inferred from posting text
("seed-funded", "Series A", "founding team", "team of 12"); the registry
overrides text inference when it knows the company.

## Equity evaluation

`offer equity-notes --offer-id 2` - nine due-diligence questions with
explainers (strike price, 409A value/date, option shares, fully-diluted
shares, cliff, ISO vs NSO, exercise window, dilution history). Only values
already on the offer are used; anything missing becomes an explicit
"ask the company" prompt. Nothing is invented.

`offer compare-startup --offer-a 1 --offer-b 2 [--growth low|base|high] [--growth-rate 0.25]`
- 4-year cash-vs-equity model under labeled assumptions (low 0%, base 15%,
high 40% annual equity growth), year-by-year table, break-even growth rate.
Illustrative model only; educational, not tax, legal, or financial advice.

## Prep, watchlist, digest

`prep --startup` appends a startup-interview-loop section (founder/vision
chat, technical deep-dive, take-home *planning guidance* - candid organizes
preparation, it never does the take-home work for you, reference-call prep).

`startups watch add --name "Acme AI"` then `startups watch check` -
fuzzy-matches watched names against curated jobs, appends new hits to
`startup_alerts.jsonl`, never re-alerts.

`startups digest [--markdown|--json]` - new watchlist matches since the
last digest, hiring-signal movers, startup interviews this week.

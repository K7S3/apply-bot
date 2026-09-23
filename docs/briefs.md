# Company briefs (`prep brief`)

`python -m candid prep brief --company "Acme Corp"` prints a short,
source-labeled company brief. Every `prep` pack also includes one by
default (pass `--no-brief` to skip it).

## Sources

All sources are free, keyless, and read-only. Every fact in the brief
carries its source label; nothing is ever estimated or filled in.

- **Wikipedia API** (`en.wikipedia.org/w/api.php`): the article summary
  plus company-infobox basics - type, industry, founded, headquarters,
  employees, revenue, key people. A funding sentence is pulled from the
  summary only when Wikipedia itself mentions one ("raised $X..."), and
  is labeled as such. Disambiguation pages are skipped automatically in
  favor of the "(company)"/"Inc" title variants.
- **SEC EDGAR** (`data.sec.gov`, `www.sec.gov`): for public US companies
  only. The company name is resolved to a CIK via the SEC's
  `company_tickers.json`, then the latest 10-K's XBRL company facts are
  read for Revenue, Net income, Total assets, Total liabilities, and
  Employees. When a concept has aliases (e.g. the legacy `Revenues` vs.
  `RevenueFromContractWithCustomerExcludingAssessedTax`), the row with
  the freshest period end wins, so stale legacy concepts can never
  shadow current filings. The latest 10-K filing date is also shown.

If neither source has data (private company with no Wikipedia page,
offline, no EDGAR filer match), the brief prints an explicit
**"No verified company data found"** note instead of inventing numbers -
the same honesty rule as the "no verified questions" fallback in prep
packs.

## Caching and offline behavior

- API responses are cached as JSON under `candid_data/briefs_cache/`
  (git-ignored). A cached brief is reused on repeat runs.
- `--refresh` re-fetches from the network.
- If the network is unavailable, candid falls back to the cache; with no
  cache it prints the "no verified data found" note. The brief path
  never raises on transport failure and never blocks pack generation.

## User-Agent / SEC fair-access

SEC EDGAR requires a `User-Agent` header carrying a contact email -
their edge 403s requests without one (including browser-like UAs, which
were tested). candid sends
`candid-jobsearch-copilot/0.2.0 (admin@example.com)` by default, where
the email is a documented placeholder. To identify yourself properly
per the SEC's fair-access policy, set:

```bash
export CANDID_SEC_CONTACT="Your Name you@example.com"
```

## Limits (read before quoting in an interview)

- Wikipedia infoboxes are crowd-edited and can be stale; headcount and
  revenue figures there are "as reported", not audited.
- EDGAR covers US public filers only. Private companies, non-US
  companies, and subsidiaries filing under a parent's CIK get the
  honest "no filer found" note.
- Name matching is heuristic (suffixes like "Inc."/ "Corp." are
  stripped, then substring fallback). If the wrong company resolves,
  the brief shows the CIK/ticker/Wikipedia URL so you can spot it.
- 10-K XBRL facts reflect the latest *filed* 10-K, which can lag the
  current quarter by months.
- Funding data is thin by design: only what Wikipedia's summary states.
  For a fundraise deep-dive, check the company's press page.
- Always verify anything you plan to quote against the company's own
  investor-relations page.

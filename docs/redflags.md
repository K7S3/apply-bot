# JD red-flag detector (`redflags`)

Scans a job posting for warning signs *before* you invest hours applying and
interviewing. Fully offline: pattern-based heuristics, no network, no APIs.

## Quick start

```bash
python -m candid redflags check posting.txt          # human-readable report
python -m candid redflags check posting.txt --json   # machine-readable
python -m candid redflags scan ./saved-postings/     # every .txt/.md in a dir
```

Each check returns a verdict (`clean` / `caution` / `risky`), a 0-100 risk
score, and a list of flags. Every flag carries a plain-language explanation
of *why it matters* and a concrete *suggestion* (usually: a question to ask
the recruiter).

## Flag categories

| Category | What it catches | Examples |
|---|---|---|
| `requirements` | Unrealistic or contradictory requirements | 10 years of a 3-year-old framework; junior title demanding 5+ years; 15-technology laundry lists; PhD required for non-research roles |
| `compensation` | Vague, missing, or predatory pay | No salary mentioned; "competitive salary" with no numbers; equity-only or commission-only roles |
| `culture` | High-turnover / burnout language | "Fast-paced", "wear many hats", "we're like a family", "rockstar/ninja", nights-and-weekends expectations |
| `clarity` | Undefined roles | No responsibilities section; buzzword soup; "other duties as assigned" as the whole job; no team/manager info |
| `posting-integrity` | Ghost jobs and scams | "Always accepting applications" / talent-pool language; MLM phrasing ("be your own boss", "unlimited earning potential"); too-good-to-be-true pay |
| `bait-and-switch` | Title does not match the job | Senior title with junior duties (or reverse); engineer title describing sales work; keyword-stuffed titles; "remote" that is not really remote |
| `compliance` | Legally or ethically dubious asks | Age hints ("young", "digital native"); gendered language clusters; requests for photo/DOB/marital status; 1099 misclassification signals |
| `green` | Positive signals (info only) | Posted salary range; growth path; work-life balance; transparent interview process; EEO statement; listed benefits |

Green flags never raise the risk score; the report shows a small downward
adjustment (up to -15) so genuinely good postings stand out.

## Heuristics, not verdicts

These are pattern-based heuristics. A flag means "look closer and ask about
this", not "this company is bad". The compliance explanations explicitly say
they are not legal advice. Thresholds (e.g. how many buzzwords count as
"soup") are judgment calls tuned to avoid false positives on legitimate
postings; subtle cases can slip through.

## For developers

Detectors live in `candid/redflags/` and are plain callables
`detect(text) -> list[Flag]` registered with `@register` from
`candid.redflags.core`. To add one, create a module, decorate, and add tests
in `tests/test_redflags_<name>.py` — `analyze()` picks it up automatically.
The `find_reposts()` helper in `ghostjobs.py` groups likely reposted listings
(same company+title within 90 days, or near-duplicate text).

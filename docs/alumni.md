# Alumni network mapper

Turn your LinkedIn connections into warm outreach: who you know at target
companies, which shared schools or employers give you a natural opener, and
who to contact first. Everything is local and deterministic — every score
shows its reasons, and drafts only use facts already in your network.

## Quick start (with the fictional samples)

```bash
# 1. Import the sample connections
python -m candid alumni import --csv samples/candid/sample_connections.csv

# 2. Add schools + past jobs (LinkedIn's export doesn't include schools)
python -m candid alumni enrich --csv samples/candid/sample_enrichment.csv

# 3. Onboard the sample résumé so overlap has something to match
python -m candid onboard --resume samples/candid/sample_resume.md

# 4. Find your warm paths
python -m candid alumni warm-path --company Stripe --role "ML Engineer"
python -m candid alumni prioritize --company Stripe --role "ML Engineer"
```

## With your real data

1. **Export**: LinkedIn → Me → Settings & Privacy → Data privacy →
   "Get a copy of your data" → request the archive.
2. **Import**: `python -m candid alumni import --zip LinkedIn-export.zip`
   (or `--csv Connections.csv` if you unzipped it yourself).
   Email addresses in the export are deliberately dropped on import.
3. **Enrich** (optional but recommended): build a small CSV —
   `name,school,grad_year,prev_company,start_year,end_year,notes`,
   one row per fact — then `python -m candid alumni enrich --csv schools.csv`.
   This is what powers school overlap and "bridge" detection
   (ex-employees of a target company who can intro you to former colleagues).
4. Re-import any time; enrichment, notes, and interaction logs survive
   (`--replace` wipes and starts over).

## Commands

| Command | What it does |
|---|---|
| `alumni import --csv/--zip` | Load connections into `candid_data/network.json` (git-ignored) |
| `alumni enrich --csv` | Merge schools / past jobs / tenure per contact |
| `alumni overlap [--schools] [--companies]` | Contacts sharing your schools or employers (tenure overlap flagged) |
| `alumni warm-path --company C [--role R]` | Ranked 1st-degree contacts at C + bridges (ex-employees) |
| `alumni prioritize [--company C --role R]` | Outreach queue in tiers: this-week / nurture / low |
| `alumni draft --name N --kind K` | `referral`, `info-chat`, or `reconnect` draft for N |
| `alumni coverage --company C ...` | Per-company contact counts, warmest contact, gaps |
| `alumni log --name N --kind K --note ...` | Log an interaction (met/emailed/called/coffee/messaged/other) |
| `alumni freshness` | Stale contacts (connected long ago, no recent interaction), warmest first |
| `alumni stats` | Network overview: top companies/schools, growth by year |

All list commands accept `--json` for scripting.

## How warmth scoring works

`warmth_score` is 0–100, fully explainable:

- +20 — 1st-degree connection (the base)
- +25 — shared school (from enrichment)
- +20 — works at your target company (when one is given)
- +15 — shared employer (current or past, fuzzy-matched: "Acme Inc." = "acme")
- +10 — you overlapped there at the same time (needs years on both sides)
- +8 — connected recently, or interacted recently
- +5 — you've logged an interaction before
- +5 — similar seniority (within one band)
- +5/+10 — their title shares keywords with your target role

`prioritize` blends this with role fit and company fit:
`0.5 × warmth + 0.3 × role_fit + 0.2 × company_fit`, then tiers at 65/40.

## Honest limitations

- **No 2nd-degree data.** LinkedIn's export only contains your direct
  connections, so warm paths are company-level ("who I know at Stripe"),
  not person-level ("who can intro me to Jane specifically"). Bridges —
  contacts who *used to* work at the target — are the closest substitute.
- **No schools in the export.** School overlap needs the enrichment CSV.
  Write school names in full ("University of Texas at Austin", not "UT Austin").
- **Drafts are starting points.** They never invent facts, but you should
  still personalize the opener before sending.
- Company matching is fuzzy on purpose ("Stripe, Inc." = "Stripe") and can
  occasionally over-match; the `--json` output shows exactly what matched.

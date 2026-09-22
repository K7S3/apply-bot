# candid

**Your candid job-search copilot** — profile-driven, local-first, and honest
about what it knows.

candid takes *your* résumé (or LinkedIn export) and helps with the whole
hunt: scoring job descriptions, tailoring résumés and cover letters,
tracking applications, prepping for interviews with real reported questions,
running mock coding interviews with a sandboxed judge, benchmarking salary
from public DOL data, comparing offers, and drafting follow-ups. Everything
runs on your machine; your data never leaves it.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![No paid APIs](https://img.shields.io/badge/APIs-none%20required-brightgreen.svg)](https://github.com/K7S3/candid)

## Try it in 5 minutes

```bash
git clone https://github.com/K7S3/candid.git
cd candid
pip install -r requirements.txt   # stdlib only, nothing to compile

# 1. Onboard with the fictional sample résumé (or use your own PDF/md/txt)
python -m candid onboard --resume samples/candid/sample_resume.md

# 2. Score a job description against your profile
python -m candid match --jd samples/candid/sample_jd.txt \
    --company "Acme Corp" --role "Senior Data Scientist"

# 3. Generate a tailored résumé + cover letter
python -m candid tailor resume --jd samples/candid/sample_jd.txt \
    --company "Acme Corp" --role "Senior Data Scientist"
python -m candid tailor cover-letter --jd samples/candid/sample_jd.txt \
    --company "Acme Corp" --role "Senior Data Scientist"

# 4. Track it, then build an interview prep pack when you're selected
python -m candid track add --company "Acme Corp" --role "Senior Data Scientist"
python -m candid track update 1 --status selected_for_interview
python -m candid prep --company "Capital One" --role "Senior Data Scientist" --app-id 1
```

All commands are `python -m candid <command> --help`. No accounts, no keys.

## What it does

| Command | What you get |
|---|---|
| `onboard` / `profile` | Parse your résumé or LinkedIn export into a structured profile (skills, seniority, experience). Stored as JSON you can inspect. |
| `match` | Score any JD 0–100 (skills / seniority / domain / title fit) with a GO / CONDITIONAL / NO-GO verdict. Accepts text, a file, a URL, or stdin. |
| `tailor` | Grounded résumé + cover letter in 4 tones and 2 lengths. Reorders *your* bullets; never invents experience. |
| `track` | Application tracker: add / list / update / stats with funnel + response/interview/offer rates. |
| `jobs` | Curate open postings from public feeds, score them against your profile, and save the good ones to the tracker. See [coverage](#job-source-coverage-honest) — it's two public APIs, not the whole web. |
| `prep` | Interview prep pack: real reported company questions (with source links) or an explicit "no verified questions" fallback, concept deep-dives, comp benchmark, day-before checklist. Exportable Markdown. |
| `mock` | Mock interviews: 11 seeded coding problems with a **sandboxed judge** (visible + hidden tests, hints, reference solutions), behavioral STAR practice, system-design prompts, and an optional AI interviewer. Sandboxing limits CPU/memory/files per run; note the judge is built for running *your own* practice code, not untrusted third-party code (network is not blocked at the OS namespace level). |
| `salary` | Salary intelligence: import DOL H-1B LCA disclosure data (CSV), parse posted ranges, look up p25/median/p75 by company + title with per-row source attribution. |
| `offer` | Normalize offers (base + bonus + equity/vesting + benefits) into comparable $/yr and side-by-side tables. |
| `negotiate` | BATNA playbook, scenario scripts (lowball / competing offer / exploding deadline / level pushback), and counteroffer email drafts. |
| `followup` | Thank-you, recruiter check-in, and referral-request drafts in your voice. |

## Job-source coverage (honest)

`jobs curate` pulls from **two free, no-login JSON feeds**: Arbeitnow and
RemoteOK. That's the entire coverage today. It does *not* search the web at
large, read company career pages, or touch anything behind a login — and the
CLI never claims otherwise. Adding a new public feed is a ~20-line adapter;
see [docs/adding_sources.md](docs/adding_sources.md).

## Salary data: sources and limits

- **DOL H-1B LCA disclosure data** (public CSV download from the Department
  of Labor): case-level wages with employer, title, and worksite. Import with
  `salary import-lca`. Every lookup shows p25/median/p75 *and* the source rows
  behind them.
- **Posted ranges** parsed from JDs you feed it (`salary parse-range`).
- Limits: LCA data covers H-1B filings only — it's a real signal, not the
  whole market. Small samples are labeled as such; no data is ever
  fabricated to fill a gap.

## Your data stays yours

Everything candid learns about you lives in `candid_data/` (git-ignored):
`profile.json`, `tracker.json`, `offers.json`, `salary.db`, prep packs,
tailored output, mock sessions. Delete the folder and you're forgotten.
Sample data is fictional (meet Alex Rivera) and lives in `samples/candid/`.

The only network calls candid makes:
- `jobs curate` → the two public job feeds above.
- `match --jd <url>` → fetches the JD page you pointed it at.
- `mock ai` → Gemini, **only** for conversational interview dialogue, only
  when you run it.

No analytics, no telemetry, no accounts.

## Extending it

- [docs/adding_problems.md](docs/adding_problems.md) — add coding problems to the mock judge
- [docs/adding_questions.md](docs/adding_questions.md) — add reported interview questions (source + URL required)
- [docs/adding_sources.md](docs/adding_sources.md) — add a public job feed

## Tests

```bash
python -m unittest discover -s tests -v
```

52 tests covering profile parsing, matching, tailoring, tracker, salary,
judge verdicts, problem bank, prep packs, offers, negotiation, follow-ups,
and jobs curation (mocked adapters). The mock judge is also verified by
running every problem's reference solution through it
(`python scripts/seed_problems.py --verify`).

## Legacy automation

This repo started as an automated job *applier* (Excel-driven, Playwright
browser, email summaries). That code still lives under `candid/legacy/`
(`python -m candid.legacy`) but is no longer the focus — candid the copilot
is the product now. The legacy runner expects its own `profile.yaml` /
`applications.xlsx` setup; see the docstrings in `candid/legacy/` if you're
migrating.

## License

MIT.

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

CLI niceties: `python -m candid --version`, typo-tolerant commands
(`candid macth` suggests `match`), `--json` on `match`, `track list`,
`jobs list`, and `salary lookup` for scripting, and `--jd -` reads the JD
from stdin wherever a JD is accepted. Errors never dump tracebacks — each
one ends with the exact next command to run.

## What it does

| Command | What you get |
|---|---|
| `onboard` / `profile` | Parse your résumé or LinkedIn export into a structured profile (skills, seniority, experience, domain tags). Validates the result and tells you what's missing. Stored as JSON you can inspect. |
| `match` | Score any JD 0–100 (skills / seniority / domain / title fit) with a GO / CONDITIONAL / NO-GO verdict. Section-weighted skill extraction, explicit "N+ years" handling, per-skill JD evidence, and "how to close it" pointers for missing must-haves. Accepts text, a file, a URL, or stdin. `--json` for scripting. |
| `tailor` | Grounded résumé + cover letter in 4 tones and 2 lengths. Reorders *your* bullets; never invents experience. Now ends with an **ATS keyword check** (covered vs missing JD keywords) and a **what-changed** summary. |
| `track` | Application tracker: add / list / update / stats / search / export-csv, with funnel + response/interview/offer rates and per-status next-action hints. Re-adding an existing company+role returns the existing record instead of duplicating. |
| `jobs` | Curate open postings from public feeds, score them against your profile, and save the good ones to the tracker. `--days N` for recency, `--min-score N` to gate tracker writes, cross-source dedupe, phrase-aware ranking. See [coverage](#job-source-coverage-honest) — it's two public APIs, not the whole web. |
| `prep` | Role-aware interview prep pack: real reported company questions (with source links) or an explicit "no verified questions" fallback, gap-prioritized concept deep-dives, STAR prompts built from *your* resume bullets, company-research checklist, comp talking points, day-before checklist. Exportable Markdown. |
| `mock` | Mock interviews: 15 seeded coding problems with a **sandboxed judge** (visible + hidden tests, hints, reference solutions; infinite loops fail fast per-test), behavioral STAR practice, system-design prompts, and an optional AI interviewer. Sandboxing limits CPU/memory/files per run; note the judge is built for running *your own* practice code, not untrusted third-party code (network is not blocked at the OS namespace level). |
| `salary` | Salary intelligence: import DOL H-1B LCA disclosure data (CSV), parse posted ranges, look up p25/median/p75 by company + title with per-row source attribution, plus title-level aggregation across companies. |
| `offer` | Normalize offers (base + bonus + sign-on + equity/vesting + benefits) into comparable $/yr, side-by-side tables, rough tax note, and markdown export (`offer export`). |
| `negotiate` | BATNA playbook + pre-call checklist, scenario scripts (lowball / competing offer / exploding deadline / level pushback / leveling-up / remote flexibility), and counteroffer email drafts. |
| `leverage` | Competing-offer leverage playbook: offer register with deadlines, the ethical-use playbook, deadline coordination timeline, 8 scenario scripts (disclosure / accelerate / extension / proof-sharing / match / best-and-final / exploding / graceful decline), BATNA + walk-away/target from real offers, extension email drafts, deadline tracker, disclosure honesty log, 0–100 leverage score, and an accept/negotiate/hold/decline decision plan. See [docs/leverage.md](docs/leverage.md). |
| `followup` | Thank-you, recruiter check-in, and referral-request drafts in your voice, with subject lines, timing advice, and tone options. |
| `import` | Feed in *your own exports*: `--gmail-takeout FILE.mbox` (or a directory of them) and `--linkedin-zip FILE.zip`. Gmail imports only create *proposals* — nothing touches your tracker until you confirm each one. |
| `dashboard` | Local web UI (127.0.0.1 only): funnel visualization, sortable/filterable applications table, curated-jobs workflow (curate from the UI, dismiss, tailor shortcut), match/tailor lab with keyword-coverage chips, prep cards, salary widget, and an **Import your data** section (export guides, drag-and-drop upload, proposal confirm/reject). |

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

## Privacy: you export, candid imports

**candid never connects to your accounts.** No Gmail OAuth, no Gmail API, no
LinkedIn login, no scraping, no tokens stored anywhere. You export your own
data and feed it into candid:

**Gmail (recruiter outreach, interviews, offers, rejections):**

1. Go to [Google Takeout](https://takeout.google.com).
2. Deselect all, select **Mail** only.
3. Create the export and download it, then unzip.
4. Import the `.mbox` (or the whole unzipped folder of them):

```bash
python -m candid gmail import ~/Downloads/Takeout/Mail
python -m candid gmail proposals          # review what was found
python -m candid gmail confirm <id>        # or: gmail reject <id>
```

**LinkedIn (profile, positions, skills, education):**

1. Settings & Privacy → Data Privacy → **Get a copy of your data**.
2. Download the ZIP when it's ready.
3. Import it (merge with or replace your profile):

```bash
python -m candid import --linkedin-zip ~/Downloads/linkedin_export.zip --mode merge
```

Or use the generic import entrypoint (each new source follows this pattern):

```bash
python -m candid import --gmail-takeout ~/Downloads/Takeout/Mail
```

Rules that hold for every source:

- Imported Gmail messages only become **proposals** (`candid_data/gmail_proposals.json`).
  Nothing is added to your tracker until you explicitly `confirm` each proposal.
- Re-importing the same mbox dedupes by message ID — you never get duplicates.
- The dashboard's **Import your data** section shows the same guides plus a
  file picker (`.mbox` / `.zip`) and proposal cards with Confirm/Reject buttons.

## Your data stays yours

Everything candid learns about you lives in `candid_data/` (git-ignored):
`profile.json`, `tracker.json`, `offers.json`, `salary.db`, prep packs,
tailored output, mock sessions, and `gmail_proposals.json` (pending Gmail
import proposals). Delete the folder and you're forgotten — including every
proposal and anything imported from a Takeout export or LinkedIn ZIP.
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
python3 -m pytest tests/ -q
```

249 tests covering profile parsing (incl. LinkedIn-export text and
experience dedupe), section-weighted matching with JD evidence and
missing-skill pointers, tailoring (ATS keyword check, what-changed,
never-invent guarantee), tracker (duplicate handling, search, CSV export),
salary (LCA import variants, title aggregation), judge verdicts (incl.
infinite-loop timeouts) and the problem bank, prep packs (gap-aware,
STAR prompts), offers (sign-on amortization, markdown export), negotiation
scenarios, follow-ups, jobs curation (recency/min-score filters, dedupe),
Gmail Takeout mbox import (6-kind classification, multipart handling),
LinkedIn export import, CLI UX (typo suggestions, `--json`, friendly
errors), and the dashboard HTTP endpoints (curate, dismiss, tailor-diff,
`/api/import` multipart upload, import guides, and an HTML↔API
cross-check). The mock judge is also verified by running every problem's
reference solution through it (`python scripts/seed_problems.py --verify`).

## Legacy automation

This repo started as an automated job *applier* (Excel-driven, Playwright
browser, email summaries). That code still lives under `candid/legacy/`
(`python -m candid.legacy`) but is no longer the focus — candid the copilot
is the product now. The legacy runner expects its own `profile.yaml` /
`applications.xlsx` setup; see the docstrings in `candid/legacy/` if you're
migrating.

## License

MIT.

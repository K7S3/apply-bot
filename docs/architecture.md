# candid architecture

candid is a local-first, no-accounts, no-API-keys job-search copilot. It has
two surfaces: a command-line interface (`python -m candid ...`) and a local
web dashboard (`python -m candid dashboard`).

## Big picture

```
                     +-------------------+
                     |  candid/__main__.py  |
                     |  CLI entry + command |
                     |  dispatch (COMMANDS) |
                     +---------+---------+
                               |
            +------------------+------------------+
            |                  |                  |
     candid/profile.py  candid/match.py   candid/tracker.py   ... (one module
     (onboarding)       (fit scoring)     (applications)        per feature area)
            |                  |                  |
            +------------------+------------------+
                               |
                    candid/config.py DATA_DIR
                    candid_data/
                      profile.json
                      tracker.json
                      offers.json
                      salary.db
                      prep_packs/
                      tailored/
                      gmail_proposals.json
```

- `candid/__main__.py` is the single CLI entry point. It builds an
  `argparse` parser from the `COMMANDS` / `SUBCOMMANDS` inventory and
  dispatches each command to the feature module that owns it.
- Every feature module is plain Python (mostly stdlib) that reads and writes
  files under `candid_data/` via the paths defined in `candid/config.py`.
- `candid/config.py` also holds the tracker statuses
  (`saved`, `applied`, `selected_for_interview`, `rejected`, `offer`,
  `withdrawn`), match-score thresholds, and the seniority mapping.
- Personal data lives in `candid_data/` (git-ignored). Fictional sample data
  lives in `samples/candid/` so a new user can try every command in minutes.
  Tests never touch a real `candid_data/` directory; they point
  `CANDID_DATA_DIR` at temp dirs instead.

## Module catalog

### Ingestion

- `candid/profile.py` - onboarding: parses a resume (pdf/md/txt) and/or
  LinkedIn export text into a structured JSON profile stored at
  `candid_data/profile.json`. Every downstream feature (match, tailor, prep,
  negotiate, ...) reads this profile; nothing is ever hardcoded.
- `candid/gmail.py` - Gmail auto-ingest from Google Takeout `.mbox` exports
  (mailbox + email from the stdlib). It only *proposes* tracker entries
  (recruiter outreach, interview invites, offer letters); nothing is written
  to the tracker until the user confirms (`gmail confirm <id>` or the
  dashboard). candid never connects to the Gmail account; the user exports,
  candid imports.
- `candid/linkedin.py` - LinkedIn import from LinkedIn's official data-export
  ZIP. No login, no scraping; email addresses in the export are deliberately
  not imported.

### Matching

- `candid/match.py` - job-description fit scoring (0-100 breakdown) against
  the profile: skills match, experience alignment, seniority level, and
  keyword coverage.
- `candid/tailor.py` - tailored resume + cover letter generation. Reorders
  bullets, emphasizes JD keywords, rewrites the summary around the strongest
  proof bullet. It NEVER invents employers, degrees, skills, or achievements;
  everything comes from the profile. Output goes to `candid_data/tailored/`.

### Pipeline

- `candid/tracker.py` - application tracker: add/list/update/remove, filterable
  views, full-text search, funnel stats, CSV export. Stored as JSON at
  `candid_data/tracker.json`.
- `candid/nudges.py` - pending nudges computed from tracker records:
  follow-ups due, stale saved jobs, quiet applications, upcoming interviews.
  Pure logic shared by the CLI and the dashboard; nothing here sends anything.

### Prep

- `candid/prep.py` - interview prep pack generator: company-specific
  questions (only questions actually reported for that company, with sources),
  concept deep-dives, a mock-interview checklist, and a 24-hour plan.
  Packs are Markdown files in `candid_data/prep_packs/`.
- `candid/prep_questions.py` - researched interview-question banks. Every
  question carries its source and, where known, when it was reported, so prep
  packs never invent "recently asked" questions.
- `candid/prep_concepts.py` - concept deep-dive library: self-contained
  markdown explainers (the idea in 60 seconds, a worked example, how to answer
  it, follow-ups to expect), keyed by concept tag.
- `candid/mock.py` - interactive mock interviews: coding, AI interviewer,
  behavioral, system design. Tracks attempts and shows verdicts.
- `candid/mock_judge.py` - sandboxed code judge used by `mock`. See the
  sandbox flow below.

### Intelligence

- `candid/salary.py` - salary intelligence: a local SQLite database
  (`candid_data/salary.db`) of posted pay ranges parsed from job descriptions
  plus DOL H-1B LCA disclosure rows imported from public CSVs. Every record
  carries source attribution; no data is fabricated to fill gaps.
- `candid/jobs.py` - curated job discovery: free public JSON APIs that need no
  key, no login, and no scraping. Postings are scored against the profile and
  the best feed into the tracker. Boards behind logins or that forbid
  automated access (LinkedIn, Indeed, ...) are deliberately out of scope.

### Comms

- `candid/followup.py` - post-interview follow-up drafts: thank-you emails and
  recruiter check-ins. Nothing is ever sent automatically; copy, edit, and
  send yourself.
- `candid/negotiate.py` - negotiation playbooks, recruiter scripts, counter
  drafts, BATNA framing.
- `candid/offer.py` - offer comparison and total-comp normalization, driven by
  offer data the user enters. Stored at `candid_data/offers.json`.

### Core

- `candid/__main__.py` - CLI entry and command dispatch (see above).
- `candid/config.py` - data paths, tracker statuses, score thresholds,
  seniority mapping.
- `candid/dashboard.py` - the local web dashboard. Note: there is no `coach`
  module at this commit.

## Data flows

### Onboarding to tailored application

```
onboard --resume resume.pdf --linkedin linkedin.txt
        |
        v
profile.py -> candid_data/profile.json
        |
        +---> match.py --jd jd.txt ---------> fit score (0-100) + breakdown
        |
        +---> tailor.py resume --jd jd.txt --> candid_data/tailored/<company>_<role>.md
        |       |
        |       v (tailored resume + cover letter)
        |
        +---> track add --company X --role Y -> candid_data/tracker.json
                                                     |
                                                     v
                                              nudges.py computes
                                              follow-ups due / stale / quiet
                                                     |
                                                     v
                                              dashboard overview
```

### Prep pack flow

```
python -m candid prep --company X --role Y
        |
        v
prep.py
  1. reads profile (candid/profile.py) + tracker entry (candid/tracker.py)
  2. pulls company-specific questions from prep_questions.py
     (researched banks only, each with source + date reported)
  3. maps question categories to concept tags -> deep-dives from prep_concepts.py
  4. emits candid_data/prep_packs/<company>_<role>.md
     (questions, deep-dives, mock checklist, 24-hour plan)
```

### Mock judge sandbox flow

```
python -m candid mock coding            # pick a problem from candid/data/problems/
python -m candid mock run solution.py   # submit your code
        |
        v
mock_judge.py
  1. writes your code to a FRESH temp dir (always cleaned up)
  2. for each test case: spawns a SEPARATE subprocess
       - `python -I` (isolated: no site-packages, no PYTHONPATH, no inherited env)
       - rlimits in the child: CPU seconds, address space, file size, open
         files, no core dumps
       - hard wall-clock timeout per test (default 2s); an infinite loop
         fails that test instead of hanging the run
  3. stdin/stdout only; the runner never imports anything from the network
  4. problems load from local files only (candid/data/problems/)
  5. returns verdicts: accepted / wrong answer / time limit exceeded /
     runtime error, with failing-case details
```

Known limitation: network access inside the sandbox is not blocked at the OS
level (no namespaces without root). The judge is for your own practice
solutions, not untrusted third-party code.

## config.py data paths

All paths come from `candid/config.py` and are overridable with environment
variables (tests use this for isolation):

| Constant | Default | Purpose |
|---|---|---|
| `DATA_DIR` | `./candid_data/` (or `$CANDID_DATA_DIR`) | all user data, git-ignored |
| `CONFIG_DIR` | `~/.config/candid/` (or `$CANDID_CONFIG_DIR`) | per-user config |
| `PROFILE_PATH` | `candid_data/profile.json` | structured profile |
| `TRACKER_PATH` | `candid_data/tracker.json` | application tracker |
| `OFFERS_PATH` | `candid_data/offers.json` | offer records |
| `SALARY_DB` | `candid_data/salary.db` | salary intelligence SQLite db |
| `PREP_PACKS_DIR` | `candid_data/prep_packs/` | generated prep packs |
| `TAILOR_DIR` | `candid_data/tailored/` | tailored resumes + cover letters |
| `GMAIL_PROPOSALS_PATH` | `candid_data/gmail_proposals.json` | pending gmail import proposals |
| `SAMPLES_DIR` | `./samples/candid/` | committed fictional fixtures |

## Dashboard serving model

`python -m candid dashboard` starts `dashboard.serve()`:

- Binds **127.0.0.1 only** (localhost). Never exposed to the LAN or the
  internet; the module docstring states "no accounts, no keys, no network".
- Default port **8765**; if busy it walks up to `port + 10` (8765-8774) until
  a bind succeeds.
- Opens `http://127.0.0.1:<port>/` in your browser automatically.
  Ctrl+C stops the server.
- The UI is a single self-contained file, `candid/data/dashboard.html`
  (no CDN, works fully offline). `dashboard.py` exposes the JSON API it
  talks to; the data functions (overview, import guides, tracker views) are
  importable and unit-tested independently of HTTP.
- One section per import flow: "Import your data" explains the export-only
  pattern (Takeout mbox, LinkedIn ZIP) before anything is parsed.

## Testing layout

- `tests/` holds stdlib `unittest` suites, one file per area:
  `test_core.py`, `test_match_tailor.py`, `test_ingest_track.py`,
  `test_prep_offer.py`, `test_jobs.py`, `test_dashboard.py`,
  `test_integrations.py`, `test_cli_ux.py`, `test_contrib.py`.
- Fixtures: fictional sample resume, JD, and LCA CSV under
  `samples/candid/` (committed); user data never leaves temp dirs.
- Isolation: tests set `CANDID_DATA_DIR` to a temp directory (or
  `/tmp/candid-test-<area>`) so the real `candid_data/` is never touched.
- Run everything: `python -m unittest discover -s tests -v`.
- See `docs/testing.md` for how to add a test file for a new module.

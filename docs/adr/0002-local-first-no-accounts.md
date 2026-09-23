# ADR 0002: Local-First, No Accounts, No API Keys

- Status: accepted
- Date: 2026-09-22 (retrospective; principle in place since the first commit)

## Context

candid handles the most sensitive data a job seeker has: resumes, recruiter
conversations, interview outcomes, salary history, offer letters. A design
that synced this to a cloud service or pulled it through OAuth tokens would
create an attractive breach target and force users to trust candid with
credentials to their Gmail and LinkedIn accounts. The README states the
principle outright in its "Privacy: you export, candid imports" section:
"candid never connects to your accounts. No Gmail OAuth, no Gmail API, no
LinkedIn login, no scraping, no tokens stored anywhere."

The question was how far to take it: export-only ingestion versus live
connections for convenience.

## Decision

Local-first is a hard principle, not a preference:

- **No accounts, no API keys, no OAuth.** candid never authenticates as the
  user anywhere. There are no tokens to leak because none are stored.
- **You export, candid imports.** The user downloads their own data and
  feeds the files to candid:
  - Gmail: the user exports via Google Takeout (takeout.google.com, Mail
    only) and runs `python -m candid gmail import mail.mbox`.
    `candid/gmail.py` parses the `.mbox` with stdlib `mailbox` + `email`,
    and an import only *proposes* tracker entries; nothing is written until
    the user confirms. The mbox file stays where the user put it.
  - LinkedIn: the user requests LinkedIn's official data-export archive and
    runs `python -m candid linkedin import --zip <export>.zip`.
    `candid/linkedin.py` parses the ZIP locally; automated scraping was
    rejected because it violates LinkedIn's ToS and risks the user's
    account, and email addresses in the export are deliberately not
    imported.
- **Everything runs on the machine.** Matching, tailoring, the tracker,
  salary lookups, the mock judge, and the dashboard all work offline. The
  dashboard binds 127.0.0.1 only (`candid/dashboard.py`), and its UI is a
  single self-contained HTML file with no CDN.
- **Data stays in `candid_data/`**, which is git-ignored by design; sample
  data in `samples/candid/` is fictional so new users can try every command
  without real data.

The one deliberate exception is documented in `candid/__init__.py`: the
`mock ai` interviewer dialogue uses the user's already-configured Gemini
fast path, because a local model cannot hold a real-time conversation well.
Everything else is deterministic and local.

## Consequences

- Positive: candid can never leak credentials it does not have; users keep
  full custody of their data; the tool works on a plane.
- Positive: no signup friction, no billing, no key management for a new
  user.
- Negative: ingestion is manual (export, download, import) instead of
  one-click. Mitigated by step-by-step guides in the README, the CLI
  (`gmail guide`, `linkedin guide`), and the dashboard's "Import your data"
  section.
- Negative: no automatic sync; the user's Takeout/LinkedIn exports go stale
  and must be re-imported. This is accepted as the price of the principle.
- Neutral: any future proposal to add a live integration must argue against
  this ADR explicitly and show why export-only cannot serve the need.

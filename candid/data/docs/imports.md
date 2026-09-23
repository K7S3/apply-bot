# Imports: bring your own data

candid never connects to your accounts. You export your own data and feed
it in — the candid ingestion model: Google Takeout mbox for Gmail, the
official data-export archive for LinkedIn. No OAuth, no scraping.

## The general entry point

```bash
python -m candid import --gmail-takeout mail.mbox
python -m candid import --gmail-takeout mail.mbox --max 500
python -m candid import --linkedin-zip LinkedIn-export.zip
```

Flags: `--gmail-takeout` (an `.mbox` file or a directory of them),
`--linkedin-zip`, `--mode` (`merge` default or `replace`, for LinkedIn),
`--max` (cap mbox messages read; 0 = all).

## Gmail: propose tracker entries from your inbox

```bash
python -m candid gmail import mail.mbox
python -m candid gmail import takeout-mail/ --max 1000
python -m candid gmail proposals
python -m candid gmail confirm 1
python -m candid gmail reject 2
python -m candid gmail guide
```

1. `gmail import` parses the mbox and proposes tracker entries
   (applications, recruiter outreach, interview invites) — nothing is
   written to the tracker yet.
2. `gmail proposals` lists the pending proposals.
3. `gmail confirm <id>` writes one to the tracker; `gmail reject <id>`
   dismisses it.
4. `gmail guide` prints how to export Gmail via Google Takeout.

## LinkedIn: import your official export

```bash
python -m candid linkedin guide
python -m candid linkedin import --zip LinkedIn-export.zip
python -m candid linkedin import --zip LinkedIn-export.zip --mode replace
```

- `linkedin guide` prints how to download the export (Settings & Privacy ->
  Data Privacy -> Get a copy of your data).
- `linkedin import` reads positions, skills, and education from the ZIP.
  `--zip` is required; `--mode merge` (default) folds the data into your
  existing profile, `--mode replace` overwrites it.

## Privacy notes

- Exports stay on your machine in `candid_data/` (git-ignored).
- The mbox parser only looks for job-search signals (applications,
  interviews, offers); it does not upload or summarize your mail.
- You can delete imported data by re-running `onboard` with fresh files or
  removing rows with `track remove`.

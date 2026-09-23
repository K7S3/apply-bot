# Onboarding: build your profile

Everything in candid starts from your profile: a structured record of your
name, skills, experience, and education. You create it once from your own
files, and every other command reads from it.

## The command

```bash
python -m candid onboard --resume resume.pdf
python -m candid onboard --resume resume.pdf --linkedin linkedin.txt
python -m candid onboard --resume resume.md --out /tmp/profile.json
```

Flags:

- `--resume` — resume file (`.pdf`, `.md`, or `.txt`)
- `--linkedin` — LinkedIn export file (`.txt` or `.md`)
- `--out` — where to write `profile.json` (default: `candid_data/`)

## What happens

1. candid parses your resume (and LinkedIn file, if given).
2. It saves the profile to `candid_data/` and prints a profile card.
3. Warnings tell you if it could not detect your name or any skills — that
   usually means the export needs a cleaner format.

## The candid ingestion model

You export your own data and feed it in. Google Takeout mbox for Gmail,
the official data-export archive for LinkedIn. No live account connections,
no OAuth, no scraping. See the `imports` topic.

## Viewing your profile

```bash
python -m candid profile
python -m candid profile show
```

This prints the same profile card again, from what is stored.

## Tips

- Prefer the `.md`/`.txt` resume export over PDF when you have a choice:
  parsers read them more reliably.
- Re-run `onboard` after you update your resume so later matches, tailoring,
  and prep packs use fresh data.

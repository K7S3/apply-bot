# FAQ

**Do I need the internet to use candid?**
Almost everything is offline: profile, matching, tailoring, tracker, prep
packs, the coding judge, behavioral/design practice, salary DB, offers,
and the dashboard all run locally. The exceptions: `jobs curate` fetches
live postings, and `mock ai` uses the Gemini fast path for dialogue.

**Where does my data live?**
In `candid_data/` next to where you run the commands. It is git-ignored and
never uploaded. Sample data for experimenting lives in `samples/candid/`.

**Does candid connect to my Gmail or LinkedIn accounts?**
No. You export your own data (Google Takeout mbox; LinkedIn's official
data-export archive) and import it with `import`, `gmail`, or `linkedin`.
No OAuth, no passwords, no scraping. See the `imports` topic.

**Will tailoring invent experience I do not have?**
No. Tailoring only rearranges and emphasizes what is in your profile. If a
bullet looks wrong, fix the profile (re-run `onboard` with a better
resume), not the output — and never submit claims you cannot defend.

**What does the match score mean?**
A triage signal: high scores deserve your tailoring time; low scores are
long shots. It does not predict interviews.

**How do I use a tracked job with match/tailor/prep?**
Pass `--app-id N` (the id from `track list`) instead of repeating
`--company`, `--role`, and `--jd`.

**Can I script candid?**
Yes: `match --json`, `track list --json`, `jobs list --json`, and
`salary lookup --json` emit machine-readable output; `tailor --out` and
`track export-csv` write files.

**What is `mock ai` and why does it need Gemini?**
A conversational interviewer that adapts follow-ups to your answers. Open
generation needs a model, so it uses the already-configured Gemini fast
path; every other mock mode is fully offline.

**How do I update my profile after my resume changes?**
Re-run `python -m candid onboard --resume new-resume.pdf`. Later matches,
tailoring, and prep packs use the fresh data.

**Something failed with a friendly error — what now?**
Read the "Next:" line it prints; it names the exact command to run. For a
typo'd command, candid suggests the closest real command.

**Where do I start?**
The `tutorial` topic walks the full loop: onboard -> jobs -> match ->
tailor -> track -> prep -> mock -> followup.

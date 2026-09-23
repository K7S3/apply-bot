# Prep: interview prep packs

When a role moves to interview, generate a prep pack: likely questions for
the company and role, concept deep-dives, a mock plan, and a day-of
checklist. The pack is saved to a file and previewed on screen.

## The command

```bash
python -m candid prep --company Acme --role "Data Scientist"
python -m candid prep --company Acme --role "Data Scientist" --jd jd.txt
python -m candid prep --company Acme --role "Data Scientist" --app-id 3
```

Flags:

- `--company`, `--role` — required
- `--jd` — JD text, file path, URL, or `-` (stdin); sharpens the questions
- `--location` — location context
- `--app-id` — link the pack to a tracked application

## What is in the pack

- **Company/role briefing** — what the role asks for, mapped to your profile.
- **Likely questions** — technical and behavioral questions tuned to the
  role, with pointers to which of your experiences answer each.
- **Concept deep-dives** — explanations of the key concepts the role
  requires (drawn from the built-in concept library).
- **Mock plan** — which `mock` sessions to run: coding problems, behavioral
  themes, system design level.
- **Checklist** — logistics and day-of reminders.

## Suggested prep loop

1. `python -m candid prep --company X --role Y --app-id N` — generate the pack.
2. Read the deep-dives; note weak spots.
3. `python -m candid mock ...` — drill coding, behavioral, and design
   (see the `mock` topic).
4. Re-read the likely questions the night before; bring two good questions
   of your own to ask them.

## After the interview

Draft your thank-you with `python -m candid followup thank-you ...`
(see `followup`), then `track update <id> --status interviewing` to keep the
pipeline honest.

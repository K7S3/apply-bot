# Tutorial: end-to-end walkthrough

One full loop through candid, from a blank profile to a post-interview
thank-you. Sample data in `samples/candid/` lets you try everything in
minutes; swap in your real files when ready.

## 1. Onboard — build your profile

```bash
python -m candid onboard --resume resume.pdf --linkedin linkedin.txt
```

Check the printed profile card. If the name or skills look wrong, export a
cleaner `.md`/`.txt` resume and re-run. See `onboarding`.

## 2. Jobs — find roles worth your time

```bash
python -m candid jobs curate --role "Data Scientist" --remote --limit 15
python -m candid jobs list
```

The best matches land in your tracker as `saved` rows. Each Monday, run
`jobs refresh` for only the new ones. See `jobs`.

## 3. Match — check fit before you invest

Pick a saved job and score it:

```bash
python -m candid track list
python -m candid match --app-id 3
```

Read the gaps honestly. If the fit is real, continue; if not, move on.
See `matching`.

## 4. Tailor — build the application

```bash
python -m candid tailor resume --app-id 3 --out tailored-acme.md
python -m candid tailor cover-letter --app-id 3 --hook "I loved your infra blog"
```

Review every bullet against your real experience — tailor emphasizes, it
never invents. Submit the application, then record it:

```bash
python -m candid track update 3 --status applied
```

See `tailoring` and `tracking`.

## 5. Prep — when the interview invite lands

```bash
python -m candid track update 3 --status selected_for_interview
python -m candid prep --company Acme --role "Data Scientist" --app-id 3
```

The update prints the prep command for you; the pack gives you questions,
concept deep-dives, and a checklist. See `prep`.

## 6. Mock — practice before the day

```bash
python -m candid mock coding --difficulty medium
python -m candid mock behavioral --theme leadership
python -m candid mock design --level senior
```

Attempt before you peek at `mock solution`; use `mock hint` when stuck.
See `mock`.

## 7. Followup — after the interview

```bash
python -m candid followup thank-you --person "Jane Doe" --role "Data Scientist" --company Acme --topics "team culture" --standout "my churn model"
python -m candid track update 3 --status interviewing
```

Send within 24 hours, one per interviewer, with one genuine detail from
your conversation. Silence after a week? Send the check-in draft. See
`followup`.

## What comes after

- An offer arrives: `offer add` -> `offer compare` -> `negotiate playbook`
  (see `offers`, `negotiate`, `salary`).
- Want it visual: `python -m candid dashboard` (see `dashboard`).
- Inbox full of recruiter mail: `gmail import` -> `gmail confirm`
  (see `imports`).

Repeat the loop weekly: `jobs refresh`, match the new ones, tailor for the
best, and keep the tracker honest.

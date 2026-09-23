# Profiles (multi-profile support)

One candid install can keep several job searches separate — e.g. an
ML-engineer search and a data-scientist search — each with its own
tracker, onboarding profile, prep packs, and tailored outputs.

## The concept: `default` is your existing data

If you've been using candid already, you already have a profile: it's
called `default`, and it's exactly the data you have today
(`tracker.json`, `profile.json`, prep packs, tailored outputs).
Creating new profiles doesn't move, copy, or touch any of it — **zero
migration**. New profiles live under `candid_data/profiles/<name>/`.

Profile names use 1-64 characters: letters, digits, `_` or `-`, starting
with a letter or digit (`mle`, `data-scientist`, `fall-2026`).

## Managing profiles: the `context` command group

```bash
python -m candid context list                      # all profiles, marks the current one
python -m candid context create mle --target-role "ML Engineer"
python -m candid context create ds --from mle      # clone an existing profile's data
python -m candid context use mle                   # make 'mle' the current profile
python -m candid context current                   # print the current profile name
python -m candid context show mle                  # details: name, target role, created
python -m candid context rename mle ml-eng
python -m candid context delete old-search         # refuses if it has tracker entries
python -m candid context delete old-search --force # delete anyway
```

Deleting the `default` profile is refused — it's your original data.

To onboard straight into a new profile, `onboard` takes `--context`
(creating the profile if it doesn't exist yet):

```bash
python -m candid onboard --resume resume.pdf --context mle
```

## Picking a profile: resolution order

Every command runs against exactly one profile, picked in this order:

1. `--profile NAME` — the global flag, placed **before** the subcommand:
   `python -m candid --profile mle track list`
2. The `CANDID_PROFILE` environment variable (handy for scripts)
3. The current profile (`python -m candid context use mle` sets it)
4. `default`

An unknown or misspelled name fails fast with a clean error naming the
profile — it never silently falls back to another profile's data.

## What's per-profile

Each profile is a full, isolated workspace:

- **Tracker** — applications, funnel stats, response/interview/offer
  rates. IDs restart per profile (`#1` in `mle` is unrelated to `#1` in
  `swe`).
- **Onboarding profile** — the structured resume/LinkedIn profile that
  `match` and `tailor` score against, so one profile can be
  seniority-targeted differently from another.
- **Prep packs** — `prep` output for that profile's applications.
- **Tailored outputs** — resumes and cover letters generated under that
  profile.
- **Gmail proposals** — the import review queue is per profile too.

## Export, import, clone

A profile is portable as a single zip (tracker, onboarding profile,
prep packs, tailored outputs — everything):

```bash
python -m candid context export mle --file mle.zip
python -m candid context import --file mle.zip              # keeps the original name
python -m candid context import --file mle.zip --name mle2  # import under a new name
```

Inside one machine, `context create new --from existing` is the faster
equivalent: it clones the source profile's data directory.

## Cross-profile duplicate warnings

Adding the same company+role under two profiles is allowed (maybe
you're chasing it from two angles), but `track add` warns on stderr when
that company+role is already tracked under another profile:

```bash
$ python -m candid --profile mle track add --company Acme --role "ML Engineer"
warning: 'Acme / ML Engineer' is already tracked under profile 'swe'; adding here too.
```

The warning never blocks the add. Within one profile, re-adding an
existing company+role still returns the existing record instead of
duplicating, as before.

## Dashboard: the profile switcher

`python -m candid dashboard` serves the same local-only UI (127.0.0.1,
nothing leaves the machine). A **Profile** dropdown in the header lists
every profile (with target roles) and an **All profiles (combined)**
option. Switching reloads the page as `?profile=<name>`; every section
— funnel, applications, curated jobs, prep, proposals — follows the
selected profile.

The **All profiles** view aggregates across profiles: funnel counts are
summed, with a per-profile breakdown table (each profile's totals,
funnel, and rates labeled by name) and a Profile column in the
applications table. Status changes and proposal confirm/reject are
disabled in the aggregate view — pick one profile to make changes.

The JSON API honors `?profile=` on every endpoint
(`/api/overview?profile=mle`); an unknown name returns a clean
`400 {"error": ...}`, never a traceback.

## Aggregates on the CLI: `--all-profiles`

`track list` and `track stats` take `--all-profiles` to span every
profile in one shot:

```bash
python -m candid track list --all-profiles   # every application, grouped by profile
python -m candid track stats --all-profiles  # funnel stats per profile
```

Combine with `--profile` scoping as usual; `--all-profiles` wins for the
listing itself while a single-profile default still applies to writes.

# Supervised apply (`candid apply`)

`candid apply` fills out job applications for you, but it never sends one
without you saying so. The pipeline fills only safe contact fields, uploads
your resume, takes a full-page screenshot, and then **parks at review**. You
inspect the result, answer any questions it could not fill, approve, and only
then does it submit.

## The golden rule: explicit approval is the default

Every run ends parked until you approve:

```bash
# fill + park at review (default)
python -m candid apply --job jobs/acme.yaml

# answer the questions it could not fill
python -m candid apply status --job-id acme-ml-001
python -m candid apply answer --job-id acme-ml-001 --answers '{"salary": "150k"}'

# approve, then submit
python -m candid apply approve --job-id acme-ml-001 --by "Your Name"
python -m candid apply submit --job-id acme-ml-001 --job jobs/acme.yaml
```

`--auto-submit` exists for hands-free runs, but it is **opt-in only** and it
still never overrides the safety rules:

- With `--auto-submit`, the pipeline submits only when **zero needs_input
  items are unresolved**. If a single question is still open (sensitive or
  unknown field with no value), the run **parks instead of submitting**,
  exactly like the default path.
- `--park` forces parking even if `--auto-submit` was passed.

## What gets filled: safe / sensitive / unknown

Every form field's label is classified before anything is typed
(`candid/apply_fields.py`):

- **safe**: a contact field (name, email, phone, address, LinkedIn, GitHub,
  ...) **and** your profile has a value for it. Only these are auto-filled.
- **sensitive**: visa / work authorization, citizenship, salary or
  compensation expectations, EEO / demographic questions, criminal
  background, and attestations ("I certify..."). These are **never
  auto-answered**. They become `needs_input` items for you to answer
  explicitly, and an explicit answer always wins (you supplied it yourself).
- **unknown**: the classifier does not recognize the label. Also never
  guessed: it becomes a `needs_input` item.

Radio groups and checkboxes are never auto-filled either; the one exception
is a checkbox you answered yourself via `apply answer`.

## What stops the run

- **Login walls and CAPTCHAs stop the run as `blocked` and are never
  solved.** The run writes a `blocked.png` screenshot, transitions to the
  `blocked` state, and waits for you. Solve the login yourself if you want,
  then re-run.
- **No passwords are ever stored.** `profile.yaml` holds only the 13 safe
  contact fields and is git-ignored. There is no field, flag, or env var
  anywhere in this pipeline for credentials.
- The apply profile loader rejects anything that is not one of the 13 safe
  contact keys, including keys that classify as sensitive. Visa and salary
  answers can never sneak into the contact store.

## State machine

```
new -> filling -> needs_input -> ready_for_review -> approved
                                       -> submitting -> submitted
```

- `filling`: the browser is open and the form is being filled.
- `needs_input`: questions are open; parked until you run `apply answer`.
- `ready_for_review`: everything fillable is filled; waiting for your
  approval (the default parking state).
- `approved`: you approved with `--by NAME`; `apply submit` may now run.
- `submitting` / `submitted`: the click happened and a confirmation marker
  ("thank you for applying", "application received", ...) was found on the
  page. If the click happens but no confirmation marker appears, the state
  goes to `failed` with the screenshot path in the note so you can check it
  yourself.
- `blocked` and `failed` are **terminal**: no retry happens automatically.

## Audit trail

Every run writes to `candid_data/runs/<job-id>/<utc-timestamp>/`:

- `run.log`: every step the pipeline took (fields filled, questions opened,
  screenshots taken, errors).
- `review.png`: full-page screenshot before parking, so you can see exactly
  what would be submitted.
- `submitted.png`: full-page screenshot after clicking submit.
- `blocked.png`: screenshot when a login wall or CAPTCHA stopped the run.

The state store itself lives at `candid_data/apply/state/<job-id>.json`
(overridable with `CANDID_DATA_DIR`).

## Job specs and resumes

```bash
cp jobs/example.yaml jobs/acme.yaml   # then fill in id, company, role, url
```

A job spec needs `id`, `company`, `role`, `url`; optional: `resume_pdf`
and `ats` (adapter hint: `generic` today).

The resume is resolved in this order:

1. `resume_pdf` set in the job spec (and the file exists),
2. otherwise `candid_data/tailored/<company>-<role>.pdf`, e.g. exported
   from `candid tailor resume --out` and converted to PDF,
3. otherwise the run fails with guidance (no guessing, no stale resume).

Note: the batch-2 resume-variants integration will pick up automatically
once that branch merges, since it writes its variants into the same
`candid_data/tailored/` directory.

## Playwright is optional

`candid apply` is the one feature that needs a real browser, and it is
strictly opt-in:

```bash
pip install playwright
playwright install chromium   # one-time browser download
```

Everything else in candid (match, tailor, track, prep, salary, jobs curate,
mock, alumni, dashboard) works without it, and without any browser at all.
Without Playwright installed, `candid apply` fails fast with a clear
message instead of a traceback.

## Free and local

No paid APIs, no keys, no accounts, no network calls except loading the
application page itself. The classifier is a local regex table, the state
store is local JSON, and the browser runs on your machine.

## Command reference

```bash
python -m candid apply --job jobs/x.yaml [--park] [--auto-submit] [--headless | --no-headless]
python -m candid apply status --job-id ID [--json]
python -m candid apply answer --job-id ID --answers '{"field": "value"}'
python -m candid apply approve --job-id ID --by NAME
python -m candid apply submit --job-id ID --job jobs/x.yaml
```

Keep filled-in job specs private: they point at your resume and the jobs
you are applying to, so never commit them to a public repo.

# Target-role profiles

Profiles are named sets of job-search defaults: the role you're targeting,
seniority, domains, locations, a salary floor, and free-text notes. They
live as plain JSON in `~/.config/candid/profiles/<name>.json` (override the
config dir with `CANDID_CONFIG_DIR`).

Set one profile active and other candid commands can read its defaults via
`candid.profiles.get_active_profile()`.

## Commands

```bash
# create
python -m candid profiles create ml-nyc \
  --role "Machine Learning Engineer" \
  --seniority senior \
  --domains "ads ranking,recommendations" \
  --locations "New York NY,Remote" \
  --min-salary 180000 \
  --notes "Prefer product-facing teams."

# list (active profile marked with *)
python -m candid profiles list

# activate
python -m candid profiles use ml-nyc

# show (defaults to the active profile)
python -m candid profiles show
python -m candid profiles show ml-nyc

# update only what you pass
python -m candid profiles update ml-nyc --min-salary 200000

# delete (clears the active pointer if it pointed here)
python -m candid profiles delete ml-nyc
```

Comma-separated flags split on commas, so a value that itself contains a
comma (like "New York, NY") can't be passed this way. For those, create the
profile with a placeholder and edit
`~/.config/candid/profiles/<name>.json` directly; validation still applies
on read.

## Schema

```json
{
  "name": "ml-nyc",
  "target_role": "Machine Learning Engineer",
  "seniority": "senior",
  "domains": ["ads ranking", "recommendations"],
  "locations": ["New York, NY", "Remote"],
  "min_salary": 180000,
  "notes": "Prefer product-facing teams."
}
```

Rules, validated strictly with an error naming the exact fix:

- `name`: letters, numbers, hyphens, underscores only (it's a filename).
- `target_role`: required, non-empty string.
- `seniority`: optional; one of `entry, junior, mid, senior, lead, staff,
  principal, director, director+, vp, vp+`.
- `domains`, `locations`: optional; non-empty lists of strings.
- `min_salary`: optional; a number >= 0 (or null).
- `notes`: optional string.
- No unknown fields.

## Python API (for other modules)

```python
from candid import profiles

profiles.get_active_profile()       # dict; raises ProfilesError with a fix hint
profiles.get_active_profile_name()  # str | None
profiles.list_profiles()             # [str]
profiles.create_profile("ml-nyc", role="...", seniority="senior", ...)
profiles.update_profile("ml-nyc", min_salary=200000.0)
profiles.show_profile("ml-nyc")      # or show_profile() for the active one
profiles.use_profile("ml-nyc")
profiles.delete_profile("ml-nyc")
```

`get_active_profile()` raises `ProfilesError` (never returns a partial dict)
when no profile is active, the pointer is stale, or the JSON is invalid.
The message always tells the user the exact command to run.

Verify with:

```bash
CANDID_CONFIG_DIR=/tmp/cfg python3 -m candid profiles create t --role "Data Scientist"
CANDID_CONFIG_DIR=/tmp/cfg python3 -m candid profiles use t
CANDID_CONFIG_DIR=/tmp/cfg python3 -m candid profiles show
```

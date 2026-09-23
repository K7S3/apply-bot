# Plugins

candid discovers plugins as plain `*.py` files — no install step, no packaging.
Drop a file into your plugins directory and it shows up in `candid plugins list`.

**Plugin directories** (first one wins for duplicates is *not* true — the first
discovered plugin name wins; all files are scanned):

1. `~/.config/candid/plugins/` (override with `CANDID_CONFIG_DIR`)
2. Every colon-separated directory in the `CANDID_PLUGINS` env var

A plugin declares itself with a module-level `CANDID_PLUGIN` dict and exposes
one or both hook kinds:

| Hook kind    | Signature | Returns |
|--------------|-----------|---------|
| `job_source` | `(name) -> iterable[dict]` | posting dicts in the canonical format below |
| `scorer`     | `(name) -> callable(profile, jd) -> float` | a scorer returning 0-100 |

A broken plugin (syntax error, import error, missing `CANDID_PLUGIN`, wrong
hook kind) is recorded and skipped — it can never break the CLI or other
plugins. Check `candid plugins list` for load errors.

> Plugins run as trusted local code with your privileges. Only install
> plugins you wrote or trust.

## Minimal example (~30 lines)

```python
"""My custom job source + scorer."""

def fetch_remote_jobs(name):
    # name == the plugin's registered name ("my_plugin" below)
    return [{
        "source": name,
        "source_id": f"{name}:1",
        "title": "Data Scientist",
        "company": "ExampleCo",
        "location": "Remote",
        "url": "https://example.com/jobs/1",
        "description": "Python and SQL for ML models.",
        "salary_text": "$120k-$150k",
        "remote": True,
        "posted_at": "2026-09-20",
    }]

def make_scorer(name):
    def score(profile, jd):
        skills = {s.lower() for s in profile.get("skills", [])}
        text = (jd.get("title", "") + " " + jd.get("description", "")).lower()
        hits = sum(1 for s in skills if s in text)
        return min(100.0, 50.0 + 10.0 * hits)
    return score

CANDID_PLUGIN = {
    "name": "my_plugin",
    "version": "0.1.0",
    "hooks": {"job_source": fetch_remote_jobs, "scorer": make_scorer},
}
```

Validate it without touching the network:

```bash
python -m candid plugins list
python -m candid plugins test my_plugin
```

`test` dry-runs each hook with tiny synthetic input and reports `OK`/`FAIL`
per hook: for `job_source` it checks the first few postings against the
canonical format; for `scorer` it calls the returned callable with a synthetic
profile/JD and requires a number in 0-100.

## Canonical posting format

`job_source` hooks must return dicts with these keys (the same shape as the
built-in adapters in `candid/jobs.py`):

| Key | Type | Required | Notes |
|-----|------|----------|-------|
| `source` | str | yes | adapter name, e.g. `"my_plugin"` |
| `source_id` | str | yes | unique per posting, e.g. `"my_plugin:123"` |
| `title` | str | yes | job title |
| `company` | str | yes | employer name |
| `location` | str | no | `"Remote"` or `"New York, NY"` |
| `url` | str | no | apply link (empty string if none) |
| `description` | str | no | plain-text JD (keep under ~4000 chars) |
| `salary_text` | str | no | raw posted pay, e.g. `"$120k-$150k"` |
| `remote` | bool | no | `True` if remote |
| `posted_at` | str | no | ISO date, epoch, or empty |

Extra keys are allowed. `candid.plugins.validate_posting()` returns a list of
format problems (empty means valid) — useful inside your own tests.

## Scorer contract

`scorer(name)` is a factory: it is called once with the plugin name and must
return a callable `(profile: dict, jd: dict) -> float` where the float is a
match score in 0-100 (same scale as `candid match`). The `profile` dict is the
user's candid profile; `jd` is a posting-shaped dict (`title`, `company`,
`description`, ...).

## Programmatic API

```python
from candid import plugins

plugins.discover_plugins()  # -> list[PluginInfo]: name, version, path, hooks, errors, loaded_ok
plugins.get_job_sources()   # -> {name: callable() -> iterable[posting dict]}
plugins.get_scorers()       # -> {name: callable(profile, jd) -> float 0-100}
plugins.validate_posting(p) # -> list[str] of format problems
```

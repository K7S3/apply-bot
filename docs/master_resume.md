# Master resume

The master resume is the single source of truth for your experience.
Every tailored resume variant is derived from a specific master version,
and that derivation is recorded so any variant can be traced back to the
exact master text it came from.

Storage: `candid_data/master_resume/` (git-ignored) — `versions/vNNNN.md`
keeps full history, `current.json` points at the latest, `lineage.json`
maps variant ids to master versions.

## Quick start

```python
from candid import master_resume as mr

# Build from your onboarded profile (or pass profile=... / resume_path=...)
mr.init_master()

mr.get_master()            # {"markdown", "version_id", "content_hash", ...}
mr.update_master(new_md, note="added Q3 metrics")   # -> v0002, history kept

# When tailoring generates a variant, record where it came from:
mr.record_variant("tailored-acme-v1", kind="resume")
mr.lineage("tailored-acme-v1")
# {"variant_id": ..., "kind": "resume", "master_version": "v0002", ...}

mr.diff_versions("v0001", "v0002")   # unified diff of two master versions
mr.master_bullets()                  # structured bullets for tailor
```

`master_bullets()` returns one dict per bullet:
`{text, role, company, dates, bullet_hash}` — everything tailor needs,
already grounded in the master.

## Groundedness rule

The master is the only place new facts enter the system. Nothing
downstream (tailor, bullet rewrites) may invent experience, metrics,
percentages, tools, or achievements. When information is missing, ask
the user — see `candid/bullet_scorer.py`, whose `suggest_reword()`
turns missing facts into questions instead of claims.

## Suggested CLI (for the integrator)

- `candid master init [--resume FILE]` → `init_master(resume_path=...)`
- `candid master show` → `get_master()` (print markdown)
- `candid master update FILE --note "..."` → `update_master(...)`
- `candid master diff V1 V2` → `diff_versions(v1, v2)`
- `candid master lineage VARIANT_ID` → `lineage(variant_id)`

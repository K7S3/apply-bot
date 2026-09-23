# Pre-submit quality gate

Run `python -m candid gate --app-id 3` (or `--company X --role Y`) before
you hit "submit" on any application. The gate runs 17 checks and gives
one verdict:

| Verdict | Meaning | Exit code |
|---|---|---|
| `PASS` | ready to submit | 0 |
| `WARN` | submittable, but review the warnings | 1 |
| `BLOCK` | do not submit until the blocks are fixed | 2 |

`--strict` promotes warnings to blocks. `--json` prints the machine-readable
result (exit codes still apply). Every run is stamped onto the tracked
application (`gate.ran_at`, `gate_version`, verdict, block/warning ids), so
you can see later whether you submitted with a clean gate and which
check-set version ran.

## The 17 checks

| # | Check | Severity | What it looks for |
|---|---|---|---|
| 1 | Not already submitted | block | status is `applied` / `selected_for_interview` / `offer` - submitting again risks a duplicate |
| 2 | Tailored resume recorded | block | a `tailor resume --app-id N` run recorded a variant on the application |
| 3 | Variant explicitly chosen | block | the recorded variant was marked chosen (`--choose` or `track update N --variant-chosen`) |
| 4 | JD unchanged since tailoring | warn | the JD you pass via `--jd` differs (by hash) from the one the resume was tailored against - re-tailor |
| 5 | ATS: contact email | block | no parseable email in the tailored resume text |
| 6 | ATS: phone number | warn | no parseable phone number |
| 7 | ATS: name on first line | warn | first line doesn't look like a name |
| 8 | ATS: standard sections | warn | missing SUMMARY / EXPERIENCE / EDUCATION / SKILLS headers |
| 9 | ATS: no pipe tables | block | pipe-table rows scramble most ATS parsers |
| 10 | ATS: reasonable length | warn | over ~8000 characters (likely 2+ pages) |
| 11 | Deadline sane | block/warn | block if past or unparseable; warn if within `GATE_DEADLINE_WARN_DAYS` (default 3) or not recorded |
| 12 | Contact: email on file | block | profile has no email |
| 13 | Contact: phone on file | warn | profile has no phone |
| 14 | Contact: location on file | warn | profile has no location |
| 15 | Match score above floor | warn | live `--jd` score, or the stored `--match-score`, below `GATE_MATCH_FLOOR` (default 55) |
| 16 | JD keyword coverage | warn | tailored resume covers under `GATE_KEYWORD_COVERAGE_WARN` (default 50%) of the JD's skill keywords (same measure as the tailor ATS check) |
| 17 | Cover letter ready | warn | no `tailor cover-letter --app-id N` recorded |
| 17 | JD keyword coverage | warn | tailored resume covers under `GATE_KEYWORD_COVERAGE_WARN` (default 50%) of the JD's skill keywords - reuses the tailor ATS keyword logic; skipped when no `--jd` is passed |

Each failing check prints a `fix:` line with the exact command to run.

## Typical flow

```bash
# 1. track it, with a deadline
python -m candid track add --company "Acme Corp" --role "Data Scientist" \
    --deadline 2026-10-15

# 2. tailor and choose the variant in one go
python -m candid tailor resume --jd jd.txt --app-id 1 --choose

# 3. draft the cover letter
python -m candid tailor cover-letter --jd jd.txt --app-id 1

# 4. run the gate
python -m candid gate --app-id 1 --jd jd.txt
```

## Gating status changes

`track update --status applied --gate` runs the gate *before* changing
the status. If the verdict is BLOCK, the status stays as-is (exit 2)
unless you pass `--force`:

```bash
python -m candid track update 1 --status applied --gate          # blocked -> stays 'saved'
python -m candid track update 1 --status applied --gate --force # override (not recommended)
```

`track add --gate` behaves the same way when you create the record with
`--status applied`.

## Supporting commands

- `python -m candid track update 1 --deadline 2026-10-15` - set/clear the deadline (validated as YYYY-MM-DD)
- `python -m candid track update 1 --variant-chosen` - mark the recorded variant chosen
- `python -m candid track update 1 --match-score 72` - store a score for the floor check
- `python -m candid profile set --email you@example.com --phone "+1 555-010-1234"` - fix contact gaps (name/headline/location also settable; skills and experience stay owned by `onboard` so tailoring stays grounded)

## Tuning

In `candid/config.py`: `GATE_MATCH_FLOOR` (default 55),
`GATE_DEADLINE_WARN_DAYS` (default 3), and `GATE_KEYWORD_COVERAGE_WARN`
(default 0.5, i.e. warn when the resume covers under half the JD's skill
keywords). Programmatic use:

```python
from candid import gate as G, tracker as T, profile as P
rec = next(a for a in T.list_apps() if a["id"] == 1)
result = G.run_gate(rec, P.load_profile(), jd_text=open("jd.txt").read())
print(G.render_report(result, company=rec["company"], role=rec["role"]))
```

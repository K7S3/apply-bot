# Hidden gems

A **hidden gem** is a posting where a strong candidate probably faces a
smaller applicant pool than the fit alone would suggest: high profile fit
**plus** low-competition signals. The detector lives in `candid/gems.py`;
this page explains what it measures, the commands, and what it cannot know.

## The score

`gem_score(job, profile, all_jobs)` returns a dict with:

| Field | Meaning |
|---|---|
| `gem_score` | 0-100 blend: `0.65 * fit + 0.35 * competition` with a profile; the pure competition score without one |
| `fit_score` | Profile match 0-100 from `jobs.score_job` (or `None` with no profile) |
| `signals` | The six competition signals below, each 0-100 (higher = less competition) |
| `reasons` | Short human-readable notes for the strongest signals |
| `sleeper` | `True` when the posting is old (> 45 days) but still listed, with a low repost count: high fit hiding behind an unremarkable surface |
| `megacorp` | `True` when the employer looks like a high-competition funnel (see below) |

`top_gems()` keeps postings at or above `GEM_THRESHOLD` (60.0), optionally
drops megacorps (`exclude_megacorps=True`) and low-fit postings
(`min_fit`), and returns the top `limit` sorted by gem score. It never
mutates the input dicts; each returned job carries its result under `_gem`.

## Competition signals (and their honest basis)

No signal is a measured applicant count. Each is a documented proxy:

| Signal | Weight | What it measures | Honest basis |
|---|---|---|---|
| freshness | 25% | `posted_at` age, decaying linearly to 0 over 21 days | Older postings are closer to filled, or buried under newer ones |
| repost rarity | 20% | (company, title) duplicates inside the batch | The same role pushed across boards is usually being pushed hard |
| company volume | 20% | Employer's posting count in the batch | Posting volume proxies applicant volume |
| source niche | 15% | Board audience size: niche (`hn_hiring`, `greenhouse`, `lever`, …) outrank mass boards (`arbeitnow`, `remoteok`) | Board audience size proxies applicant volume |
| salary opacity | 10% | Postings *without* disclosed salary score higher | A disclosed salary draws salary-shoppers |
| remote pool | 10% | Remote postings score lower than on-site/hybrid | Remote pulls a national pool; on-site pulls a local one |

**Megacorp detection** (`is_megacorp(company, jobs)`): true when the
normalized company name contains a known giant's brand token (Google, Meta,
Amazon, …) or the company ranks in the top 10 employers by posting volume
within the batch. Megacorps are never scored as *better* fits; they are
only excluded or down-ranked as competition.

## CLI

```bash
# rank your curated pool as hidden gems
python -m candid jobs gems
python -m candid jobs gems --role "ML Engineer" --remote --limit 10
python -m candid jobs gems --no-megacorps --min-fit 50 --json

# explain one posting's signals (1-based index from `jobs list`, or source-id)
python -m candid jobs why-gem 1
python -m candid jobs why-gem arbeitnow-12345 --json

# rank under-the-radar employers in the curated pool
python -m candid gems employers
python -m candid gems employers --limit 10 --json
```

Python API for the exclude-megacorps filter at curation time:

```python
from candid import jobs
jobs.curate(profile, role="Data Scientist", exclude_megacorps=True)
jobs.refresh(profile, role="Data Scientist", exclude_megacorps=True)
jobs.filter_jobs(raw, role="Data Scientist", exclude_megacorps=True)
```

(There is no `--exclude-megacorps` CLI flag on `jobs curate`/`refresh` yet;
use `jobs gems --no-megacorps` at ranking time, or the Python API.)

## Dashboard panel

The dashboard has a **Hidden gems** section listing the top 5 gems from
stored curation state: gem score, the top reason, a sleeper-pick tag when
applicable, fit score, and an Apply link. The scores are stashed into
`job_meta.json` under the `gem` key during curation, so the panel reads
stored data and never re-scores. Postings curated before gems existed
simply don't appear until the next curation pass.

## Limitations (read before trusting a score)

- **No real applicant counts.** Everything is a proxy: posting age,
  repost counts, employer volume, board size, salary disclosure, remote
  status. A "low competition" posting can still be flooded.
- **Batch-relative.** Volume and repost signals only see the fetched
  batch, not the whole web. `is_megacorp` volume ranking shifts with the
  batch.
- **Megacorp exclusion is about competition, not quality.** A megacorp
  posting can be a great fit; the flag only says the pool is probably
  crowded.
- **Stale scores.** The dashboard panel reads gem payloads stored at
  curation time; signals like freshness age. Re-run `jobs refresh` to
  recompute.
- **Coverage.** Gem detection only sees what `jobs curate` fetches: two
  public no-login feeds (Arbeitnow, RemoteOK). See the README's coverage
  notes.

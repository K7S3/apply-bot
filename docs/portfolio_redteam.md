# Portfolio + Red-team (batch 7: resume and profile mastery)

Two offline modules for the resume layer of candid. Both are stdlib-only
and deterministic - no network, no paid APIs, no hardcoded candidate data.

## candid.portfolio - project descriptions from GitHub repo metadata

Input is **offline repo metadata the user supplies** - a `repos.json`
export, a copy-paste, whatever. This module makes no API calls. (A future
online fetcher, e.g. from batch-3's GitHub work, can plug in here by
producing the same dict shape.)

```python
from candid import portfolio as P

repos = P.load_repos("repos.json")          # JSON list of repo dicts
ranked = P.rank_repos(repos, profile["skills"])   # most relevant first
print(P.portfolio_section(ranked, top_n=4)) # markdown "## Projects" section
```

Repo dict shape: `{name, description, language, topics[], stars, forks,
readme_excerpt, url}`. Only `name` is required.

- `describe_repo(repo)` / `describe_single(name, **fields)` - polished
  1-2 line headline plus 2-4 resume-ready bullets derived **only** from the
  metadata. If `readme_excerpt` is missing it says so (`missing_readme`,
  plus a `caveat` string) and writes a thinner description instead of
  inventing one.
- `rank_repos(repos, profile_skills)` - scores each repo by how many of the
  profile's skills (matched through the shared skill lexicon) appear in its
  metadata; ties break on stars, then forks. Returns copies with a
  `match_score` key; input is never mutated.
- `portfolio_section(repos, top_n=4)` - markdown `## Projects` section ready
  to paste into a resume. Repos missing a README excerpt get an HTML
  comment reminding the user to add one (invisible in the rendered resume).

## candid.redteam - adversarial resume review

```python
from candid import redteam as R

findings = R.review(resume_markdown)   # or R.review(profile_dict)
print(R.hiring_manager_summary(findings))
for fix in R.prioritized_fixes(findings):
    print(fix["severity"], fix["category"], "-", fix["fix"])
```

`review()` accepts resume markdown **or** a profile dict (the shape
`candid.profile.build_profile` returns). Each finding is
`{severity: high|medium|low, category, quote, critique, fix}`.

Categories:

| category | what it catches | severity |
|---|---|---|
| `vague-bullet` | weak verbs ("responsible for", "worked on") with no outcome | medium |
| `overclaim-risk` | big numbers with no baseline/scope/timeframe | medium |
| `inconsistency` | end-date before start-date; same-company title conflicts; summary seniority not backed by any title | high / medium |
| `ats-risk` | tables/graphics/multi-column mentions; non-standard section headers | medium / low |
| `buzzword-density` | filler like "synergy", "ninja", "passionate", "self-starter" | low / medium |
| `gap-explanation` | > 6-month employment gaps, noted neutrally with a suggestion | low |

**Strict rules, enforced by the tests:** every finding's `quote` is copied
verbatim from the input; numbers without context are flagged as *verify*
questions ("What was the baseline for this 50% claim?"), never accusations;
nothing is invented about the candidate.

- `hiring_manager_summary(findings)` - blunt 5-line verdict: does this
  survive a 30-second scan, why, what a skeptic notices first, the biggest
  risk, and what to fix first.
- `prioritized_fixes(findings)` - top 5 fixes ordered by impact (severity,
  then category priority).

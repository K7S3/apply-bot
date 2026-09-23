# Pivot: career-pivot reframing

`candid/pivot.py` reframes your experience for adjacent roles/titles.

**Golden rule:** reframing changes *angle*, never *facts*. Summaries,
bullets, companies, titles, dates, and metrics come verbatim from your
profile - nothing is invented. Gaps are stated plainly; the module never
implies you are qualified for something the profile doesn't support.

## API

```python
from candid import pivot, profile

p = profile.load_profile()

# Rank adjacent titles by transferable-skill overlap
sugs = pivot.suggest_pivots(p, n=5)
# -> [{"target": "platform engineer", "overlap_pct": 75.0,
#      "transferable": ["python", "cloud", ...],
#      "gaps": ["dbt"], "why": "..."}, ...]

# Reframe toward one title
r = pivot.reframe(p, "platform engineer")
# -> {"reframed_summary": "...", "roles": [...],  # bullets verbatim, reordered
#     "skills_to_foreground": [...],
#     "credibility_gaps": ["you'd need to address dbt: ..."],
#     "honest_read": "Near pivot: 3 of 4 core ..."}

# 30/60/90-day plan derived from the gaps
plan = pivot.pivot_plan(p, "platform engineer")
# -> {"steps": [{"phase": "30", "action": "...",
#                "outcome": "Deliverable: ...", "addresses": "dbt"}, ...]}

# Markdown brief: reframe + gaps + plan
md = pivot.pivot_brief(p, "platform engineer")
Path("pivot-brief.md").write_text(md)
```

Every plan step is actionable with a verifiable outcome
(`"Deliverable: ..."`). No vague "learn leadership".

## Extending the adjacency map

`ADJACENCY` is a plain dict: normalized current title ->
list of `{"title", "skills", "why"}` targets. To add a pivot:

1. Add or extend a source key (lowercase, e.g. `"qa engineer"`).
2. List each target's skills using **canonical** names from
   `config.SKILL_LEXICON` - overlap scoring, gap detection, and
   foregrounding all run on these.
3. Write a one-sentence `"why"`.

Matching is fuzzy: if no source key matches exactly, the key with the
best word overlap against your titles/headline wins. Unknown target
titles (not in the map) are handled honestly: the title is mined for
known skills, and anything unrecognized becomes an explicit
"domain experience in X" credibility gap - never invented, never hidden.

## Suggested CLI wiring (for `candid/__main__.py`)

- `candid pivot suggest [--n 5]` -> `suggest_pivots(profile, n)`; print
  ranked targets with overlap %, transferable skills, and gaps.
- `candid pivot reframe --target "platform engineer"` ->
  `reframe(profile, target)`; print the summary, per-role angles, and
  foreground list.
- `candid pivot plan --target "..."` -> `pivot_plan(profile, target)`;
  print the 30/60/90 steps.
- `candid pivot brief --target "..." [--out brief.md]` ->
  `pivot_brief(profile, target)`; write or print the markdown.

Entry-point shape (one function per subcommand, `-> int`):

```python
def cmd_pivot_suggest(args) -> int:
    from candid import pivot, profile
    p = profile.load_profile()
    for s in pivot.suggest_pivots(p, n=args.n):
        print(f"{s['target']} ({s['overlap_pct']}%): "
              f"+{', '.join(s['transferable']) or '-'} "
              f"-{', '.join(s['gaps']) or '-'}")
    return 0
```

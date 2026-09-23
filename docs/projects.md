# Side-project ideator (`project`)

Turn resume gaps into shippable weekend projects. The ideator is
**deterministic**: ideas come from a curated library (`candid/projects.py`),
not an LLM, so suggestions are reproducible and every recommendation can
explain itself.

## The loop

```
1. gaps      rank the JD skills missing from your resume
2. ideas     concrete project ideas that fill exactly those gaps
3. scope     weekend-by-weekend plan with done-criteria
4. stack     tech-stack recommendation, tuned to the JD's keywords
5. estimate  hours + a weekend calendar (discounts stack you already know)
6. learn     free resources for the stack (alongside weekend 1, not before)
7. scaffold  starter repo: README, .gitignore, skeleton code
8. build it on weekends
9. add/done  record it in the ledger -> it now covers those skills
10. story    STAR resume bullets + interview talking points + demo checklist
```

## Examples

```bash
# 1-2. What am I missing, and what should I build?
python -m candid project gaps --jd jd.txt
python -m candid project ideas --jd jd.txt --n 5

# No JD? Broaden toward a role family instead:
python -m candid project ideas --role ml --n 5

# 3-6. Plan one idea
python -m candid project scope rag-support-bot
python -m candid project stack rag-support-bot --jd jd.txt
python -m candid project estimate rag-support-bot --hours-per-weekend 8
python -m candid project learn rag-support-bot

# 7. Scaffold the repo
python -m candid project scaffold rag-support-bot --dir ~/code/rag-bot

# 9-10. After shipping: ledger + portfolio story
python -m candid project add --name "RAG support bot" \
    --skills "llm,python" --status done --url https://github.com/you/rag-bot
python -m candid project story "RAG support bot"

# Browse the whole library
python -m candid project browse
```

The JD can be text, a file, a URL, `-` (stdin), or `--app-id N` to reuse a
tracked application's stored JD — same as `match`.

## How ideas are ranked

`score = (sum of gap weights covered) x appeal / difficulty`, where gap
weights come from the JD (must-have = 2, nice-to-have = 1, context = 0.5)
and appeal/difficulty are curated per idea. Ties break toward fewer
weekends. `rank` is an alias for `ideas`.

Ideas whose skills are already on your resume are never suggested; skills
demonstrated by `done`/`in_progress` ledger projects are excluded too, so
you're never told to build what you've built.

## Gap fixes: reframe vs project vs course

Not every gap needs a project. `gaps` classifies each missing skill:

- **reframe** — it overlaps something already on your resume; name it
  explicitly before building anything.
- **project** — best proven by building; the ideas cover it directly.
- **course** — theory-heavy; pair structured study with one applied project.

## Honest metrics

`story` generates resume bullets with `[bracketed]` placeholders for any
number you haven't measured (scale, latency, accuracy). Fill them with real
numbers — the tool refuses to invent metrics for you, and says so in the
output.

## Extending the library

Add a dict to `_IDEA_TEMPLATES` (or `_SECOND_WAVE`) in
`candid/projects.py`. Required keys: `id`, `title`, `summary`, `why`,
`skills` (canonical names from `config.SKILL_LEXICON`), `roles`,
`difficulty` (1-3), `appeal` (1-5), `stack_skills`, `stack` (dict),
`weekends` (list of `goal`/`tasks`/`done`/`hours`), `demo`, `pitfalls`.
`tests/test_projects.py::LibraryIntegrityTest` validates every entry, so
run the suite after editing.

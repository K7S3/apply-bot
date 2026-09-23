# Coding patterns curriculum

`python -m candid patterns ...` — a Blind-75-style study system built on the
mock-interview problem bank. Everything is offline and deterministic; your
attempts and review schedule live in `candid_data/patterns/` (git-ignored).

## The loop

1. **Learn the patterns**: `patterns list` shows the 20-pattern taxonomy;
   `patterns list --pattern sliding-window` shows recognition cues and the
   canonical template.
2. **Practice and log**: solve bank problems (`mock coding`), then
   `patterns log --problem two-sum --solved --quality 4`. Each log entry
   updates your spaced-repetition card automatically.
3. **Find your gaps**: `patterns mastery` shows per-pattern mastery
   (0-100, from solve rate + self-rated quality), due reviews, and streaks.
4. **Study the gaps**: `patterns plan` builds a Blind-75-style curriculum —
   weakest patterns first, easy-to-medium ramp inside each pattern,
   interleaved across weeks. `patterns drill` turns it into a day-by-day
   schedule that fits your daily time budget and folds in due reviews.
5. **Retain**: `patterns due` / `patterns review --problem X --quality 5`
   run the SM-2 spaced-repetition loop; `patterns cheatsheet <pattern>`
   gives you a one-page refresher.

## The 20 patterns

| id | name | bank problems |
|----|------|---------------|
| `two-pointers` | Two Pointers | 2 |
| `sliding-window` | Sliding Window | 1 |
| `fast-slow-pointers` | Fast & Slow Pointers | 0 |
| `merge-intervals` | Merge Intervals | 1 |
| `cyclic-sort` | Cyclic Sort | 0 |
| `hashmap` | Hash Map / Frequency Counting | 5 |
| `stack` | Stack | 1 |
| `monotonic-stack` | Monotonic Stack | 0 |
| `heap-top-k` | Heap / Top-K | 2 |
| `binary-search` | Binary Search | 0 |
| `tree-dfs` | Tree DFS | 0 |
| `tree-bfs` | Tree BFS | 0 |
| `graph-bfs-dfs` | Graph BFS / DFS | 2 |
| `topological-sort` | Topological Sort | 1 |
| `dp-1d` | 1D Dynamic Programming | 3 |
| `dp-2d` | 2D / Knapsack DP | 1 |
| `dp-subsequence` | Subsequence DP (LCS / LIS) | 0 |
| `backtracking` | Backtracking | 0 |
| `greedy` | Greedy | 1 |
| `prefix-sum` | Prefix Sums | 0 |

Patterns with zero bank problems are reported honestly by `patterns tags`
and by study plans ("no bank problems yet") — add problems via
`docs/adding_problems.md` to fill them in.

## Tagging problems

Every problem JSON carries a `patterns` list (primary pattern first):

```json
"patterns": ["sliding-window", "hashmap"],
```

Tagging guidance:

- Tag the pattern the *intended* solution uses, not every pattern that
  could conceivably apply. Two tags max in practice.
- An attempt counts toward *all* of its problem's patterns in mastery math.
- `patterns tags` validates the whole bank; unknown pattern ids fail loudly.

## Mastery math

For each pattern with attempts:

```
mastery = round(100 * (0.6 * solve_rate + 0.4 * avg_quality / 5))
```

Patterns you never attempted show as `untested` (not 0) — the plan treats
them as gaps to explore, ordered after your known-weak patterns.

## Spaced repetition (SM-2)

`patterns log` and `patterns review` maintain one card per problem:

- quality 0-5 (0 = blank stare, 5 = flawless); quality < 3 resets the card
  to a 1-day interval.
- otherwise: 1 day -> 6 days -> interval x easiness, easiness clamped >= 1.3.
- `patterns due [--as-of DATE]` lists cards due on or before a date.

## Study plans (Blind-75-style)

`patterns plan [--gaps a,b] [--total 75] [--weeks N] [--out plan.md]`:

- gap order defaults to your measured weaknesses (weakest first), or pass
  explicit pattern ids.
- picks round-robin across patterns for interleaving, easy -> medium ramp
  inside each pattern, at most 6 problems per pattern for breadth.
- total caps at 75 like the original Blind 75; weeks chunk to ~10/week.
- `--json` prints the machine-readable plan for scripting.

## Weekly drills

`patterns drill [--minutes-per-day 45] [--days 7] [--seed 0] [--start DATE]`:

- one new problem per day from your weakest pattern that still has untried
  problems (easy 15 / medium 25 / hard 35 min estimates),
- then due spaced-repetition reviews packed into the remaining budget,
- deterministic for a given seed.

## Reset

`patterns reset --yes` deletes your attempts and review cards. There is no
undo — export anything you care about first.

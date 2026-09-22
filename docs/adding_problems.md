# Adding coding problems to the mock-interview bank

Problems live in `candid/data/problems/`, one JSON file per problem.
The filename must match the problem `id`: `<id>.json`.

## Schema

```json
{
  "id": "two-sum",
  "title": "Two Sum",
  "topic": "arrays",
  "difficulty": "easy",
  "statement": "Markdown problem statement shown to the candidate.",
  "function": "solve(nums, target)",
  "compare": "exact",
  "visible_tests": [{"args": [[2,7,11,15], 9], "expected": [0,1]}],
  "hidden_tests":  [{"args": [[3,3], 6], "expected": [0,1]}],
  "hints": ["First hint (gentlest).", "Second hint.", "Third hint (most direct)."],
  "reference_solution": "def solve(nums, target):\n    ...\n",
  "complexity": "Time O(n), space O(n)."
}
```

### Fields

- `id`: lowercase, hyphenated, unique. Used on the CLI: `mock run --problem two-sum`.
- `topic`: free text, but prefer existing topics so `--topic` filters stay useful
  (`arrays`, `strings`, `hashmap`, `two-pointers`, `dp`, `graphs`, `heap`).
- `difficulty`: `easy` | `medium` | `hard`.
- `function`: the exact signature the candidate must implement, e.g. `solve(nums, target)`.
  The judge calls `solve(*args)` from each test case.
- `compare`: how outputs are compared —
  - `"exact"`: `==`
  - `"sorted"`: top-level sorted before comparing (for "any order" list answers)
  - `"sorted_nested"`: for lists of groups (group anagrams)
- `visible_tests` / `hidden_tests`: `args` is the positional argument list,
  `expected` the return value. Visible tests are shown to the candidate;
  hidden tests only report pass/fail counts (inputs withheld).
- `hints`: ordered gentle → direct. Shown one at a time on request.
- `reference_solution`: must define the function from `function` and pass
  **every** test. Shown after the session (or on request).
- `complexity`: one-line Big-O analysis shown with the reference solution.

### Rules

1. **Never invent expected values.** Hand-compute every `expected`, or derive it
   from a second independent implementation you trust.
2. **Verify before committing.** Run the seed/verify script — it judges every
   reference solution against every test and refuses to write files on failure:
   `python3 scripts/seed_problems.py` (for the seed set), or for a new file:
   `python3 -c "
   import json, sys; sys.path.insert(0, '.')
   from candid.mock_judge import judge
   p = json.load(open('candid/data/problems/<id>.json'))
   r = judge(p, p['reference_solution'])
   print(r['summary']); assert r['verdict'] == 'accepted', r
   "`
3. Keep statements self-contained — no external links required to solve.
4. Prefer problems with a single canonical answer; if multiple answers are
   valid, use a `compare` mode that accepts them all.

## Safety note

The judge executes solution code in a sandboxed subprocess (timeouts, memory
and CPU limits, isolated temp dir). Problems themselves are **data** — the
judge never executes anything fetched from the network.

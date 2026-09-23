"""Coding patterns curriculum: taxonomy, problem tagging, gap-driven
Blind-75-style study plans, spaced repetition, drills, mastery, cheat sheets.

The ten batch-35 features live here:

1.  ``PATTERNS``            curated taxonomy of 20 classic coding patterns
2.  problem tagging        every bank problem carries ``patterns: [...]`` tags
3.  skill-gap detection    per-pattern mastery from your attempt log
4.  Blind-75-style plans   study plans generated from your skill gaps
5.  spaced repetition      SM-2 review scheduling per problem
6.  attempt logging        ``log_attempt()`` records solve/fail + quality
7.  weekly drills          day-by-day schedule mixing new + due reviews
8.  mastery dashboard      per-pattern stats, streaks, overall progress
9.  cheat sheets            one-page pattern reference, exportable markdown
10. plan export             plans/drills render to markdown

Everything is offline and deterministic. User state lives under
``DATA_DIR / "patterns"`` (``attempts.jsonl``, ``cards.json``), resolved at
call time so ``CANDID_DATA_DIR`` always wins (same convention as
``candid.study``). The problem bank itself is read-only package data.
"""

from __future__ import annotations

import json
import os
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from candid import config as C


class PatternsError(Exception):
    """Raised for invalid pattern-curriculum input or operations."""


def _today_iso() -> str:
    return date.today().isoformat()


def _coerce_date(value) -> date:
    """Accept a date, datetime, or YYYY-MM-DD string; default today."""
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise PatternsError(
            f"Bad date '{value}'. Use YYYY-MM-DD.") from None


def _patterns_dir() -> Path:
    """Resolve the user patterns dir at call time so CANDID_DATA_DIR wins."""
    override = os.environ.get("CANDID_DATA_DIR")
    base = Path(override).expanduser() if override else C.DATA_DIR
    d = base / "patterns"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _bank_dir() -> Path:
    return Path(__file__).parent / "data" / "problems"


# ---------------------------------------------------------------------------
# 1. Pattern taxonomy
# ---------------------------------------------------------------------------
# Each pattern: id, name, blurb, cues (how to recognize it), template (a
# short Python sketch of the canonical shape), complexity, related ids.
# ---------------------------------------------------------------------------

PATTERNS: list[dict] = [
    {
        "id": "two-pointers",
        "name": "Two Pointers",
        "blurb": "Two indices walk an array from the ends (or the same start) "
                 "and move based on a condition, shrinking the search space.",
        "cues": [
            "Array is sorted (or can be sorted).",
            "Looking for a pair / triplet with a target sum.",
            "Palindrome check or in-place partition.",
            "Phrase like 'in O(1) extra space' on a sorted array.",
        ],
        "template": (
            "l, r = 0, len(a) - 1\n"
            "while l < r:\n"
            "    s = a[l] + a[r]\n"
            "    if s == target:\n"
            "        return (l, r)\n"
            "    elif s < target:\n"
            "        l += 1\n"
            "    else:\n"
            "        r -= 1"
        ),
        "complexity": "Time O(n), space O(1).",
        "related": ["sliding-window", "binary-search", "hashmap"],
    },
    {
        "id": "sliding-window",
        "name": "Sliding Window",
        "blurb": "Keep a window [left, right] that expands and contracts to "
                 "satisfy a constraint; track the best valid window seen.",
        "cues": [
            "Subarray / substring with a constraint ('at most K', 'contains all').",
            "Asks for longest / shortest / count of valid windows.",
            "'Contiguous' in the statement.",
        ],
        "template": (
            "from collections import defaultdict\n"
            "need = defaultdict(int)\n"
            "left = 0\n"
            "best = 0\n"
            "for right, ch in enumerate(s):\n"
            "    need[ch] += 1\n"
            "    while not valid(need):      # shrink until valid again\n"
            "        need[s[left]] -= 1\n"
            "        left += 1\n"
            "    best = max(best, right - left + 1)"
        ),
        "complexity": "Time O(n), space O(k) for the window state.",
        "related": ["two-pointers", "hashmap", "prefix-sum"],
    },
    {
        "id": "fast-slow-pointers",
        "name": "Fast & Slow Pointers",
        "blurb": "Two pointers traverse a linked structure at different "
                 "speeds; their meeting (or gap) reveals cycles and midpoints.",
        "cues": [
            "Linked list (singly) traversal.",
            "Cycle detection, or 'find the middle'.",
            "'kth node from the end'.",
        ],
        "template": (
            "slow = fast = head\n"
            "while fast and fast.next:\n"
            "    slow = slow.next\n"
            "    fast = fast.next.next\n"
            "    if slow is fast:\n"
            "        return True   # cycle found"
        ),
        "complexity": "Time O(n), space O(1).",
        "related": ["two-pointers", "graph-bfs-dfs"],
    },
    {
        "id": "merge-intervals",
        "name": "Merge Intervals",
        "blurb": "Sort by start, then sweep once merging anything that "
                 "overlaps the current interval.",
        "cues": [
            "Input is [start, end] pairs.",
            "'Overlapping', 'merge', 'insert interval', 'meeting rooms'.",
        ],
        "template": (
            "ivs = sorted(intervals)\n"
            "merged = [ivs[0]]\n"
            "for s, e in ivs[1:]:\n"
            "    if s <= merged[-1][1]:\n"
            "        merged[-1][1] = max(merged[-1][1], e)\n"
            "    else:\n"
            "        merged.append([s, e])"
        ),
        "complexity": "Time O(n log n) for the sort, space O(n).",
        "related": ["greedy", "two-pointers"],
    },
    {
        "id": "cyclic-sort",
        "name": "Cyclic Sort",
        "blurb": "When values map to indices (1..n or 0..n), place each value "
                 "at its home index by swapping; whatever is misplaced is the "
                 "answer.",
        "cues": [
            "Numbers in range 1..n (or 0..n).",
            "'Find the missing / duplicate number'.",
            "Asks for O(n) time and O(1) space on such input.",
        ],
        "template": (
            "i = 0\n"
            "while i < len(a):\n"
            "    j = a[i] - 1\n"
            "    if a[i] != a[j]:\n"
            "        a[i], a[j] = a[j], a[i]\n"
            "    else:\n"
            "        i += 1\n"
            "# first index where a[i] != i + 1 is the answer"
        ),
        "complexity": "Time O(n), space O(1).",
        "related": ["hashmap", "two-pointers"],
    },
    {
        "id": "hashmap",
        "name": "Hash Map / Frequency Counting",
        "blurb": "Trade space for time: index by key or count frequencies so "
                 "lookups become O(1).",
        "cues": [
            "'Find two numbers that...', anagrams, duplicates.",
            "Need 'have I seen this before?' in O(1).",
            "Frequency / counting words or characters.",
        ],
        "template": (
            "seen = {}\n"
            "for i, x in enumerate(a):\n"
            "    need = target - x\n"
            "    if need in seen:\n"
            "        return (seen[need], i)\n"
            "    seen[x] = i"
        ),
        "complexity": "Time O(n), space O(n).",
        "related": ["two-pointers", "sliding-window", "prefix-sum"],
    },
    {
        "id": "stack",
        "name": "Stack",
        "blurb": "LIFO order for nested or matching structure: push opens, "
                 "pop on closes, check what remains.",
        "cues": [
            "Parentheses / brackets / tags matching.",
            "'Valid ...' with nesting.",
            "Undo-like or reverse-polish evaluation.",
        ],
        "template": (
            "pairs = {')': '(', ']': '[', '}': '{'}\n"
            "st = []\n"
            "for ch in s:\n"
            "    if ch in pairs.values():\n"
            "        st.append(ch)\n"
            "    elif not st or st.pop() != pairs[ch]:\n"
            "        return False\n"
            "return not st"
        ),
        "complexity": "Time O(n), space O(n).",
        "related": ["monotonic-stack", "backtracking"],
    },
    {
        "id": "monotonic-stack",
        "name": "Monotonic Stack",
        "blurb": "Keep the stack sorted (increasing or decreasing); each "
                 "element is pushed/popped once, giving O(n) 'next greater / "
                 "smaller' answers.",
        "cues": [
            "'Next greater element', 'daily temperatures'.",
            "Largest rectangle in histogram.",
            "Needs nearest larger/smaller on either side.",
        ],
        "template": (
            "st = []          # stores indices, values decreasing\n"
            "ans = [-1] * len(a)\n"
            "for i, x in enumerate(a):\n"
            "    while st and a[st[-1]] < x:\n"
            "        ans[st.pop()] = x\n"
            "    st.append(i)"
        ),
        "complexity": "Time O(n), space O(n).",
        "related": ["stack", "heap-top-k"],
    },
    {
        "id": "heap-top-k",
        "name": "Heap / Top-K",
        "blurb": "A heap keeps the K best elements without a full sort; a "
                 "min-heap of size K tracks the K largest seen so far.",
        "cues": [
            "'Kth largest / smallest', 'top K frequent'.",
            "Streaming data where K is small.",
            "Merge K sorted lists.",
        ],
        "template": (
            "import heapq\n"
            "h = []\n"
            "for x in stream:\n"
            "    heapq.heappush(h, x)\n"
            "    if len(h) > k:\n"
            "        heapq.heappop(h)   # h holds the k largest"
        ),
        "complexity": "Time O(n log k), space O(k).",
        "related": ["binary-search", "monotonic-stack", "hashmap"],
    },
    {
        "id": "binary-search",
        "name": "Binary Search",
        "blurb": "Halve a sorted search space each step; the art is in the "
                 "boundary conditions and the 'first true' formulation.",
        "cues": [
            "Sorted array / 'sorted rotated array'.",
            "'O(log n)' requirement.",
            "Search answer space ('minimum feasible value').",
        ],
        "template": (
            "lo, hi = 0, len(a) - 1\n"
            "while lo <= hi:\n"
            "    mid = (lo + hi) // 2\n"
            "    if a[mid] == target:\n"
            "        return mid\n"
            "    elif a[mid] < target:\n"
            "        lo = mid + 1\n"
            "    else:\n"
            "        hi = mid - 1\n"
            "return -1"
        ),
        "complexity": "Time O(log n), space O(1).",
        "related": ["two-pointers", "heap-top-k"],
    },
    {
        "id": "tree-dfs",
        "name": "Tree DFS",
        "blurb": "Recurse down root-to-leaf paths carrying path state "
                 "(sum, depth, path list); backtrack on return.",
        "cues": [
            "Binary tree + 'path', 'all root-to-leaf', 'path sum'.",
            "Serialize / validate / invert a tree.",
        ],
        "template": (
            "def dfs(node, path_sum):\n"
            "    if not node:\n"
            "        return False\n"
            "    path_sum += node.val\n"
            "    if not node.left and not node.right:\n"
            "        return path_sum == target\n"
            "    return dfs(node.left, path_sum) or dfs(node.right, path_sum)"
        ),
        "complexity": "Time O(n), space O(h) for recursion depth.",
        "related": ["tree-bfs", "backtracking", "graph-bfs-dfs"],
    },
    {
        "id": "tree-bfs",
        "name": "Tree BFS",
        "blurb": "Level-order traversal with a queue; process one full level "
                 "per loop iteration.",
        "cues": [
            "'Level order', 'zigzag', 'right side view'.",
            "Shortest path in an unweighted tree.",
            "Anything 'per level' / 'by depth'.",
        ],
        "template": (
            "from collections import deque\n"
            "q = deque([root])\n"
            "while q:\n"
            "    level = []\n"
            "    for _ in range(len(q)):\n"
            "        node = q.popleft()\n"
            "        level.append(node.val)\n"
            "        q.extend([c for c in (node.left, node.right) if c])\n"
            "    yield level"
        ),
        "complexity": "Time O(n), space O(w) for the widest level.",
        "related": ["tree-dfs", "graph-bfs-dfs", "topological-sort"],
    },
    {
        "id": "graph-bfs-dfs",
        "name": "Graph BFS / DFS",
        "blurb": "Traverse components with a visited set; DFS for "
                 "connectedness, BFS for shortest path on unweighted graphs.",
        "cues": [
            "Grid of 0/1 ('islands', 'flood fill').",
            "'Connected components', 'number of provinces'.",
            "Clone graph / word ladder.",
        ],
        "template": (
            "seen = set()\n"
            "def dfs(r, c):\n"
            "    if not (0 <= r < R and 0 <= c < C):\n"
            "        return\n"
            "    if (r, c) in seen or grid[r][c] == '0':\n"
            "        return\n"
            "    seen.add((r, c))\n"
            "    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):\n"
            "        dfs(r + dr, c + dc)"
        ),
        "complexity": "Time O(V + E), space O(V).",
        "related": ["tree-dfs", "tree-bfs", "topological-sort"],
    },
    {
        "id": "topological-sort",
        "name": "Topological Sort",
        "blurb": "Order nodes so dependencies come first: Kahn's algorithm "
                 "(indegree queue) or DFS post-order. A leftover cycle means "
                 "no valid order exists.",
        "cues": [
            "'Prerequisites', 'course schedule'.",
            "Build / task ordering with dependencies.",
            "'Can it be finished?' with directed edges.",
        ],
        "template": (
            "from collections import deque, defaultdict\n"
            "indeg = defaultdict(int)\n"
            "adj = defaultdict(list)\n"
            "for u, v in edges:      # u before v\n"
            "    adj[u].append(v)\n"
            "    indeg[v] += 1\n"
            "q = deque([n for n in nodes if indeg[n] == 0])\n"
            "order = []\n"
            "while q:\n"
            "    u = q.popleft()\n"
            "    order.append(u)\n"
            "    for v in adj[u]:\n"
            "        indeg[v] -= 1\n"
            "        if indeg[v] == 0:\n"
            "            q.append(v)\n"
            "ok = len(order) == len(nodes)   # False -> cycle"
        ),
        "complexity": "Time O(V + E), space O(V + E).",
        "related": ["graph-bfs-dfs", "tree-bfs"],
    },
    {
        "id": "dp-1d",
        "name": "1D Dynamic Programming",
        "blurb": "dp[i] stores the best answer for the prefix ending at i; "
                 "fill it left to right from a recurrence on the last choice.",
        "cues": [
            "'Climbing stairs', 'house robber', 'maximum subarray'.",
            "Optimal answer for prefix i depends on smaller prefixes.",
            "Counting ways with a small set of last moves.",
        ],
        "template": (
            "dp = [0] * (n + 1)\n"
            "dp[0], dp[1] = base0, base1\n"
            "for i in range(2, n + 1):\n"
            "    dp[i] = best(dp[i - 1], dp[i - 2])   # recurrence\n"
            "return dp[n]"
        ),
        "complexity": "Time O(n), space O(n) (often O(1) with rolling vars).",
        "related": ["dp-2d", "dp-subsequence", "greedy", "prefix-sum"],
    },
    {
        "id": "dp-2d",
        "name": "2D / Knapsack DP",
        "blurb": "Two dimensions: items x capacity (knapsack) or string x "
                 "string (edit problems). Fill row by row from the recurrence.",
        "cues": [
            "'Knapsack', 'coin change', 'partition equal subset'.",
            "Two strings: 'edit distance', 'distinct subsequences'.",
            "Grid paths with obstacles.",
        ],
        "template": (
            "# 0/1 knapsack: dp[w] = max value with capacity w\n"
            "dp = [0] * (W + 1)\n"
            "for wt, val in items:\n"
            "    for w in range(W, wt - 1, -1):   # backwards: 0/1\n"
            "        dp[w] = max(dp[w], dp[w - wt] + val)"
        ),
        "complexity": "Time O(n * W), space O(W).",
        "related": ["dp-1d", "dp-subsequence"],
    },
    {
        "id": "dp-subsequence",
        "name": "Subsequence DP (LCS / LIS)",
        "blurb": "Compare sequences and extend: LCS for two strings, LIS for "
                 "increasing order; both reduce to 'extend or skip'.",
        "cues": [
            "'Longest common subsequence', 'longest increasing subsequence'.",
            "'Uncrossed lines', 'delete operations for two strings'.",
        ],
        "template": (
            "# LCS\n"
            "dp = [[0] * (m + 1) for _ in range(n + 1)]\n"
            "for i in range(1, n + 1):\n"
            "    for j in range(1, m + 1):\n"
            "        if a[i - 1] == b[j - 1]:\n"
            "            dp[i][j] = dp[i - 1][j - 1] + 1\n"
            "        else:\n"
            "            dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])"
        ),
        "complexity": "Time O(n * m), space O(n * m) (often O(min(n, m))).",
        "related": ["dp-2d", "dp-1d"],
    },
    {
        "id": "backtracking",
        "name": "Backtracking",
        "blurb": "Build candidates one choice at a time; recurse, then undo "
                 "the choice. Prune branches that cannot lead to a solution.",
        "cues": [
            "'All combinations / permutations / subsets'.",
            "N-queens, sudoku, 'generate parentheses'.",
            "'Find all ...' with constraints.",
        ],
        "template": (
            "res = []\n"
            "def backtrack(path, start):\n"
            "    res.append(list(path))\n"
            "    for i in range(start, len(nums)):\n"
            "        path.append(nums[i])\n"
            "        backtrack(path, i + 1)\n"
            "        path.pop()          # undo\n"
            "backtrack([], 0)"
        ),
        "complexity": "Time O(2^n) typical, space O(n) recursion.",
        "related": ["tree-dfs", "stack"],
    },
    {
        "id": "greedy",
        "name": "Greedy",
        "blurb": "Take the locally optimal choice at each step; correct only "
                 "when a greedy choice can be proven never to hurt.",
        "cues": [
            "'Minimum number of ...' (jumps, arrows, coins with canonical "
            "denominations).",
            "Interval scheduling / activity selection.",
            "'Best time to buy and sell stock'.",
        ],
        "template": (
            "# jump game: track farthest reachable\n"
            "reach = 0\n"
            "for i, x in enumerate(a):\n"
            "    if i > reach:\n"
            "        return False\n"
            "    reach = max(reach, i + x)\n"
            "return True"
        ),
        "complexity": "Often O(n log n) with a sort, space O(1).",
        "related": ["dp-1d", "merge-intervals", "heap-top-k"],
    },
    {
        "id": "prefix-sum",
        "name": "Prefix Sums",
        "blurb": "Precompute cumulative sums so any range sum is O(1); with a "
                 "hash map, count subarrays with a target sum in one pass.",
        "cues": [
            "'Sum of subarray', 'range sum query' (many queries).",
            "'Subarray sum equals K'.",
            "2D variant: 'max sum rectangle'.",
        ],
        "template": (
            "from collections import defaultdict\n"
            "pref = defaultdict(int)\n"
            "pref[0] = 1\n"
            "run = ans = 0\n"
            "for x in a:\n"
            "    run += x\n"
            "    ans += pref[run - k]\n"
            "    pref[run] += 1"
        ),
        "complexity": "Time O(n), space O(n).",
        "related": ["hashmap", "sliding-window", "dp-1d"],
    },
]

PATTERN_IDS: tuple[str, ...] = tuple(p["id"] for p in PATTERNS)


def get_pattern(pattern_id: str) -> dict:
    """Return the taxonomy entry for ``pattern_id`` or raise PatternsError."""
    for p in PATTERNS:
        if p["id"] == pattern_id:
            return p
    raise PatternsError(
        f"Unknown pattern '{pattern_id}'. Known: {', '.join(PATTERN_IDS)}")


def _taxonomy_report() -> dict:
    """Structural validation of the taxonomy itself (used by tests)."""
    errors = []
    seen = set()
    for p in PATTERNS:
        for field in ("id", "name", "blurb", "cues", "template",
                      "complexity", "related"):
            if field not in p:
                errors.append(f"pattern missing field '{field}': {p.get('id')}")
        if p["id"] in seen:
            errors.append(f"duplicate pattern id: {p['id']}")
        seen.add(p["id"])
        for r in p.get("related", []):
            if r not in PATTERN_IDS:
                errors.append(f"pattern '{p['id']}' has unknown related '{r}'")
        if not p.get("cues"):
            errors.append(f"pattern '{p['id']}' has no recognition cues")
        if not p.get("template"):
            errors.append(f"pattern '{p['id']}' has no template")
    return {"patterns": len(PATTERNS), "errors": errors}


# ---------------------------------------------------------------------------
# 2. Problem tagging: load the bank with pattern tags, validate them.
# ---------------------------------------------------------------------------

DIFFICULTY_RANK = {"easy": 0, "medium": 1, "hard": 2}
EST_MINUTES = {"easy": 15, "medium": 25, "hard": 35}


def load_bank() -> list[dict]:
    """Load every bank problem (full dicts), validating pattern tags.

    Raises PatternsError if any problem is missing ``patterns`` or tags an
    unknown pattern. Problems come back sorted by id for determinism.
    """
    d = _bank_dir()
    if not d.exists():
        raise PatternsError("Problem bank not found.")
    problems = []
    errors = []
    for f in sorted(d.glob("*.json")):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            errors.append(f"{f.name}: unreadable ({e})")
            continue
        tags = p.get("patterns")
        if not tags:
            errors.append(f"{p.get('id', f.name)}: missing 'patterns' tags")
        elif not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            errors.append(f"{p['id']}: 'patterns' must be a list of strings")
        else:
            for t in tags:
                if t not in PATTERN_IDS:
                    errors.append(f"{p['id']}: unknown pattern tag '{t}'")
        problems.append(p)
    if errors:
        raise PatternsError("Problem bank tag errors:\n- " + "\n- ".join(errors))
    return problems


def validate_bank() -> dict:
    """Non-raising tag report: counts plus a list of problems per pattern."""
    try:
        problems = load_bank()
    except PatternsError as e:
        return {"problems": 0, "errors": str(e).splitlines(), "coverage": {}}
    coverage: dict[str, list[str]] = {pid: [] for pid in PATTERN_IDS}
    for p in problems:
        for t in p.get("patterns", []):
            coverage[t].append(p["id"])
    unused = sorted(pid for pid, ids in coverage.items() if not ids)
    return {
        "problems": len(problems),
        "patterns_used": sorted(pid for pid, ids in coverage.items() if ids),
        "patterns_unused": unused,
        "errors": [],
        "coverage": {pid: sorted(ids) for pid, ids in coverage.items() if ids},
    }


def problems_for_pattern(pattern_id: str) -> list[dict]:
    """Bank problems tagged with ``pattern_id``, easiest first."""
    get_pattern(pattern_id)  # validates the id
    out = [p for p in load_bank() if pattern_id in p.get("patterns", [])]
    out.sort(key=lambda p: (DIFFICULTY_RANK.get(p.get("difficulty", ""), 99),
                            p["id"]))
    return out


def coverage() -> dict[str, list[str]]:
    """Map pattern id -> sorted list of bank problem ids."""
    return validate_bank()["coverage"]


# ---------------------------------------------------------------------------
# 3-6. Attempt log, skill-gap detection, mastery, spaced repetition.
# ---------------------------------------------------------------------------

def _attempts_path() -> Path:
    return _patterns_dir() / "attempts.jsonl"


def _cards_path() -> Path:
    return _patterns_dir() / "cards.json"


def read_attempts() -> list[dict]:
    """Read the attempt log (oldest first). Empty list when never logged."""
    p = _attempts_path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _quality_or_default(solved: bool, quality) -> int:
    if quality is None:
        return 4 if solved else 2
    if not isinstance(quality, int) or not 0 <= quality <= 5:
        raise PatternsError("quality must be an integer 0-5 "
                            "(0 = blank stare, 5 = flawless).")
    return quality


def log_attempt(problem_id: str, solved: bool, quality: int | None = None,
                minutes: float | None = None, at=None) -> dict:
    """Log one practice attempt and update its spaced-repetition card.

    ``solved`` is True when the attempt passed; ``quality`` is a 0-5
    self-rating (defaults: 4 when solved, 2 when not). Also feeds
    ``review()`` so the next-due date moves automatically.
    """
    bank_ids = {p["id"]: p for p in load_bank()}
    if problem_id not in bank_ids:
        raise PatternsError(
            f"Unknown problem '{problem_id}'. "
            f"See `patterns tags` for bank ids.")
    solved = bool(solved)
    q = _quality_or_default(solved, quality)
    if minutes is not None and (not isinstance(minutes, (int, float))
                                or minutes < 0):
        raise PatternsError("minutes must be a non-negative number.")
    day = _coerce_date(at)
    record = {
        "date": day.isoformat(),
        "ts": datetime.now().isoformat(timespec="seconds"),
        "problem_id": problem_id,
        "patterns": bank_ids[problem_id].get("patterns", []),
        "solved": solved,
        "quality": q,
        "minutes": minutes,
    }
    with open(_attempts_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    review(problem_id, q, today=day)  # keep the SR card in sync
    return record


def pattern_mastery(attempts: list[dict] | None = None) -> dict[str, dict]:
    """Per-pattern mastery from the attempt log.

    An attempt counts toward every pattern its problem is tagged with.
    mastery = round(100 * (0.6 * solve_rate + 0.4 * avg_quality/5));
    None when the pattern was never attempted (untested, not "bad").
    """
    if attempts is None:
        attempts = read_attempts()
    stats: dict[str, dict] = {
        pid: {"attempts": 0, "solved": 0, "quality_sum": 0}
        for pid in PATTERN_IDS
    }
    for a in attempts:
        for pid in a.get("patterns", []):
            if pid not in stats:
                continue
            stats[pid]["attempts"] += 1
            stats[pid]["solved"] += 1 if a.get("solved") else 0
            stats[pid]["quality_sum"] += a.get("quality", 0)
    out = {}
    for pid, s in stats.items():
        n = s["attempts"]
        if n == 0:
            out[pid] = {"attempts": 0, "solved": 0, "solve_rate": None,
                        "avg_quality": None, "mastery": None}
            continue
        solve_rate = s["solved"] / n
        avg_q = s["quality_sum"] / n
        mastery = round(100 * (0.6 * solve_rate + 0.4 * (avg_q / 5)))
        out[pid] = {"attempts": n, "solved": s["solved"],
                    "solve_rate": round(solve_rate, 3),
                    "avg_quality": round(avg_q, 2), "mastery": mastery}
    return out


def weak_patterns(mastery: dict | None = None, threshold: int = 60,
                  attempts: list[dict] | None = None) -> list[dict]:
    """Skill gaps, weakest first.

    Order: known-weak patterns (mastery < threshold, ascending), then
    untested patterns that have bank problems, then untested patterns with
    no bank problems yet (flagged, so plans can note them honestly).
    """
    if mastery is None:
        mastery = pattern_mastery(attempts)
    cov = coverage()
    weak, untested_banked, untested_empty = [], [], []
    for pid in PATTERN_IDS:
        m = mastery[pid]["mastery"]
        entry = {"pattern": pid, "mastery": m,
                 "bank_problems": len(cov.get(pid, []))}
        if m is None:
            (untested_banked if entry["bank_problems"] else untested_empty
             ).append(entry)
        elif m < threshold:
            weak.append(entry)
    weak.sort(key=lambda e: (e["mastery"], e["pattern"]))
    untested_banked.sort(key=lambda e: e["pattern"])
    untested_empty.sort(key=lambda e: e["pattern"])
    return weak + untested_banked + untested_empty


# ---------------------------------------------------------------------------
# Spaced repetition (SM-2)
# ---------------------------------------------------------------------------

def _load_cards() -> dict:
    p = _cards_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cards(cards: dict) -> None:
    _cards_path().write_text(json.dumps(cards, indent=2), encoding="utf-8")


def get_card(problem_id: str, today=None) -> dict:
    """Return the SR card for a problem, creating it when missing."""
    bank_ids = {p["id"] for p in load_bank()}
    if problem_id not in bank_ids:
        raise PatternsError(f"Unknown problem '{problem_id}'.")
    day = _coerce_date(today)
    cards = _load_cards()
    card = cards.get(problem_id)
    if card is None:
        card = {"problem_id": problem_id, "easiness": 2.5, "interval": 0,
                "repetitions": 0, "reviews": 0, "last_quality": None,
                "next_due": day.isoformat()}
        cards[problem_id] = card
        _save_cards(cards)
    return card


def review(problem_id: str, quality: int, today=None) -> dict:
    """Record a review with quality 0-5 and reschedule (SM-2).

    quality < 3 resets the streak (review again tomorrow); otherwise the
    interval grows by the easiness factor (1 -> 6 -> interval * easiness).
    Returns the updated card.
    """
    q = _quality_or_default(True, quality)  # validates 0-5 int
    day = _coerce_date(today)
    card = get_card(problem_id, today=day)
    cards = _load_cards()
    e = card["easiness"]
    if q < 3:
        card["repetitions"] = 0
        card["interval"] = 1
    else:
        card["repetitions"] += 1
        if card["repetitions"] == 1:
            card["interval"] = 1
        elif card["repetitions"] == 2:
            card["interval"] = 6
        else:
            card["interval"] = max(1, round(card["interval"] * e))
        e = e + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
        card["easiness"] = round(max(1.3, e), 2)
    card["reviews"] += 1
    card["last_quality"] = q
    card["next_due"] = (day + timedelta(days=card["interval"])).isoformat()
    cards[problem_id] = card
    _save_cards(cards)
    return card


def due_cards(as_of=None) -> list[dict]:
    """Cards with next_due on or before ``as_of`` (default today), oldest first."""
    day = _coerce_date(as_of)
    cards = _load_cards()
    due = [c for c in cards.values()
           if c.get("reviews", 0) > 0 and c.get("next_due", "") <= day.isoformat()]
    due.sort(key=lambda c: (c["next_due"], c["problem_id"]))
    return due


def reset_progress() -> dict:
    """Delete attempts and SR cards. Returns what was removed (for confirm UI)."""
    removed = {"attempts": 0, "cards": 0}
    ap = _attempts_path()
    if ap.exists():
        removed["attempts"] = len(read_attempts())
        ap.unlink()
    cp = _cards_path()
    if cp.exists():
        removed["cards"] = len(_load_cards())
        cp.unlink()
    return removed


# ---------------------------------------------------------------------------
# 4. Blind-75-style study plans generated from skill gaps.
# ---------------------------------------------------------------------------
# Shape mirrors the original Blind 75 idea: a capped, pattern-balanced list
# ordered by your weakest patterns first, with an easy -> medium ramp inside
# each pattern and problems interleaved across weeks for spacing.
# ---------------------------------------------------------------------------

BLIND75_CAP = 75
PLAN_WEEKLY_TARGET = 10


def _normalize_gaps(gaps, mastery) -> list[str]:
    """Accept None, [pattern-id], or weak_patterns() dicts -> ordered ids."""
    if gaps is None:
        return [g["pattern"] for g in weak_patterns(mastery)]
    ids = []
    for g in gaps:
        pid = g["pattern"] if isinstance(g, dict) else g
        get_pattern(pid)  # validates
        if pid not in ids:
            ids.append(pid)
    return ids


def build_plan(gaps=None, total: int = BLIND75_CAP, per_pattern_cap: int = 6,
               weeks: int | None = None, attempts: list[dict] | None = None,
               mastery: dict | None = None) -> dict:
    """Build a Blind-75-style curriculum from your skill gaps.

    - Problems are picked weakest-pattern-first (``gaps`` order), with an
      easy -> medium ramp inside each pattern and at most
      ``per_pattern_cap`` problems per pattern for breadth.
    - Picks interleave across patterns (round-robin), then chunk into weeks
      of ~``PLAN_WEEKLY_TARGET`` problems for spacing.
    - ``total`` caps the list at 75 like the original Blind 75.
    """
    if total < 1:
        raise PatternsError("total must be >= 1.")
    if per_pattern_cap < 1:
        raise PatternsError("per_pattern_cap must be >= 1.")
    bank = load_bank()
    by_id = {p["id"]: p for p in bank}
    gap_order = _normalize_gaps(gaps, mastery)
    # Round-robin over gap-ordered patterns for interleaving.
    per_pattern: dict[str, list[dict]] = {}
    for pid in gap_order:
        plist = [p for p in bank if pid in p.get("patterns", [])]
        plist.sort(key=lambda p: (DIFFICULTY_RANK.get(p.get("difficulty"), 99),
                                  p["id"]))
        per_pattern[pid] = plist[:per_pattern_cap]
    selected: list[dict] = []
    seen: set[str] = set()
    round_i = 0
    while len(selected) < min(total, len(bank)):
        progressed = False
        for pid in gap_order:
            pool = per_pattern.get(pid, [])
            if round_i < len(pool):
                cand = pool[round_i]
                if cand["id"] not in seen:
                    seen.add(cand["id"])
                    selected.append({"problem_id": cand["id"],
                                     "title": cand["title"],
                                     "difficulty": cand["difficulty"],
                                     "focus_pattern": pid,
                                     "patterns": cand.get("patterns", [])})
                    progressed = True
                    if len(selected) >= min(total, len(bank)):
                        break
            if len(selected) >= min(total, len(bank)):
                break
        if not progressed:
            break
        round_i += 1
    n_weeks = weeks if weeks else max(1, -(-len(selected) // PLAN_WEEKLY_TARGET))
    if weeks is not None and weeks < 1:
        raise PatternsError("weeks must be >= 1.")
    week_lists: list[list[dict]] = [[] for _ in range(n_weeks)]
    for i, item in enumerate(selected):
        week_lists[i % n_weeks].append(item)
    week_struct = [{"week": i + 1, "items": wl} for i, wl in enumerate(week_lists)]
    cov = coverage()
    skipped = [pid for pid in gap_order if not cov.get(pid)]
    return {
        "total": len(selected),
        "cap": BLIND75_CAP,
        "gap_order": gap_order,
        "weeks": week_struct,
        "skipped_no_bank": skipped,
        "generated": _today_iso(),
    }


def render_plan(plan: dict) -> str:
    """Render a plan as markdown with per-week checklists."""
    lines = [
        f"# Coding patterns study plan ({plan['total']} problems)",
        "",
        f"_Generated {plan['generated']}. Weakest patterns first, "
        f"easy-to-medium ramp inside each pattern._",
        "",
        "## Focus order",
        "",
    ]
    for i, pid in enumerate(plan["gap_order"], 1):
        try:
            name = get_pattern(pid)["name"]
        except PatternsError:
            name = pid
        lines.append(f"{i}. {name} (`{pid}`)")
    if plan.get("skipped_no_bank"):
        lines += ["",
                  "_No bank problems yet for: "
                  + ", ".join(f"`{p}`" for p in plan["skipped_no_bank"])
                  + " — add some via docs/adding_problems.md._"]
    for w in plan["weeks"]:
        lines += ["", f"## Week {w['week']}", ""]
        for it in w["items"]:
            try:
                pname = get_pattern(it["focus_pattern"])["name"]
            except PatternsError:
                pname = it["focus_pattern"]
            lines.append(
                f"- [ ] `{it['problem_id']}` — {it['title']} "
                f"({it['difficulty']}, focus: {pname})")
    return "\n".join(lines) + "\n"


def export_plan(plan: dict, path: str | Path) -> Path:
    """Write the rendered plan markdown to ``path``. Returns the path."""
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_plan(plan), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 7. Weekly drills: new problems from weak patterns + due reviews,
#    packed into a daily time budget.
# ---------------------------------------------------------------------------

def build_drill(weak: list[dict] | None = None, minutes_per_day: int = 45,
                days: int = 7, seed: int = 0, start=None,
                attempts: list[dict] | None = None) -> dict:
    """Build a day-by-day drill schedule.

    Each day: one new problem from the weakest pattern that still has
    untried problems, then due spaced-repetition reviews while the time
    budget lasts. Time estimates: easy 15 / medium 25 / hard 35 min.
    Deterministic for a given seed.
    """
    if minutes_per_day < 15:
        raise PatternsError("minutes_per_day must be >= 15.")
    if days < 1:
        raise PatternsError("days must be >= 1.")
    rng = random.Random(seed)
    start_day = _coerce_date(start)
    if weak is None:
        weak = weak_patterns(attempts=attempts)
    bank = {p["id"]: p for p in load_bank()}
    tried = {a["problem_id"] for a in (attempts if attempts is not None
                                       else read_attempts())}
    reviewed = {pid for pid, c in _load_cards().items()
                if c.get("reviews", 0) > 0}
    # Untried pools per weak pattern, easiest first (seed shuffles ties).
    pools: dict[str, list[dict]] = {}
    for g in weak:
        pid = g["pattern"]
        pool = [p for p in load_bank()
                if pid in p.get("patterns", [])
                and p["id"] not in tried and p["id"] not in reviewed]
        by_diff: dict[str, list[dict]] = {}
        for p in pool:
            by_diff.setdefault(p.get("difficulty", "medium"), []).append(p)
        ordered = []
        for diff in ("easy", "medium", "hard"):
            group = sorted(by_diff.get(diff, []), key=lambda p: p["id"])
            rng.shuffle(group)
            ordered.extend(group)
        pools[pid] = ordered
    days_out = []
    scheduled_reviews: set[str] = set()
    for d in range(days):
        day = start_day + timedelta(days=d)
        items: list[dict] = []
        used = 0

        def fits(p):
            return used + EST_MINUTES.get(p.get("difficulty", "medium"), 25) \
                <= minutes_per_day

        # One new problem from the weakest pattern that still has any.
        for g in weak:
            pool = pools.get(g["pattern"], [])
            cand = next((p for p in pool if fits(p)), None)
            if cand is not None:
                pool.remove(cand)
                est = EST_MINUTES.get(cand.get("difficulty", "medium"), 25)
                items.append({"problem_id": cand["id"], "title": cand["title"],
                              "difficulty": cand["difficulty"],
                              "focus_pattern": g["pattern"],
                              "kind": "new", "est_minutes": est})
                used += est
                break
        # Fill the rest of the budget with due reviews.
        for card in due_cards(as_of=day):
            pid = card["problem_id"]
            if pid in scheduled_reviews or pid in tried and any(
                    i["problem_id"] == pid for i in items):
                continue
            p = bank.get(pid)
            if p is None or not fits(p):
                continue
            est = EST_MINUTES.get(p.get("difficulty", "medium"), 25)
            focus = (p.get("patterns") or [""])[0]
            items.append({"problem_id": pid, "title": p["title"],
                          "difficulty": p["difficulty"],
                          "focus_pattern": focus,
                          "kind": "review", "est_minutes": est})
            used += est
            scheduled_reviews.add(pid)
        days_out.append({"date": day.isoformat(), "items": items,
                         "total_minutes": used})
    return {"start": start_day.isoformat(), "minutes_per_day": minutes_per_day,
            "days": days_out, "seed": seed, "generated": _today_iso()}


def render_drill(drill: dict) -> str:
    """Render a drill schedule as readable text."""
    lines = [f"Weekly drill — {drill['minutes_per_day']} min/day "
             f"from {drill['start']}", ""]
    for d in drill["days"]:
        lines.append(f"{d['date']} ({d['total_minutes']} min)")
        if not d["items"]:
            lines.append("  (rest day — nothing due)")
        for it in d["items"]:
            tag = "NEW" if it["kind"] == "new" else "REVIEW"
            lines.append(f"  [{tag}] `{it['problem_id']}` — {it['title']} "
                         f"({it['difficulty']}, ~{it['est_minutes']} min, "
                         f"{it['focus_pattern']})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# 8. Mastery dashboard.
# ---------------------------------------------------------------------------

def _streak_days(attempts: list[dict]) -> int:
    days = sorted({a["date"] for a in attempts if a.get("date")})
    if not days:
        return 0
    day_set = set(days)
    cursor = date.today()
    if cursor.isoformat() not in day_set:
        cursor -= timedelta(days=1)
    streak = 0
    while cursor.isoformat() in day_set:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def mastery_report(attempts: list[dict] | None = None, as_of=None) -> dict:
    """Full dashboard payload: per-pattern rows, overall %, streaks."""
    if attempts is None:
        attempts = read_attempts()
    mastery = pattern_mastery(attempts)
    cov = coverage()
    due = {c["problem_id"] for c in due_cards(as_of=as_of)}
    bank = load_bank()
    prob_patterns = {p["id"]: p.get("patterns", []) for p in bank}
    rows = []
    for p in PATTERNS:
        pid = p["id"]
        m = mastery[pid]
        due_n = sum(1 for prob_id in cov.get(pid, []) if prob_id in due)
        rows.append({
            "pattern": pid, "name": p["name"],
            "bank_problems": len(cov.get(pid, [])),
            "attempts": m["attempts"], "solved": m["solved"],
            "solve_rate": m["solve_rate"], "avg_quality": m["avg_quality"],
            "mastery": m["mastery"], "due": due_n,
        })
    known = [m["mastery"] for m in mastery.values() if m["mastery"] is not None]
    attempted_ids = {a["problem_id"] for a in attempts}
    solved_ids = {a["problem_id"] for a in attempts if a.get("solved")}
    return {
        "patterns": rows,
        "overall_mastery": round(sum(known) / len(known)) if known else None,
        "patterns_attempted": sum(1 for m in mastery.values()
                                  if m["attempts"] > 0),
        "patterns_weak": len(weak_patterns(mastery)),
        "total_attempts": len(attempts),
        "problems_attempted": len(attempted_ids),
        "problems_solved": len(solved_ids),
        "bank_problems": len(bank),
        "due_total": len(due),
        "streak_days": _streak_days(attempts),
        "as_of": _coerce_date(as_of).isoformat(),
    }


def render_mastery(report: dict) -> str:
    """Render the mastery report as an aligned text table."""
    lines = ["Coding patterns mastery", ""]
    ov = report["overall_mastery"]
    lines.append(
        f"Overall: {ov if ov is not None else '—'}%   "
        f"attempts: {report['total_attempts']}   "
        f"solved: {report['problems_solved']}/{report['problems_attempted']} problems   "
        f"due reviews: {report['due_total']}   "
        f"streak: {report['streak_days']}d")
    lines.append("")
    header = (f"{'Pattern':<22}{'Bank':>5}{'Tried':>7}{'Solved':>8}"
              f"{'Mastery':>9}{'Due':>5}")
    lines.append(header)
    lines.append("-" * len(header))
    for r in report["patterns"]:
        m = f"{r['mastery']}%" if r["mastery"] is not None else "untested"
        lines.append(f"{r['name'][:21]:<22}{r['bank_problems']:>5}"
                     f"{r['attempts']:>7}{r['solved']:>8}{m:>9}{r['due']:>5}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 9. Cheat sheets: one-page pattern references.
# ---------------------------------------------------------------------------

def cheatsheet(pattern_id: str) -> str:
    """Render a one-page markdown cheat sheet for a pattern."""
    p = get_pattern(pattern_id)
    banked = problems_for_pattern(pattern_id)
    lines = [f"# {p['name']} — cheat sheet", "", p["blurb"], "",
             "## Recognize it", ""]
    lines += [f"- {c}" for c in p["cues"]]
    lines += ["", "## Template", "", "```python", p["template"], "```", "",
              f"**Complexity:** {p['complexity']}", ""]
    lines += ["## Practice in the bank", ""]
    if banked:
        for b in banked:
            lines.append(f"- `{b['id']}` — {b['title']} ({b['difficulty']})")
    else:
        lines.append("_No bank problems tagged with this pattern yet. "
                     "Add some via docs/adding_problems.md._")
    related = [get_pattern(r)["name"] for r in p["related"]]
    lines += ["", "## Goes well with", "",
              ", ".join(f"{n} (`{r}`)" for n, r in
                        zip(related, p["related"])),
              ""]
    return "\n".join(lines)


def export_cheatsheets(out_dir: str | Path) -> list[Path]:
    """Write one markdown cheat sheet per pattern. Returns written paths."""
    d = Path(out_dir).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    paths = []
    for pid in PATTERN_IDS:
        fp = d / f"{pid}.md"
        fp.write_text(cheatsheet(pid), encoding="utf-8")
        paths.append(fp)
    return paths

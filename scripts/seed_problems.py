#!/usr/bin/env python3
"""Seed the candid problem bank: writes candid/data/problems/*.json.

Each problem is verified: its reference solution is run through the same
judge the user faces, and every test (visible + hidden) must pass before
the file is written. Run: python3 scripts/seed_problems.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # repo root (scripts/seed_problems.py)
sys.path.insert(0, str(ROOT))
from candid.mock_judge import judge  # noqa: E402  (created below before running)

PROBLEMS = [
    {
        "id": "two-sum", "title": "Two Sum", "topic": "arrays", "difficulty": "easy",
        "statement": (
            "Given an array of integers `nums` and an integer `target`, return the "
            "indices of the two numbers that add up to `target`.\n\n"
            "Each input has exactly one solution; you may not use the same element twice.\n\n"
            "Example: nums = [2, 7, 11, 15], target = 9 -> [0, 1]"
        ),
        "function": "solve(nums, target)",
        "compare": "sorted",
        "visible_tests": [
            {"args": [[2, 7, 11, 15], 9], "expected": [0, 1]},
            {"args": [[3, 2, 4], 6], "expected": [1, 2]},
            {"args": [[3, 3], 6], "expected": [0, 1]},
        ],
        "hidden_tests": [
            {"args": [[-1, -2, -3, -4, -5], -8], "expected": [2, 4]},
            {"args": [[0, 4, 3, 0], 0], "expected": [0, 3]},
            {"args": [[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 19], "expected": [8, 9]},
            {"args": [[-10, 5, 15, 20, -5], 25], "expected": [1, 3]},
        ],
        "hints": [
            "A brute-force double loop is O(n^2). Can you check the complement in O(1)?",
            "As you scan, store each value you've seen in a hash map: value -> index.",
            "For x = nums[i], you need target - x. Look it up before inserting x.",
        ],
        "reference_solution": (
            "def solve(nums, target):\n"
            "    seen = {}\n"
            "    for i, x in enumerate(nums):\n"
            "        if target - x in seen:\n"
            "            return [seen[target - x], i]\n"
            "        seen[x] = i\n"
            "    return []\n"
        ),
        "complexity": "Time O(n) — one pass with hash-map lookups. Space O(n) for the map.",
    },
    {
        "id": "max-subarray", "title": "Maximum Subarray", "topic": "arrays", "difficulty": "easy",
        "statement": (
            "Given an integer array `nums`, find the contiguous subarray with the "
            "largest sum and return that sum.\n\n"
            "Example: nums = [-2, 1, -3, 4, -1, 2, 1, -5, 4] -> 6"
        ),
        "function": "solve(nums)",
        "compare": "exact",
        "visible_tests": [
            {"args": [[-2, 1, -3, 4, -1, 2, 1, -5, 4]], "expected": 6},
            {"args": [[1]], "expected": 1},
            {"args": [[5, 4, -1, 7, 8]], "expected": 23},
        ],
        "hidden_tests": [
            {"args": [[-1]], "expected": -1},
            {"args": [[-2, -1]], "expected": -1},
            {"args": [[0, 0, 0]], "expected": 0},
            {"args": [[1, 2, 3, 4, 5]], "expected": 15},
        ],
        "hints": [
            "Brute force checks all O(n^2) subarrays. Think about what you know when you extend a subarray by one element.",
            "Kadane's algorithm: at each position, the best subarray ending here is max(x, best_so_far + x).",
            "Track two variables as you scan: best ending here, and best overall.",
        ],
        "reference_solution": (
            "def solve(nums):\n"
            "    best = cur = nums[0]\n"
            "    for x in nums[1:]:\n"
            "        cur = max(x, cur + x)\n"
            "        best = max(best, cur)\n"
            "    return best\n"
        ),
        "complexity": "Time O(n), space O(1) — Kadane's algorithm.",
    },
    {
        "id": "valid-anagram", "title": "Valid Anagram", "topic": "strings", "difficulty": "easy",
        "statement": (
            "Given two strings `s` and `t`, return True if `t` is an anagram of `s`, "
            "else False.\n\n"
            'Example: s = "anagram", t = "nagaram" -> True'
        ),
        "function": "solve(s, t)",
        "compare": "exact",
        "visible_tests": [
            {"args": ["anagram", "nagaram"], "expected": True},
            {"args": ["rat", "car"], "expected": False},
        ],
        "hidden_tests": [
            {"args": ["a", "ab"], "expected": False},
            {"args": ["", ""], "expected": True},
            {"args": ["aacc", "ccac"], "expected": False},
            {"args": ["listen", "silent"], "expected": True},
        ],
        "hints": [
            "Anagrams have identical character counts. What data structure counts characters?",
            "collections.Counter(s) == collections.Counter(t) is the one-liner — but first check len(s) == len(t).",
            "Sorting both strings also works but costs O(n log n).",
        ],
        "reference_solution": (
            "def solve(s, t):\n"
            "    from collections import Counter\n"
            "    return len(s) == len(t) and Counter(s) == Counter(t)\n"
        ),
        "complexity": "Time O(n), space O(1) for lowercase letters (O(k) alphabet).",
    },
    {
        "id": "longest-substring", "title": "Longest Substring Without Repeating Characters",
        "topic": "strings", "difficulty": "medium",
        "statement": (
            "Given a string `s`, find the length of the longest substring without "
            "repeating characters.\n\n"
            'Example: s = "abcabcbb" -> 3 ("abc")'
        ),
        "function": "solve(s)",
        "compare": "exact",
        "visible_tests": [
            {"args": ["abcabcbb"], "expected": 3},
            {"args": ["bbbbb"], "expected": 1},
            {"args": ["pwwkew"], "expected": 3},
        ],
        "hidden_tests": [
            {"args": [""], "expected": 0},
            {"args": ["dvdf"], "expected": 3},
            {"args": ["abba"], "expected": 2},
            {"args": ["tmmzuxt"], "expected": 5},
        ],
        "hints": [
            "The brute force checks all substrings: O(n^2). Notice the window only grows/shrinks at the ends.",
            "Sliding window: expand the right edge; when a duplicate enters, move the left edge past its previous occurrence.",
            "Keep a dict of char -> last index. left = max(left, last[ch] + 1) on duplicates.",
        ],
        "reference_solution": (
            "def solve(s):\n"
            "    last = {}\n"
            "    start = best = 0\n"
            "    for i, ch in enumerate(s):\n"
            "        if ch in last and last[ch] >= start:\n"
            "            start = last[ch] + 1\n"
            "        last[ch] = i\n"
            "        best = max(best, i - start + 1)\n"
            "    return best\n"
        ),
        "complexity": "Time O(n) — each character visited at most twice. Space O(min(n, alphabet)).",
    },
    {
        "id": "group-anagrams", "title": "Group Anagrams", "topic": "hashmap", "difficulty": "medium",
        "statement": (
            "Given a list of strings `strs`, group the anagrams together. Return the "
            "groups in any order.\n\n"
            'Example: ["eat", "tea", "tan", "ate", "nat", "bat"] -> '
            '[["bat"], ["nat", "tan"], ["ate", "eat", "tea"]]'
        ),
        "function": "solve(strs)",
        "compare": "sorted_nested",
        "visible_tests": [
            {"args": [["eat", "tea", "tan", "ate", "nat", "bat"]],
             "expected": [["bat"], ["nat", "tan"], ["ate", "eat", "tea"]]},
            {"args": [[""]], "expected": [[""]]},
            {"args": [["a"]], "expected": [["a"]]},
        ],
        "hidden_tests": [
            {"args": [["abc", "bca", "xyz", "zyx"]], "expected": [["abc", "bca"], ["xyz", "zyx"]]},
            {"args": [["ddddddddddg", "dgggggggggg"]], "expected": [["ddddddddddg"], ["dgggggggggg"]]},
            {"args": [["a", "b", "c"]], "expected": [["a"], ["b"], ["c"]]},
        ],
        "hints": [
            "Anagrams share a canonical form. What single key could represent a whole group?",
            "The sorted tuple of characters works as a dict key: tuple(sorted(word)).",
            "For long strings, a 26-count signature is O(n) per word instead of O(n log n).",
        ],
        "reference_solution": (
            "def solve(strs):\n"
            "    from collections import defaultdict\n"
            "    groups = defaultdict(list)\n"
            "    for w in strs:\n"
            "        groups[tuple(sorted(w))].append(w)\n"
            "    return list(groups.values())\n"
        ),
        "complexity": "Time O(n * k log k) for words of length k (O(n*k) with count signatures). Space O(n*k).",
    },
    {
        "id": "container-water", "title": "Container With Most Water", "topic": "two-pointers",
        "difficulty": "medium",
        "statement": (
            "Given integer array `height` of length n, where n vertical lines are drawn "
            "at positions 0..n-1 with the given heights: find the two lines that together "
            "with the x-axis form the container holding the most water. Return the area.\n\n"
            "Example: height = [1, 8, 6, 2, 5, 4, 8, 3, 7] -> 49"
        ),
        "function": "solve(height)",
        "compare": "exact",
        "visible_tests": [
            {"args": [[1, 8, 6, 2, 5, 4, 8, 3, 7]], "expected": 49},
            {"args": [[1, 1]], "expected": 1},
        ],
        "hidden_tests": [
            {"args": [[4, 3, 2, 1, 4]], "expected": 16},
            {"args": [[1, 2, 1]], "expected": 2},
            {"args": [[2, 3, 4, 5, 18, 17, 6]], "expected": 17},
        ],
        "hints": [
            "Brute force tries all pairs: O(n^2). The area is min(h[l], h[r]) * (r - l).",
            "Start with the widest container (both ends). Which pointer should move inward?",
            "Move the shorter line's pointer: the taller line can't improve the area with a narrower width, but the shorter one might find a taller partner.",
        ],
        "reference_solution": (
            "def solve(height):\n"
            "    l, r = 0, len(height) - 1\n"
            "    best = 0\n"
            "    while l < r:\n"
            "        best = max(best, min(height[l], height[r]) * (r - l))\n"
            "        if height[l] < height[r]:\n"
            "            l += 1\n"
            "        else:\n"
            "            r -= 1\n"
            "    return best\n"
        ),
        "complexity": "Time O(n) — single pass with two pointers. Space O(1).",
    },
    {
        "id": "climbing-stairs", "title": "Climbing Stairs", "topic": "dp", "difficulty": "easy",
        "statement": (
            "You are climbing a staircase of `n` steps. Each time you can climb 1 or 2 "
            "steps. Return the number of distinct ways to reach the top.\n\n"
            "Example: n = 3 -> 3 (1+1+1, 1+2, 2+1)"
        ),
        "function": "solve(n)",
        "compare": "exact",
        "visible_tests": [
            {"args": [2], "expected": 2},
            {"args": [3], "expected": 3},
            {"args": [5], "expected": 8},
        ],
        "hidden_tests": [
            {"args": [1], "expected": 1},
            {"args": [10], "expected": 89},
            {"args": [20], "expected": 10946},
            {"args": [30], "expected": 1346269},
        ],
        "hints": [
            "How many ways to reach step i? It only depends on steps i-1 and i-2.",
            "This is the Fibonacci recurrence: ways[i] = ways[i-1] + ways[i-2].",
            "You only need the last two values — O(1) space is enough.",
        ],
        "reference_solution": (
            "def solve(n):\n"
            "    a, b = 1, 1\n"
            "    for _ in range(n - 1):\n"
            "        a, b = b, a + b\n"
            "    return b\n"
        ),
        "complexity": "Time O(n), space O(1).",
    },
    {
        "id": "coin-change", "title": "Coin Change", "topic": "dp", "difficulty": "medium",
        "statement": (
            "Given coins of different denominations and a total `amount`, compute the "
            "fewest number of coins needed to make up that amount. Return -1 if impossible.\n\n"
            "Example: coins = [1, 2, 5], amount = 11 -> 3 (5 + 5 + 1)"
        ),
        "function": "solve(coins, amount)",
        "compare": "exact",
        "visible_tests": [
            {"args": [[1, 2, 5], 11], "expected": 3},
            {"args": [[2], 3], "expected": -1},
            {"args": [[1], 0], "expected": 0},
        ],
        "hidden_tests": [
            {"args": [[1, 2, 5], 100], "expected": 20},
            {"args": [[186, 419, 83, 408], 6249], "expected": 20},
            {"args": [[2, 5, 10, 1], 27], "expected": 4},
        ],
        "hints": [
            "Greedy (largest coin first) fails: coins=[1,3,4], amount=6 needs 3+3, greedy picks 4+1+1.",
            "Define dp[a] = fewest coins for amount a. dp[a] = 1 + min(dp[a - c]) over coins c <= a.",
            "Fill dp bottom-up from 0 to amount; answer dp[amount], or -1 if unreachable.",
        ],
        "reference_solution": (
            "def solve(coins, amount):\n"
            "    INF = float('inf')\n"
            "    dp = [INF] * (amount + 1)\n"
            "    dp[0] = 0\n"
            "    for a in range(1, amount + 1):\n"
            "        for c in coins:\n"
            "            if c <= a:\n"
            "                dp[a] = min(dp[a], dp[a - c] + 1)\n"
            "    return dp[amount] if dp[amount] != INF else -1\n"
        ),
        "complexity": "Time O(amount * coins), space O(amount).",
    },
    {
        "id": "number-of-islands", "title": "Number of Islands", "topic": "graphs", "difficulty": "medium",
        "statement": (
            "Given an m x n binary grid of '1's (land) and '0's (water), return the "
            "number of islands. An island is surrounded by water and formed by "
            "connecting adjacent lands horizontally or vertically.\n\n"
            'Example: [["1","1","0"],["1","0","0"],["0","0","1"]] -> 2'
        ),
        "function": "solve(grid)",
        "compare": "exact",
        "visible_tests": [
            {"args": [[["1", "1", "1", "1", "0"], ["1", "1", "0", "1", "0"],
                       ["1", "1", "0", "0", "0"], ["0", "0", "0", "0", "0"]]], "expected": 1},
            {"args": [[["1", "1", "0", "0", "0"], ["1", "1", "0", "0", "0"],
                       ["0", "0", "1", "0", "0"], ["0", "0", "0", "1", "1"]]], "expected": 3},
        ],
        "hidden_tests": [
            {"args": [[["0", "0"], ["0", "0"]]], "expected": 0},
            {"args": [[["1"]]], "expected": 1},
            {"args": [[["1", "0", "1"], ["0", "1", "0"], ["1", "0", "1"]]], "expected": 5},
        ],
        "hints": [
            "Each island is a connected component. How do you explore everything reachable from one land cell?",
            "DFS/BFS from each unvisited '1', marking visited cells as '0'. Each new DFS = one island.",
            "Iterative BFS with a queue avoids recursion-depth issues on huge grids.",
        ],
        "reference_solution": (
            "def solve(grid):\n"
            "    if not grid or not grid[0]:\n"
            "        return 0\n"
            "    R, C = len(grid), len(grid[0])\n"
            "    count = 0\n"
            "    def dfs(r, c):\n"
            "        if not (0 <= r < R and 0 <= c < C) or grid[r][c] != '1':\n"
            "            return\n"
            "        grid[r][c] = '0'\n"
            "        dfs(r + 1, c); dfs(r - 1, c); dfs(r, c + 1); dfs(r, c - 1)\n"
            "    for r in range(R):\n"
            "        for c in range(C):\n"
            "            if grid[r][c] == '1':\n"
            "                count += 1\n"
            "                dfs(r, c)\n"
            "    return count\n"
        ),
        "complexity": "Time O(m*n) — each cell visited once. Space O(m*n) worst-case recursion.",
    },
    {
        "id": "course-schedule", "title": "Course Schedule", "topic": "graphs", "difficulty": "medium",
        "statement": (
            "There are `numCourses` courses labeled 0..numCourses-1. `prerequisites[i] = [a, b]` "
            "means course a requires course b first. Return True if all courses can be "
            "finished, else False.\n\n"
            "Example: numCourses = 2, prerequisites = [[1, 0]] -> True"
        ),
        "function": "solve(numCourses, prerequisites)",
        "compare": "exact",
        "visible_tests": [
            {"args": [2, [[1, 0]]], "expected": True},
            {"args": [2, [[1, 0], [0, 1]]], "expected": False},
        ],
        "hidden_tests": [
            {"args": [3, [[0, 1], [1, 2]]], "expected": True},
            {"args": [4, [[1, 0], [2, 1], [3, 2], [1, 3]]], "expected": False},
            {"args": [1, []], "expected": True},
            {"args": [5, [[1, 4], [2, 4], [3, 1], [3, 2]]], "expected": True},
        ],
        "hints": [
            "Model courses as a directed graph: edge b -> a means b before a. What's the forbidden structure?",
            "It's cycle detection. A course schedule is feasible iff the graph is a DAG.",
            "Use DFS with 3 colors (unvisited / in-stack / done), or Kahn's algorithm peeling zero-in-degree nodes.",
        ],
        "reference_solution": (
            "def solve(numCourses, prerequisites):\n"
            "    from collections import defaultdict\n"
            "    graph = defaultdict(list)\n"
            "    for a, b in prerequisites:\n"
            "        graph[b].append(a)\n"
            "    WHITE, GRAY, BLACK = 0, 1, 2\n"
            "    color = [WHITE] * numCourses\n"
            "    def dfs(u):\n"
            "        color[u] = GRAY\n"
            "        for v in graph[u]:\n"
            "            if color[v] == GRAY:\n"
            "                return False\n"
            "            if color[v] == WHITE and not dfs(v):\n"
            "                return False\n"
            "        color[u] = BLACK\n"
            "        return True\n"
            "    return all(dfs(u) for u in range(numCourses) if color[u] == WHITE)\n"
        ),
        "complexity": "Time O(V + E), space O(V + E) — DFS cycle detection.",
    },
    {
        "id": "top-k-frequent", "title": "Top K Frequent Elements", "topic": "heap", "difficulty": "medium",
        "statement": (
            "Given an integer array `nums` and an integer `k`, return the `k` most "
            "frequent elements, in any order.\n\n"
            "Example: nums = [1, 1, 1, 2, 2, 3], k = 2 -> [1, 2]"
        ),
        "function": "solve(nums, k)",
        "compare": "sorted",
        "visible_tests": [
            {"args": [[1, 1, 1, 2, 2, 3], 2], "expected": [1, 2]},
            {"args": [[1], 1], "expected": [1]},
        ],
        "hidden_tests": [
            {"args": [[4, 1, -1, 2, -1, 2, 3], 2], "expected": [-1, 2]},
            {"args": [[3, 0, 1, 0], 1], "expected": [0]},
            {"args": [[1, 2, 3, 4, 5, 1, 2, 3, 1, 2, 1], 3], "expected": [1, 2, 3]},
        ],
        "hints": [
            "First count frequencies with collections.Counter. Then what?",
            "A heap of size k gives O(n log k). Sorting all frequencies is O(n log n) — fine for interviews, but mention the heap.",
            "Bucket sort by frequency is O(n): buckets[f] = elements occurring f times.",
        ],
        "reference_solution": (
            "def solve(nums, k):\n"
            "    from collections import Counter\n"
            "    return [x for x, _ in Counter(nums).most_common(k)]\n"
        ),
        "complexity": "Time O(n log k) with a heap (O(n) with bucket sort). Space O(n).",
    },
]

OUT = ROOT / "candid" / "data" / "problems"
OUT.mkdir(parents=True, exist_ok=True)

failed = []
for p in PROBLEMS:
    result = judge(p, p["reference_solution"], per_test_timeout=5.0)
    bad = [t for t in result["tests"] if t["verdict"] != "accepted"]
    if bad:
        failed.append((p["id"], bad))
        print(f"FAIL {p['id']}: {bad}")
        continue
    (OUT / f"{p['id']}.json").write_text(json.dumps(p, indent=2), encoding="utf-8")
    print(f"ok   {p['id']} ({p['topic']}/{p['difficulty']}, "
          f"{len(p['visible_tests'])} visible + {len(p['hidden_tests'])} hidden)")

if failed:
    sys.exit(f"{len(failed)} problem(s) failed verification")
print(f"\nWrote {len(PROBLEMS)} problems to {OUT}")

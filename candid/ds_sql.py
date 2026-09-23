"""Data-Science SQL drills with a real judge.

A seeded bank of ~15 SQL interview questions (aggregations, window
functions, joins, CTEs, date logic). Each question ships a setup script
that builds a tiny in-memory SQLite database plus the expected result.
The judge runs the candidate's query against that database and compares
result row-sets, order-insensitively unless the question requires ORDER BY.

Usage:
    python -m candid ds-sql list [--topic window] [--difficulty hard]
    python -m candid ds-sql show ds-sql-06
    python -m candid ds-sql solve ds-sql-06 --file solution.sql
    cat solution.sql | python -m candid ds-sql solve ds-sql-06

Everything runs locally (stdlib sqlite3). The judge only executes the
candidate's own query text against the seeded database.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

DATA = Path(__file__).parent / "data"
QUESTIONS_FILE = DATA / "ds_sql.json"


class SQLDrillError(Exception):
    """Raised for SQL-drill usage errors."""


# ---------------------------------------------------------------------------
# question bank
# ---------------------------------------------------------------------------

def load_questions() -> list[dict]:
    if not QUESTIONS_FILE.exists():
        raise SQLDrillError(f"SQL question bank not found at {QUESTIONS_FILE}.")
    data = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    return data["questions"]


def list_questions(topic: str | None = None,
                   difficulty: str | None = None) -> list[dict]:
    out = []
    for q in load_questions():
        if topic and q.get("topic") != topic:
            continue
        if difficulty and q.get("difficulty") != difficulty:
            continue
        out.append(q)
    return out


def get_question(qid: str) -> dict:
    for q in load_questions():
        if q["id"] == qid:
            return q
    known = ", ".join(q["id"] for q in load_questions())
    raise SQLDrillError(f"Unknown SQL question '{qid}'. Known: {known}")


def render_question(q: dict) -> str:
    tables = [ln.strip() for ln in q["setup_sql"].splitlines()
              if ln.strip().upper().startswith("CREATE TABLE")]
    lines = [
        f"### {q['title']}  [{q['topic']} · {q['difficulty']}]  ({q['id']})",
        "",
        q["prompt"],
        "",
        "**Tables:**",
    ]
    lines += [f"  {t}" for t in tables]
    lines += ["", f"Order matters: {'yes' if q.get('order_matters') else 'no'}"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# judge
# ---------------------------------------------------------------------------

def _build_db(setup_sql: str) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(setup_sql)
    except sqlite3.Error as e:
        conn.close()
        raise SQLDrillError(f"Question setup script is broken: {e}") from e
    return conn


def run_query(setup_sql: str, query: str) -> tuple[list[str], list[tuple]]:
    """Run `query` against the seeded DB. Returns (column names, rows)."""
    stripped = query.strip().rstrip(";").strip()
    if not stripped:
        raise SQLDrillError("Empty query — nothing to judge.")
    first = stripped.split(None, 1)[0].upper() if stripped.split() else ""
    if first not in ("SELECT", "WITH"):
        raise SQLDrillError("Only SELECT / WITH queries are judged "
                            f"(got: {first or 'nothing'}).")
    conn = _build_db(setup_sql)
    try:
        cur = conn.execute(stripped)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = [tuple(r) for r in cur.fetchall()]
    except sqlite3.Error as e:
        raise SQLDrillError(f"Your query failed: {e}") from e
    finally:
        conn.close()
    return cols, rows


def fetch_expected(setup_sql: str, solution: str) -> list[list]:
    """Compute the expected rows by running the reference solution.

    Used to seed/verify the bank. Values are converted to JSON-safe types.
    """
    _, rows = run_query(setup_sql, solution)
    return [[_jsonable(v) for v in r] for r in rows]


def _jsonable(v):
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    return str(v)


def _cells_equal(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)
    return abs(fa - fb) <= 1e-6 * max(1.0, abs(fa), abs(fb))


def _rows_equal(r1: tuple, r2: tuple) -> bool:
    return len(r1) == len(r2) and all(_cells_equal(a, b) for a, b in zip(r1, r2))


def _sort_key(v):
    if v is None:
        return (1, "")
    try:
        return (0, float(v))
    except (TypeError, ValueError):
        return (2, str(v))


def compare(got_rows: list[tuple], want_rows: list[tuple],
            order_matters: bool) -> dict:
    """Compare result row-sets. Returns a verdict dict with a diff."""
    want = [tuple(r) for r in want_rows]
    got = list(got_rows)
    col_mismatch = bool(want) and any(len(r) != len(want[0]) for r in got)

    seq_got = got if order_matters else sorted(got, key=lambda r: tuple(_sort_key(v) for v in r))
    seq_want = want if order_matters else sorted(want, key=lambda r: tuple(_sort_key(v) for v in r))

    if not col_mismatch and len(seq_got) == len(seq_want) and \
            all(_rows_equal(g, w) for g, w in zip(seq_got, seq_want)):
        return {"passed": True, "missing": [], "extra": [],
                "column_mismatch": False}

    # greedy multiset diff for a readable report
    remaining = list(seq_got)
    missing: list[tuple] = []
    for w in seq_want:
        hit = next((i for i, g in enumerate(remaining) if _rows_equal(g, w)), None)
        if hit is None:
            missing.append(w)
        else:
            remaining.pop(hit)
    return {"passed": False, "missing": missing, "extra": remaining,
            "column_mismatch": col_mismatch}


def judge(qid: str, query: str) -> dict:
    """Judge a query for question `qid`. Returns the full verdict dict."""
    q = get_question(qid)
    cols, rows = run_query(q["setup_sql"], query)
    want = [tuple(r) for r in q["expected"]]
    result = compare(rows, want, bool(q.get("order_matters")))
    result.update({
        "id": qid,
        "title": q["title"],
        "columns": cols,
        "got_rows": len(rows),
        "want_rows": len(want),
    })
    return result


def _fmt_row(r: tuple) -> str:
    return "(" + ", ".join("NULL" if v is None else repr(v) for v in r) + ")"


def render_verdict(result: dict, show_hint: bool = True) -> str:
    icon = "✅" if result["passed"] else "❌"
    lines = [
        f"{icon} {'PASS' if result['passed'] else 'FAIL'} — {result['id']}: {result['title']}",
        f"Your query returned {result['got_rows']} row(s); expected {result['want_rows']}.",
    ]
    if result.get("column_mismatch"):
        lines.append("⚠️  Column count differs from the expected result — "
                     "check your SELECT list.")
    if not result["passed"]:
        if result["missing"]:
            lines += ["", "Missing rows (expected but not returned):"]
            lines += [f"  – {_fmt_row(r)}" for r in result["missing"][:10]]
            if len(result["missing"]) > 10:
                lines.append(f"  … and {len(result['missing']) - 10} more")
        if result["extra"]:
            lines += ["", "Extra rows (returned but not expected):"]
            lines += [f"  + {_fmt_row(r)}" for r in result["extra"][:10]]
            if len(result["extra"]) > 10:
                lines.append(f"  … and {len(result['extra']) - 10} more")
        if show_hint:
            q = get_question(result["id"])
            if q.get("hint"):
                lines += ["", f"💡 Hint: {q['hint']}"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry points (wired in candid/__main__.py)
# ---------------------------------------------------------------------------

def read_query_interactive() -> str:
    print("Paste your SQL query below. End with a line containing only EOF, "
          "or press Ctrl-D.")
    lines: list[str] = []
    try:
        while True:
            line = input()
            if line.strip() == "EOF":
                break
            lines.append(line)
    except EOFError:
        pass
    return "\n".join(lines)


def cmd_list(args) -> None:
    qs = list_questions(topic=args.topic, difficulty=args.difficulty)
    if not qs:
        print("No questions match. Try without filters.")
        return
    print(f"{'ID':<12}{'Title':<42}{'Topic':<14}Difficulty")
    for q in qs:
        print(f"{q['id']:<12}{q['title'][:41]:<42}{q['topic']:<14}{q['difficulty']}")


def cmd_show(args) -> None:
    q = get_question(args.id)
    print(render_question(q))


def cmd_solve(args) -> int:
    q = get_question(args.id)
    if args.file:
        query = Path(args.file).read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        query = sys.stdin.read()
    else:
        query = read_query_interactive()
    result = judge(args.id, query)
    print(render_verdict(result))
    return 0 if result["passed"] else 1

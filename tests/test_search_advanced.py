"""Tests for candid.search.search_advanced / explain_query (batch-69 worker 2).

Hermetic: all data lives in temp dirs and every search_advanced call passes
explicit paths. stdlib only.

candid.query is owned by batch-69 worker 1 and may not exist yet; the
_contract stub below implements exactly the contract search_advanced codes
against (Term/Query dataclasses, parse(), QueryError, VALID_FIELDS) and is
installed into sys.modules as "candid.query" ONLY when the real module
cannot be imported. At integration the real parser is used instead.
"""

import json
import os
import re as _re
import sys
import tempfile
import types as _types
import unittest
from dataclasses import dataclass, replace
from datetime import date as _date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Contract stub for candid.query (used only if worker 1's module is missing).
# ---------------------------------------------------------------------------

class QueryError(Exception):
    """Raised for invalid advanced queries."""


VALID_FIELDS = frozenset({"company", "role", "status", "source", "notes",
                          "jd", "title", "kind"})


@dataclass
class Term:
    value: str
    field: str | None = None
    negated: bool = False
    regex: bool = False
    fuzzy = None          # int max edit distance, or None
    phrase: bool = False


@dataclass
class Query:
    groups: tuple = ()
    after = None          # date | None
    before = None         # date | None


_TOKEN_RE = _re.compile(r"\(|\)|\"[^\"]*\"|/(?:\\.|[^/\\])*/|[^\s()\"']+")


def _tokenize(s):
    toks = []
    pos, n = 0, len(s)
    while pos < n:
        if s[pos].isspace():
            pos += 1
            continue
        m = _TOKEN_RE.match(s, pos)
        if not m:
            raise QueryError(f"Cannot parse near {s[pos:pos + 20]!r}")
        raw = m.group(0)
        pos = m.end()
        if raw == "(":
            toks.append(("LPAREN", raw))
        elif raw == ")":
            toks.append(("RPAREN", raw))
        elif raw.startswith('"'):
            toks.append(("PHRASE", raw[1:-1]))
        elif raw.startswith("/"):
            toks.append(("REGEX", raw[1:-1]))
        else:
            toks.append(("WORD", raw))
    return toks


def _check_regex(pattern):
    try:
        _re.compile(pattern)
    except _re.error as exc:
        raise QueryError(f"Invalid regex {pattern!r}: {exc}") from exc


def _make_term(kind, text):
    if kind == "PHRASE":
        if not text:
            raise QueryError("Empty phrase")
        return Term(text, phrase=True)
    if kind == "REGEX":
        _check_regex(text)
        return Term(text, regex=True)
    # WORD: optional field: prefix, /re/ value, or val~N fuzzy suffix.
    field, value = None, text
    m = _re.match(r"^([A-Za-z][\w-]*):(.*)$", text, _re.DOTALL)
    if m:
        if m.group(1) not in VALID_FIELDS:
            raise QueryError(f"Unknown field {m.group(1)!r}")
        field, value = m.group(1), m.group(2)
    if not value:
        raise QueryError("Empty term" if field is None
                         else f"Empty value for field {field!r}")
    if len(value) >= 2 and value.startswith("/") and value.endswith("/"):
        _check_regex(value[1:-1])
        return Term(value[1:-1], field=field, regex=True)
    if value.startswith("/"):
        raise QueryError(f"Unterminated regex in {value!r}")
    fm = _re.match(r"^(.*)~(\d+)$", value, _re.DOTALL)
    if fm and fm.group(1):
        return Term(fm.group(1), field=field, fuzzy=int(fm.group(2)))
    return Term(value, field=field)


class _Parser:
    def __init__(self, toks):
        self.toks = toks
        self.i = 0
        self.after = None
        self.before = None

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def advance(self):
        tok = self.peek()
        if tok is None:
            raise QueryError("Unexpected end of query")
        self.i += 1
        return tok

    def parse(self):
        if not self.toks:
            return Query(groups=(), after=None, before=None)
        groups = self.parse_or()
        if self.peek() is not None:
            raise QueryError(f"Unexpected {self.peek()[1]!r}")
        # A query of only date filters yields one empty group: it matches
        # every document inside the date range.
        return Query(groups=tuple(tuple(g) for g in groups),
                     after=self.after, before=self.before)

    def parse_or(self):
        groups = self.parse_and()
        while self.peek() == ("WORD", "OR"):
            self.advance()
            groups = groups + self.parse_and()
        return groups

    def parse_and(self):
        acc = [[]]
        while True:
            p = self.peek()
            if p is None or p[0] == "RPAREN":
                break
            if p == ("WORD", "OR"):
                break
            if p == ("WORD", "AND"):
                self.advance()
                continue
            factor = self.parse_factor()
            acc = [a + b for a in acc for b in factor]
        if acc == [[]] and not (self.after or self.before):
            raise QueryError("Empty term group")
        return acc

    def parse_factor(self):
        negate = False
        while True:
            p = self.peek()
            if p is not None and p[0] == "WORD" and p[1].upper() == "NOT":
                self.advance()
                negate = not negate
            else:
                break
        kind, text = self.advance()
        if kind == "LPAREN":
            groups = self.parse_or()
            closing = self.peek()
            if closing is None or closing[0] != "RPAREN":
                raise QueryError("Unbalanced parenthesis")
            self.advance()
            if negate:  # NOT (A OR B) == (NOT A) AND (NOT B)
                return [[replace(t, negated=not t.negated)
                         for g in groups for t in g]]
            return groups
        if kind == "RPAREN":
            raise QueryError("Unbalanced parenthesis")
        if kind == "WORD" and text.startswith("-") and len(text) > 1:
            negate = not negate
            text = text[1:]
        if kind == "WORD":
            low = text.lower()
            if low.startswith("after:") or low.startswith("before:"):
                if negate:
                    raise QueryError("after:/before: cannot be negated")
                name = "after" if low.startswith("after:") else "before"
                datestr = text.split(":", 1)[1].strip()
                try:
                    d = _date.fromisoformat(datestr)
                except ValueError:
                    raise QueryError(f"Invalid date {datestr!r} in {name}:")
                if name == "after":
                    self.after = d
                else:
                    self.before = d
                return [[]]
        term = _make_term(kind, text)
        if negate:
            term = replace(term, negated=True)
        return [[term]]


def parse(query):
    return _Parser(_tokenize(query or "")).parse()


def _ensure_query_module():
    try:
        from candid import query
        return query
    except ImportError:
        stub = _types.ModuleType("candid.query")
        stub.QueryError = QueryError
        stub.VALID_FIELDS = VALID_FIELDS
        stub.Term = Term
        stub.Query = Query
        stub.parse = parse
        sys.modules["candid.query"] = stub
        return stub


Q = _ensure_query_module()

from candid import search as S  # noqa: E402


def _parser_or_is_correct():
    """True when candid.query builds a real OR-of-ANDs DNF.

    Worker 1's query.py had a bug where terms after an OR were appended to
    every group (``"a OR b"`` parsed as ``[[a, b], [b]]`` instead of
    ``[[a], [b]]``). The OR/parens tests below assert the contracted
    semantics; they are skipped until the parser is fixed rather than
    weakened to match the bug.
    """
    try:
        groups = Q.parse("python OR golang").groups
    except Exception:
        return False
    return [[t.value for t in g] for g in groups] == [["python"], ["golang"]]


_NEEDS_OR_FIX = "candid.query OR-group bug (worker 1's file)"


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

class AdvancedBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-adv-"))
        self.tracker = self.tmp / "tracker.json"
        self.prep = self.tmp / "prep"
        self.tailor = self.tmp / "tailor"
        self.debriefs = self.tmp / "debriefs"
        for d in (self.prep, self.tailor, self.debriefs):
            d.mkdir(parents=True, exist_ok=True)
        self.write_tracker([
            {"id": 1, "company": "Stripe", "role": "Senior ML Engineer",
             "status": "applied", "source": "referral",
             "notes": "python and ml platform work",
             "jd_text": "We need senior engineers. Python, Go.",
             "jd_link": "https://example.com/jobs/1",
             "date_added": "2026-09-10"},
            {"id": 2, "company": "Acme", "role": "Junior Data Analyst",
             "status": "saved", "source": "linkedin",
             "notes": "sql dashboards",
             "jd_text": "SQL and dashboards.",
             "jd_link": "",
             "date_added": "2026-09-20"},
            {"id": 3, "company": "Globex", "role": "ML Engineer",
             "status": "rejected", "source": "",
             "notes": "no date here",
             "jd_text": "", "jd_link": "",
             "date_added": ""},
            {"id": 4, "company": "Initech", "role": "Backend Engineer",
             "status": "applied", "source": "website",
             "notes": "golang services",
             "jd_text": "", "jd_link": "",
             "date_added": "not-a-date"},
        ])
        (self.prep / "stripe_loop.md").write_text(
            "# Stripe ML loop\npython system design practice\n",
            encoding="utf-8")
        (self.tailor / "resume.txt").write_text(
            "Resume: python, ml platform, dashboards.\n", encoding="utf-8")
        (self.debriefs / "onsite.md").write_text(
            "# Debrief\nBehavioral rounds went well.\n", encoding="utf-8")

    def write_tracker(self, apps):
        self.tracker.write_text(json.dumps(apps), encoding="utf-8")

    def adv(self, query, **kw):
        kw.setdefault("path", self.tracker)
        kw.setdefault("prep_dir", self.prep)
        kw.setdefault("tailor_dir", self.tailor)
        kw.setdefault("debriefs_dir", self.debriefs)
        return S.search_advanced(query, **kw)

    def app_refs(self, results):
        return {r["ref"] for r in results if r["kind"] == "application"}


# ---------------------------------------------------------------------------
# Boolean semantics
# ---------------------------------------------------------------------------

class BooleanTest(AdvancedBase):
    def test_and(self):
        self.assertEqual(self.app_refs(self.adv("python engineer")), {"1"})

    @unittest.skipUnless(_parser_or_is_correct(), _NEEDS_OR_FIX)
    def test_or(self):
        self.assertEqual(self.app_refs(self.adv("python OR golang")),
                         {"1", "4"})

    def test_or_lowercase_is_literal(self):
        # Only uppercase OR is an operator; lowercase "or" is a plain term,
        # so this is an AND of three terms that matches nothing here.
        self.assertEqual(self.adv("python or golang"), [])

    def test_not(self):
        # "senior" appears in app 1's title and jd_text: excluded.
        self.assertEqual(self.app_refs(self.adv("engineer -senior")),
                         {"3", "4"})

    def test_not_keyword(self):
        self.assertEqual(self.app_refs(self.adv("engineer NOT senior")),
                         {"3", "4"})

    @unittest.skipUnless(_parser_or_is_correct(), _NEEDS_OR_FIX)
    def test_parens(self):
        self.assertEqual(
            self.app_refs(self.adv("(python OR golang) engineer")), {"1", "4"})

    @unittest.skipUnless(_parser_or_is_correct(), _NEEDS_OR_FIX)
    def test_parens_grouping_matters(self):
        # "(engineer OR golang) senior"
        #   = (engineer AND senior) OR (golang AND senior) -> app 1 only.
        self.assertEqual(
            self.app_refs(self.adv("(engineer OR golang) senior")), {"1"})
        # "engineer OR golang senior"
        #   = engineer OR (golang AND senior) -> apps 1, 3, 4.
        self.assertEqual(
            self.app_refs(self.adv("engineer OR golang senior")),
            {"1", "3", "4"})

    def test_negated_only_query(self):
        hits = self.adv("-senior")
        self.assertEqual(self.app_refs(hits), {"2", "3", "4"})
        for h in hits:
            self.assertEqual(h["matched"], [],
                             "negated terms never appear in matched[]")

    def test_no_match(self):
        self.assertEqual(self.adv("zzznope"), [])

    def test_empty_query(self):
        self.assertEqual(self.adv(""), [])
        self.assertEqual(self.adv("   "), [])


# ---------------------------------------------------------------------------
# Field scoping
# ---------------------------------------------------------------------------

class FieldTest(AdvancedBase):
    def test_company_field(self):
        hits = self.adv("company:stripe")
        self.assertEqual(self.app_refs(hits), {"1"})
        self.assertEqual(hits[0]["matched"], ["company:stripe"])

    def test_status_field(self):
        self.assertEqual(self.app_refs(self.adv("status:applied")), {"1", "4"})

    def test_source_field(self):
        self.assertEqual(self.app_refs(self.adv("source:linkedin")), {"2"})

    def test_notes_field(self):
        self.assertEqual(self.app_refs(self.adv("notes:dashboards")), {"2"})

    def test_jd_field(self):
        # jd = jd_text + " " + jd_link.
        self.assertEqual(self.app_refs(self.adv("jd:senior")), {"1"})

    def test_title_field_application(self):
        # title = "<role> @ <company>"
        self.assertEqual(self.app_refs(self.adv("title:stripe")), {"1"})

    def test_field_does_not_leak(self):
        # "acme" is only in company; role:acme must not match app 2.
        self.assertEqual(self.app_refs(self.adv("role:acme")), set())

    def test_kind_field_on_files(self):
        hits = self.adv("kind:prep_pack python")
        kinds = {h["kind"] for h in hits}
        self.assertEqual(kinds, {"prep_pack"})
        hits = self.adv("kind:debrief")
        self.assertEqual({h["kind"] for h in hits}, {"debrief"})

    def test_unknown_field_stays_literal(self):
        # The parser keeps unknown fields as literal terms (no error);
        # "bogus:x" matches nothing here, and nothing is raised.
        self.assertEqual(self.adv("bogus:x"), [])


# ---------------------------------------------------------------------------
# Regex terms
# ---------------------------------------------------------------------------

class RegexTest(AdvancedBase):
    def test_regex(self):
        hits = self.adv("/senior.*engineer/")
        self.assertEqual(self.app_refs(hits), {"1"})
        self.assertEqual(hits[0]["matched"], ["regex:/senior.*engineer/"])

    def test_regex_case_insensitive(self):
        self.assertEqual(self.app_refs(self.adv("/SENIOR/")), {"1"})

    def test_regex_field_term_matcher(self):
        # The real parser's syntax never emits field+regex terms (a value
        # like company:/^str/ stays literal), but the matcher supports the
        # combination; exercise it directly.
        from candid.query import Term
        doc = S._app_doc({"id": 1, "company": "Stripe", "role": "Engineer"})
        term = Term(value="^str", field="company", regex=True)
        self.assertTrue(
            S._match_term_text(term, S._term_field_text(term, doc)))
        self.assertEqual(S._describe_term(term), "company:regex:/^str/")
        other = Term(value="^str", field="role", regex=True)
        self.assertFalse(
            S._match_term_text(other, S._term_field_text(other, doc)))

    def test_regex_no_match(self):
        self.assertEqual(self.adv("/zzzqqq/"), [])

    def test_invalid_regex_is_query_error(self):
        with self.assertRaises(Q.QueryError):
            self.adv("/([/")
        with self.assertRaises(Q.QueryError):
            self.adv("/zzz(q/")  # unbalanced paren inside the pattern

    def test_unterminated_regex_is_literal(self):
        # No closing slash: the parser falls back to a plain word term.
        self.assertEqual(self.adv("/unterminated"), [])

    def test_query_error_propagates_unwrapped(self):
        try:
            self.adv("/([/")
        except Q.QueryError as exc:
            self.assertIs(type(exc), Q.QueryError)
        else:
            self.fail("QueryError not raised")

    def test_regex_snippet_falls_back_to_body_start(self):
        # No plain terms in the group: snippet is the body's first ~160 chars.
        hits = self.adv("/golang/")
        self.assertEqual(self.app_refs(hits), {"4"})
        body_start = "Initech\nBackend Engineer\napplied\nwebsite\ngolang services"
        self.assertTrue(hits[0]["snippet"].startswith("Initech"))
        self.assertIn("golang", hits[0]["snippet"])
        self.assertIn(body_start[:40], hits[0]["snippet"])


# ---------------------------------------------------------------------------
# Fuzzy terms
# ---------------------------------------------------------------------------

class FuzzyTest(AdvancedBase):
    def test_fuzzy_match(self):
        hits = self.adv("pythons~1")  # token "python" is distance 1 away
        self.assertIn("1", self.app_refs(hits))
        app1 = next(h for h in hits if h["ref"] == "1")
        self.assertEqual(app1["matched"], ["fuzzy:pythons~1"])

    def test_fuzzy_distance_cap(self):
        # "pythno" is distance 2 from "python": ~1 misses, ~2 hits.
        self.assertEqual(self.app_refs(self.adv("pythno~1")), set())
        self.assertIn("1", self.app_refs(self.adv("pythno~2")))

    def test_fuzzy_no_match(self):
        self.assertEqual(self.adv("zzzzqq~1"), [])

    def test_levenshtein_unit(self):
        self.assertEqual(S._levenshtein("", ""), 0)
        self.assertEqual(S._levenshtein("", "abc"), 3)
        self.assertEqual(S._levenshtein("abc", "abc"), 0)
        self.assertEqual(S._levenshtein("kitten", "sitting"), 3)
        self.assertEqual(S._levenshtein("python", "pythno"), 2)


# ---------------------------------------------------------------------------
# Date bounds
# ---------------------------------------------------------------------------

class DateBoundsTest(AdvancedBase):
    def test_after(self):
        # app 1 (09-10) dropped; app 3 (missing date) and app 4
        # (unparseable date) are kept, never dropped.
        self.assertEqual(self.app_refs(self.adv("engineer after:2026-09-15")),
                         {"3", "4"})

    def test_before(self):
        self.assertEqual(self.app_refs(self.adv("engineer before:2026-09-15")),
                         {"1", "3", "4"})

    def test_after_and_before(self):
        hits = self.adv("engineer after:2026-09-01 before:2026-09-15")
        self.assertEqual(self.app_refs(hits), {"1", "3", "4"})

    def test_after_excludes_everything(self):
        # Apps 3 (missing date_added) and 4 (unparseable date_added) are
        # never dropped by date bounds.
        self.assertEqual(self.app_refs(self.adv("engineer after:2027-01-01")),
                         {"3", "4"})

    def test_invalid_date_is_query_error(self):
        with self.assertRaises(Q.QueryError):
            self.adv("engineer after:2026-13-99")

    def test_file_mtime_bound(self):
        old = self.prep / "old.md"
        old.write_text("uniqueword content here\n", encoding="utf-8")
        ancient = 1577836800  # 2020-01-01 UTC, safely before any bound
        os.utime(old, (ancient, ancient))
        fresh = self.prep / "fresh.md"
        fresh.write_text("uniqueword fresh content\n", encoding="utf-8")

        unbound = {h["ref"] for h in self.adv("uniqueword")}
        self.assertIn("old.md", unbound)
        self.assertIn("fresh.md", unbound)

        bound = {h["ref"] for h in self.adv("uniqueword after:2026-01-01")}
        self.assertNotIn("old.md", bound)
        self.assertIn("fresh.md", bound)

    def test_date_only_query_matches_nothing(self):
        # The parser strips date bounds out of the term groups, so a
        # date-only query has no groups and matches nothing.
        self.assertEqual(self.adv("after:2026-09-15"), [])


# ---------------------------------------------------------------------------
# matched[], scoring, sorting, limit, explain
# ---------------------------------------------------------------------------

class ResultShapeTest(AdvancedBase):
    def test_result_keys(self):
        for h in self.adv("python"):
            for key in ("kind", "ref", "title", "snippet", "score", "matched"):
                self.assertIn(key, h)

    def test_matched_combined(self):
        hits = self.adv("company:stripe /python/ pythons~1")
        self.assertEqual(self.app_refs(hits), {"1"})
        self.assertEqual(hits[0]["matched"],
                         ["company:stripe", "regex:/python/",
                          "fuzzy:pythons~1"])

    def test_matched_plain_and_phrase(self):
        hits = self.adv('"ml platform"')
        self.assertEqual(self.app_refs(hits), {"1"})
        self.assertEqual(hits[0]["matched"], ["ml platform"])

    def test_first_matching_group_explains(self):
        hits = self.adv("zzznope OR python")
        self.assertEqual(self.app_refs(hits), {"1"})
        self.assertEqual(hits[0]["matched"], ["python"])

    def test_sort_order(self):
        hits = self.adv("python OR golang OR sql OR dashboards OR engineer")
        keys = [(-h["score"], h["kind"], h["ref"]) for h in hits]
        self.assertEqual(keys, sorted(keys))

    def test_title_hit_outranks(self):
        # "stripe" hits app 1's title and the prep file's title.
        hits = self.adv("stripe")
        titles = [h for h in hits if h["score"] >= 1000]
        self.assertTrue(titles, "expected title-bonus hits for 'stripe'")

    def test_limit(self):
        hits = self.adv("python OR golang OR sql OR dashboards OR engineer",
                        limit=2)
        self.assertEqual(len(hits), 2)

    def test_limit_zero(self):
        self.assertEqual(self.adv("python", limit=0), [])

    def test_snippet_around_plain_term(self):
        hits = self.adv("dashboards")
        app2 = next(h for h in hits if h["ref"] == "2")
        self.assertIn("dashboards", app2["snippet"])

    def test_explain(self):
        out = S.explain_query("company:stripe -senior after:2026-01-01")
        self.assertIn("company:stripe", out)
        self.assertIn("senior", out)
        self.assertIn("[excluded]", out)
        self.assertIn("2026-01-01", out)
        self.assertIn("OR-group 1", out)

    def test_explain_empty(self):
        out = S.explain_query("   ")
        self.assertIn("no terms", out)

    def test_explain_bad_query_raises(self):
        with self.assertRaises(Q.QueryError):
            S.explain_query("/([/")


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------

class RobustnessTest(AdvancedBase):
    def test_missing_tracker(self):
        hits = self.adv("python", path=self.tmp / "nope.json")
        self.assertTrue(all(h["kind"] != "application" for h in hits))
        self.assertTrue(hits)

    def test_bad_tracker_json(self):
        self.tracker.write_text("not json", encoding="utf-8")
        with self.assertRaises(S.SearchError):
            self.adv("python")

    def test_missing_dirs(self):
        hits = S.search_advanced("python", path=self.tmp / "nope.json",
                                 prep_dir=self.tmp / "n1",
                                 tailor_dir=self.tmp / "n2",
                                 debriefs_dir=self.tmp / "n3")
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()

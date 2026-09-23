"""Advanced search query parser for candid.

Parses a query string into a structured :class:`Query`: an OR of AND-groups
of :class:`Term`, plus optional ``after:`` / ``before:`` date bounds.

Informal grammar::

    query     := or_expr
    or_expr   := and_expr ("OR" and_expr)*     # uppercase OR only
    and_expr  := factor+
    factor    := ["NOT" | "-"] (term | "(" or_expr ")")

Term forms:

* ``foo bar``            two plain terms, ANDed
* ``"multi word"``       one phrase term
* ``company:acme``       field-scoped term (see :data:`VALID_FIELDS`;
                         field names are case-insensitive: ``Company:acme``
                         works and normalizes to ``"company"``)
* ``unknown:x``          unknown field: stays a literal term (friendly, no error)
* ``https://...``        URLs contain ":", but "https" is not a valid field,
                         so they stay literal terms too
* ``/pat/`` / ``/pat/i`` regex term, compiled case-insensitively with ``re``
* ``term~`` / ``term~2`` fuzzy term, max edit distance (cap 3)
* ``-term`` / ``NOT term`` negated term
* ``after:YYYY-MM-DD`` / ``before:YYYY-MM-DD`` date bounds (stripped from
  the term groups; they are not terms)

Escaping: a backslash escapes the next character's special meaning, e.g.
``\\(``, ``\\)``, ``\\"``, ``\\-``, ``\\/``, ``\\~``. This is implemented
generally: ``\\X`` is always a literal ``X``.

Decisions worth knowing:

* ``parse("")`` returns ``Query(groups=(), after=None, before=None)``.
* Date bounds are stripped out of the term groups wherever they appear,
  so ``parse("after:2026-01-01")`` has ``groups == ()``. If a bound is
  repeated, the last one wins.
* A dangling ``OR`` (``"a OR"``) or empty ``()`` is ignored rather than an
  error; only unbalanced parens raise :class:`QueryError`.
* ``NOT`` / ``-`` negate a single term only; ``NOT (a b)`` raises
  :class:`QueryError`.
* Term values keep their original case; the matching layer decides how to
  handle case.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

VALID_FIELDS = ("company", "role", "status", "source", "kind", "title",
                "notes", "jd")

_DATE_FIELDS = ("after", "before")

_MAX_FUZZY = 3


class QueryError(Exception):
    """Raised when a search query cannot be parsed."""


@dataclass(frozen=True)
class Term:
    value: str            # literal text or regex pattern
    field: str | None = None  # None, or one of VALID_FIELDS (defaults to None)
    negated: bool = False
    regex: bool = False
    fuzzy: int | None = None   # max edit distance, None = exact
    phrase: bool = False


@dataclass(frozen=True)
class Query:
    groups: tuple[tuple[Term, ...], ...]  # OR of AND-groups
    after: date | None    # from after:YYYY-MM-DD
    before: date | None   # from before:YYYY-MM-DD


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------
#
# Tokens are small tuples; the first element is the kind:
#   ('LPAREN',) ('RPAREN',) ('OR',) ('NOT',)
#   ('WORD', [(char, escaped), ...])
#   ('PHRASE', text)
#   ('REGEX', pattern)

def _scan_phrase(s: str, i: int) -> tuple[str, int]:
    """Scan a quoted phrase starting at s[i] == '"'. Returns (text, next_i)."""
    n = len(s)
    i += 1
    buf: list[str] = []
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            buf.append(s[i + 1])
            i += 2
            continue
        if c == '"':
            return "".join(buf), i + 1
        buf.append(c)
        i += 1
    raise QueryError("unterminated quoted phrase")


def _scan_word(s: str, i: int) -> tuple[list[tuple[str, bool]], int]:
    """Scan a bare word; stops at whitespace, parens, or a quote.

    Returns ([(char, escaped)], next_i). Backslash escapes the next char.
    """
    n = len(s)
    buf: list[tuple[str, bool]] = []
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            buf.append((s[i + 1], True))
            i += 2
            continue
        if c.isspace() or c in '()"':
            break
        if c == "/" and buf == [("-", False)]:
            break  # "-/re/": leave the "/" so it scans as a regex
        buf.append((c, False))
        i += 1
    if not buf and i < n and s[i] == "\\":
        buf.append(("\\", False))  # trailing lone backslash: literal
        i += 1
    return buf, i


def _scan_regex(s: str, i: int) -> tuple[tuple, int]:
    """Scan a /pattern/ or /pattern/i token starting at s[i] == '/'.

    Falls back to a literal WORD when there is no closing slash or when
    junk follows the closing slash (e.g. "/p/x"); raises QueryError when
    the pattern does not compile.
    """
    n = len(s)
    buf: list[str] = []
    j = i + 1
    closed = False
    while j < n:
        c = s[j]
        if c == "\\" and j + 1 < n:
            buf.append(c)
            buf.append(s[j + 1])
            j += 2
            continue
        if c == "/":
            closed = True
            break
        buf.append(c)
        j += 1
    if not closed:
        word, k = _scan_word(s, i)
        return ("WORD", word), k
    j += 1  # past the closing slash
    if j < n and s[j] == "i" and (j + 1 >= n or s[j + 1].isspace()
                                  or s[j + 1] in '()"'):
        j += 1  # trailing 'i' accepted; matching is case-insensitive anyway
    elif j < n and not (s[j].isspace() or s[j] in '()"'):
        word, k = _scan_word(s, i)  # e.g. "/p/x": treat as literal
        return ("WORD", word), k
    pattern = "".join(buf)
    try:
        re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise QueryError(f"invalid regex /{pattern}/: {exc}") from exc
    return ("REGEX", pattern), j


def _tokenize(s: str) -> list[tuple]:
    toks: list[tuple] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c.isspace():
            i += 1
            continue
        if c == "(":
            toks.append(("LPAREN",))
            i += 1
            continue
        if c == ")":
            toks.append(("RPAREN",))
            i += 1
            continue
        if c == '"':
            text, i = _scan_phrase(s, i)
            toks.append(("PHRASE", text))
            if i < n and s[i] == "~":
                raise QueryError("fuzzy '~' cannot be applied to a quoted phrase")
            continue
        if c == "/":
            tok, i = _scan_regex(s, i)
            toks.append(tok)
            if tok[0] == "REGEX" and i < n and s[i] == "~":
                raise QueryError("fuzzy '~' cannot be applied to a regex")
            continue
        buf, i = _scan_word(s, i)
        # Bare uppercase OR / NOT (nothing escaped) are operators.
        if not any(escaped for _, escaped in buf):
            raw = "".join(c for c, _ in buf)
            if raw == "OR":
                toks.append(("OR",))
                continue
            if raw == "NOT":
                toks.append(("NOT",))
                continue
        # A lone "-" glued to a phrase or regex negates it: -"a b", -/p/
        if len(buf) == 1 and buf[0] == ("-", False) and i < n and s[i] in '"/':
            toks.append(("NOT",))
            continue
        toks.append(("WORD", buf))
    return toks


# ---------------------------------------------------------------------------
# Term classification
# ---------------------------------------------------------------------------

def _parse_date(name: str, text: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text or ""):
        raise QueryError(f"'{name}:' date must be YYYY-MM-DD, got {text!r}")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise QueryError(f"'{name}:' is not a real calendar date: {text!r}") from None


def _word_term(buf: list[tuple[str, bool]], negated: bool) -> tuple:
    """Classify a WORD token.

    Returns ('TERM', Term) or ('DATE', 'after'|'before', date).
    """
    rest = list(buf)
    if len(rest) > 1 and rest[0] == ("-", False):
        negated = True
        rest = rest[1:]
    # Fuzzy suffix: unescaped "~" then unescaped digits, at the end.
    fuzzy: int | None = None
    k = len(rest)
    while k > 0 and rest[k - 1][0].isdigit() and not rest[k - 1][1]:
        k -= 1
    if k > 0 and rest[k - 1] == ("~", False):
        digits = "".join(c for c, _ in rest[k:])
        dist = int(digits) if digits else 1
        if dist > _MAX_FUZZY:
            raise QueryError(f"fuzzy distance {dist} exceeds the max of {_MAX_FUZZY}")
        fuzzy = dist
        rest = rest[:k - 1]
    if not rest:
        raise QueryError("fuzzy '~' must follow a term")
    # Field split on the first unescaped ":".
    colon = next((idx for idx, (c, e) in enumerate(rest)
                  if c == ":" and not e), None)
    if colon is not None:
        name = "".join(c for c, _ in rest[:colon]).lower()
        val = "".join(c for c, _ in rest[colon + 1:])
        if name in _DATE_FIELDS:
            if negated:
                raise QueryError(f"'{name}:' date bound cannot be negated")
            if fuzzy is not None:
                raise QueryError(f"fuzzy '~' cannot be combined with '{name}:'")
            return ("DATE", name, _parse_date(name, val))
        if name in VALID_FIELDS:
            return ("TERM", Term(value=val, field=name, negated=negated,
                                  fuzzy=fuzzy))
        # Unknown field: the whole word stays a literal term (no error).
    text = "".join(c for c, _ in rest)
    return ("TERM", Term(value=text, field=None, negated=negated, fuzzy=fuzzy))


# ---------------------------------------------------------------------------
# Parser: builds DNF (list of AND-groups) plus date bounds
# ---------------------------------------------------------------------------

_FACTOR_START = ("WORD", "PHRASE", "REGEX")


def _parse_factor(toks: list[tuple], i: int, negated: bool,
                  depth: int) -> tuple[tuple, date | None, date | None, int]:
    """Parse one factor. Returns ((kind, payload), after, before, next_i)."""
    kind = toks[i][0]
    if kind == "LPAREN":
        if negated:
            raise QueryError("'NOT' cannot negate a parenthesized group; "
                             "negate individual terms instead")
        dnf, after, before, i = _parse_seq(toks, i + 1, depth + 1)
        return ("GROUPS", dnf), after, before, i
    if kind == "PHRASE":
        term = Term(value=toks[i][1], phrase=True, negated=negated)
        return ("TERM", term), None, None, i + 1
    if kind == "REGEX":
        term = Term(value=toks[i][1], regex=True, negated=negated)
        return ("TERM", term), None, None, i + 1
    if kind == "WORD":
        res = _word_term(toks[i][1], negated)
        if res[0] == "DATE":
            _, name, d = res
            after = d if name == "after" else None
            before = d if name == "before" else None
            return ("DATE", res), after, before, i + 1
        # `field:"quoted phrase"`: attach a following phrase to an empty
        # field value, so the phrase is scoped to the field.
        _, term = res
        if (term.field is not None and term.value == ""
                and i + 1 < len(toks) and toks[i + 1][0] == "PHRASE"):
            term = Term(value=toks[i + 1][1], field=term.field,
                        negated=term.negated, fuzzy=term.fuzzy, phrase=True)
            return ("TERM", term), None, None, i + 2
        return res, None, None, i + 1
    raise QueryError(f"unexpected {kind} while parsing query")


def _parse_seq(toks: list[tuple], i: int,
               depth: int) -> tuple[list[list[Term]], date | None,
                                    date | None, int]:
    """Parse an AND-sequence (OR-separated at this level).

    Returns (dnf, after, before, next_i). ``done`` holds groups closed by
    OR; ``pending`` holds the group(s) still being built. ANDing a
    parenthesized group cross-products it into ``pending``.
    """
    done: list[list[Term]] = []
    pending: list[list[Term]] = [[]]
    after: date | None = None
    before: date | None = None
    n = len(toks)
    while i < n:
        kind = toks[i][0]
        if kind == "RPAREN":
            if depth == 0:
                raise QueryError("unbalanced ')'")
            done.extend(pending)
            return done, after, before, i + 1
        if kind == "OR":
            done.extend(pending)
            pending = [[]]
            i += 1
            continue
        if kind == "NOT":
            if i + 1 >= n or toks[i + 1][0] not in _FACTOR_START:
                raise QueryError("'NOT' must be followed by a term")
            (fk, payload), ia, ib, i = _parse_factor(toks, i + 1, True, depth)
            if fk != "TERM":
                raise QueryError("'NOT' must be followed by a term")
            for group in pending:
                group.append(payload)
            continue
        (fk, payload), ia, ib, i = _parse_factor(toks, i, False, depth)
        if ia is not None:
            after = ia
        if ib is not None:
            before = ib
        if fk == "TERM":
            for group in pending:
                group.append(payload)
        elif fk == "GROUPS":
            pending = [p + h for p in pending for h in payload]
        # DATE factors contribute only the bound; nothing is appended.
    if depth > 0:
        raise QueryError("unbalanced '('")
    done.extend(pending)
    return done, after, before, i


def parse(query: str) -> Query:
    """Parse an advanced search query string into a :class:`Query`.

    ``parse("")`` returns ``Query(groups=(), after=None, before=None)``.
    Raises :class:`QueryError` on unbalanced parens, invalid regex,
    bad fuzzy syntax, malformed dates, and other syntax problems.
    """
    if not isinstance(query, str):
        raise TypeError(f"query must be a string, got {type(query).__name__}")
    toks = _tokenize(query)
    dnf, after, before, _ = _parse_seq(toks, 0, 0)
    groups = tuple(tuple(group) for group in dnf if group)
    return Query(groups=groups, after=after, before=before)

"""Hermetic unit tests for candid.query (advanced search operators).

Pure parsing only: no filesystem, no network, no fixtures.
"""

from datetime import date

import pytest

from candid.query import Query, QueryError, Term, VALID_FIELDS, parse


def terms_of(group):
    return list(group)


# ---------------------------------------------------------------------------
# Basics: AND / OR / NOT
# ---------------------------------------------------------------------------

def test_and_of_two_words():
    q = parse("foo bar")
    assert q.groups == ((Term(value="foo"), Term(value="bar")),)
    assert q.after is None and q.before is None


def test_single_term():
    q = parse("python")
    assert q.groups == ((Term(value="python"),),)


def test_or_splits_groups():
    q = parse("a OR b")
    assert q.groups == ((Term(value="a"),), (Term(value="b"),))


def test_or_chains():
    q = parse("a OR b OR c")
    assert len(q.groups) == 3
    assert [g[0].value for g in q.groups] == ["a", "b", "c"]


def test_lowercase_or_is_literal():
    q = parse("a or b")
    assert q.groups == ((Term(value="a"), Term(value="or"), Term(value="b")),)


def test_dangling_or_is_ignored():
    q = parse("a OR")
    assert q.groups == ((Term(value="a"),),)


def test_dash_negation():
    q = parse("-term")
    (group,) = q.groups
    assert group == (Term(value="term", negated=True),)


def test_not_negation():
    q = parse("NOT term")
    (group,) = q.groups
    assert group == (Term(value="term", negated=True),)


def test_lowercase_not_is_literal():
    q = parse("not term")
    assert q.groups == ((Term(value="not"), Term(value="term")),)


def test_dangling_not_raises():
    with pytest.raises(QueryError):
        parse("a NOT")


def test_not_before_paren_raises():
    with pytest.raises(QueryError):
        parse("NOT (a b)")


def test_not_not_raises():
    with pytest.raises(QueryError):
        parse("NOT NOT a")


def test_mixed_and_or_not():
    q = parse("a -b OR c NOT d")
    assert q.groups == (
        (Term(value="a"), Term(value="b", negated=True)),
        (Term(value="c"), Term(value="d", negated=True)),
    )


# ---------------------------------------------------------------------------
# Parentheses
# ---------------------------------------------------------------------------

def test_paren_group_anded_with_term():
    q = parse("(a OR b) c")
    assert q.groups == (
        (Term(value="a"), Term(value="c")),
        (Term(value="b"), Term(value="c")),
    )


def test_paren_cross_product():
    q = parse("(a OR b) (c OR d)")
    assert q.groups == (
        (Term(value="a"), Term(value="c")),
        (Term(value="a"), Term(value="d")),
        (Term(value="b"), Term(value="c")),
        (Term(value="b"), Term(value="d")),
    )


def test_nested_parens():
    q = parse("((a OR b) c)")
    assert q.groups == (
        (Term(value="a"), Term(value="c")),
        (Term(value="b"), Term(value="c")),
    )


def test_unbalanced_open_raises():
    with pytest.raises(QueryError):
        parse("(a b")


def test_unbalanced_close_raises():
    with pytest.raises(QueryError):
        parse("a b)")


def test_deeply_unbalanced_raises():
    with pytest.raises(QueryError):
        parse("((a)")


def test_empty_parens_ignored():
    q = parse("() a")
    assert q.groups == ((Term(value="a"),),)


def test_not_inside_parens():
    q = parse("(a NOT b)")
    assert q.groups == ((Term(value="a"), Term(value="b", negated=True)),)


# ---------------------------------------------------------------------------
# Phrases
# ---------------------------------------------------------------------------

def test_phrase_is_single_term():
    q = parse('"multi word"')
    assert q.groups == ((Term(value="multi word", phrase=True),),)


def test_phrase_mixed_with_words():
    q = parse('python "machine learning"')
    assert q.groups == (
        (Term(value="python"), Term(value="machine learning", phrase=True)),
    )


def test_negated_phrase():
    q = parse('-"multi word"')
    assert q.groups == ((Term(value="multi word", phrase=True, negated=True),),)


def test_not_phrase():
    q = parse('NOT "multi word"')
    assert q.groups == ((Term(value="multi word", phrase=True, negated=True),),)


def test_unterminated_phrase_raises():
    with pytest.raises(QueryError):
        parse('"oops')


def test_phrase_with_escaped_quote():
    q = parse(r'"say \"hi\""')
    assert q.groups == ((Term(value='say "hi"', phrase=True),),)


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------

def test_every_valid_field():
    for field in VALID_FIELDS:
        q = parse(f"{field}:x")
        assert q.groups == ((Term(value="x", field=field),),), field


def test_negated_field():
    q = parse("-company:acme")
    assert q.groups == ((Term(value="acme", field="company", negated=True),),)


def test_not_field():
    q = parse("NOT role:engineer")
    assert q.groups == ((Term(value="engineer", field="role", negated=True),),)


def test_unknown_field_stays_literal():
    q = parse("bogus:value")
    assert q.groups == ((Term(value="bogus:value", field=None),),)


def test_url_stays_literal():
    q = parse("https://example.com/jobs")
    assert q.groups == ((Term(value="https://example.com/jobs", field=None),),)


def test_field_value_with_url():
    q = parse("notes:https://example.com")
    assert q.groups == (
        (Term(value="https://example.com", field="notes"),),
    )


def test_escaped_colon_stays_literal():
    q = parse(r"company\:acme")
    assert q.groups == ((Term(value="company:acme", field=None),),)


def test_field_anded_with_words():
    q = parse("company:acme engineer")
    assert q.groups == (
        (Term(value="acme", field="company"), Term(value="engineer")),
    )


# ---------------------------------------------------------------------------
# Regex
# ---------------------------------------------------------------------------

def test_regex_term():
    q = parse(r"/py(th)?on/")
    (group,) = q.groups
    assert group == (Term(value=r"py(th)?on", regex=True),)


def test_regex_trailing_i():
    q = parse("/abc/i")
    (group,) = q.groups
    assert group == (Term(value="abc", regex=True),)


def test_regex_with_escaped_slash():
    q = parse(r"/a\/b/")
    (group,) = q.groups
    assert group == (Term(value=r"a\/b", regex=True),)


def test_negated_regex():
    q = parse("-/foo/")
    (group,) = q.groups
    assert group == (Term(value="foo", regex=True, negated=True),)


def test_invalid_regex_raises():
    with pytest.raises(QueryError):
        parse("/([/")


def test_unterminated_regex_is_literal():
    q = parse("/usr/bin")
    assert q.groups == ((Term(value="/usr/bin"),),)


def test_regex_with_junk_suffix_is_literal():
    q = parse("/p/x")
    assert q.groups == ((Term(value="/p/x"),),)


# ---------------------------------------------------------------------------
# Fuzzy
# ---------------------------------------------------------------------------

def test_fuzzy_default_distance():
    q = parse("term~")
    assert q.groups == ((Term(value="term", fuzzy=1),),)


def test_fuzzy_explicit_distance():
    q = parse("term~2")
    assert q.groups == ((Term(value="term", fuzzy=2),),)


def test_fuzzy_max_distance():
    q = parse("term~3")
    assert q.groups == ((Term(value="term", fuzzy=3),),)


def test_fuzzy_above_cap_raises():
    with pytest.raises(QueryError):
        parse("term~4")


def test_fuzzy_on_phrase_raises():
    with pytest.raises(QueryError):
        parse('"multi word"~')


def test_fuzzy_on_field_value():
    q = parse("role:dev~")
    assert q.groups == ((Term(value="dev", field="role", fuzzy=1),),)


def test_dangling_tilde_raises():
    with pytest.raises(QueryError):
        parse("~2")


def test_escaped_tilde_is_literal():
    q = parse(r"a\~")
    assert q.groups == ((Term(value="a~"),),)


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

def test_after_date():
    q = parse("after:2026-08-01")
    assert q.after == date(2026, 8, 1)
    assert q.before is None
    assert q.groups == ()


def test_before_date():
    q = parse("before:2026-09-01")
    assert q.before == date(2026, 9, 1)
    assert q.after is None


def test_dates_stripped_from_groups():
    q = parse("python after:2026-08-01 before:2026-09-01")
    assert q.groups == ((Term(value="python"),),)
    assert q.after == date(2026, 8, 1)
    assert q.before == date(2026, 9, 1)


def test_date_inside_parens():
    q = parse("(a OR b) after:2026-01-15")
    assert q.after == date(2026, 1, 15)
    assert q.groups == (
        (Term(value="a"),),
        (Term(value="b"),),
    )


def test_malformed_date_raises():
    for bad in ("after:2026-8-1", "after:08-01-2026", "after:tomorrow",
                "before:2026/09/01", "after:"):
        with pytest.raises(QueryError):
            parse(bad)


def test_impossible_date_raises():
    with pytest.raises(QueryError):
        parse("after:2026-13-40")


def test_negated_date_raises():
    with pytest.raises(QueryError):
        parse("-after:2026-01-01")
    with pytest.raises(QueryError):
        parse("NOT before:2026-01-01")


def test_repeated_date_last_wins():
    q = parse("after:2026-01-01 after:2026-02-01")
    assert q.after == date(2026, 2, 1)


# ---------------------------------------------------------------------------
# Escapes
# ---------------------------------------------------------------------------

def test_escaped_parens_literal():
    q = parse(r"\(a b\)")
    assert q.groups == (
        (Term(value="(a"), Term(value="b)")),
    )


def test_escaped_dash_literal():
    q = parse(r"\-term")
    assert q.groups == ((Term(value="-term", negated=False),),)


def test_escaped_quote_literal():
    q = parse(r'\"quoted\"')
    assert q.groups == ((Term(value='"quoted"'),),)


def test_escaped_slashes_literal():
    q = parse(r"\/not-a-regex\/")
    assert q.groups == ((Term(value="/not-a-regex/"),),)


def test_escaped_space_is_literal():
    q = parse(r"a\ b")
    assert q.groups == ((Term(value="a b"),),)


# ---------------------------------------------------------------------------
# Empty query and error surface
# ---------------------------------------------------------------------------

def test_empty_query():
    q = parse("")
    assert isinstance(q, Query)
    assert q.groups == ()
    assert q.after is None
    assert q.before is None


def test_whitespace_only_query():
    q = parse("   ")
    assert q.groups == ()


def test_non_string_raises():
    with pytest.raises(TypeError):
        parse(None)


def test_query_error_is_exception():
    assert issubclass(QueryError, Exception)


def test_term_defaults():
    t = Term(value="x")
    assert t.field is None
    assert t.negated is False
    assert t.regex is False
    assert t.fuzzy is None
    assert t.phrase is False


# ---------------------------------------------------------------------------
# Combined real-world queries
# ---------------------------------------------------------------------------

def test_kitchen_sink():
    q = parse('company:acme (engineer OR developer) -senior '
              '"machine learning" after:2026-01-01')
    assert q.after == date(2026, 1, 1)
    assert q.before is None
    assert q.groups == (
        (Term(value="acme", field="company"),
         Term(value="engineer"),
         Term(value="senior", negated=True),
         Term(value="machine learning", phrase=True)),
        (Term(value="acme", field="company"),
         Term(value="developer"),
         Term(value="senior", negated=True),
         Term(value="machine learning", phrase=True)),
    )


def test_regex_or_phrase_or_field():
    q = parse('/^sr/ OR "staff engineer" OR status:open')
    assert q.groups == (
        (Term(value="^sr", regex=True),),
        (Term(value="staff engineer", phrase=True),),
        (Term(value="open", field="status"),),
    )


def test_values_keep_original_case():
    q = parse("Company:AcMe PyThon")
    assert q.groups == (
        (Term(value="AcMe", field="company"), Term(value="PyThon")),
    )

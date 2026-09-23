"""Tests for candid.docs_search — synthetic in-memory topics only."""

import pytest

from candid.docs_search import build_index, search


@pytest.fixture()
def topics():
    return {
        "intro": (
            "# Getting started\n\n"
            "Candid is a job-search copilot. Onboard your resume first, "
            "then tailor it for each application."
        ),
        "tracker": (
            "# Application tracker\n\n"
            "The tracker stores every application. Add an application with "
            "track add, list them with track list, update statuses as you go. "
            "The tracker keeps your pipeline visible."
        ),
        "salary": (
            "# Salary intelligence\n\n"
            "Look up pay ranges with salary lookup. The salary database "
            "stores posted ranges and H-1B LCA disclosures."
        ),
    }


@pytest.fixture()
def titles():
    return {"intro": "Getting started",
            "tracker": "Application tracker",
            "salary": "Salary intelligence"}


def test_and_semantics(topics, titles):
    idx = build_index(topics)
    slugs = [s for s, _, _ in search("tracker application", idx, titles)]
    assert slugs == ["tracker"]


def test_and_semantics_no_common_term(topics, titles):
    idx = build_index(topics)
    assert search("tracker salary", idx, titles) == []


def test_title_matches_rank_first():
    # "tracker" appears 4x in the body of "deep" but only in the title of "hub".
    topics = {
        "deep": "tracker tracker tracker tracker. other words here.",
        "hub": "a page mentioning tracker once in the body.",
    }
    titles = {"deep": "Deep dive", "hub": "Tracker hub"}
    idx = build_index(topics)
    results = search("tracker", idx, titles)
    assert [s for s, _, _ in results] == ["hub", "deep"]


def test_term_frequency_orders_body_matches():
    topics = {
        "low": "match word once, nothing else.",
        "high": "match match match. the word match appears more here: match.",
    }
    titles = {"low": "Low", "high": "High"}
    idx = build_index(topics)
    results = search("match", idx, titles)
    assert [s for s, _, _ in results] == ["high", "low"]


def test_quoted_phrase_matched_literally():
    topics = {
        "ordered": "the quick brown fox jumps",
        "shuffled": "the brown quick fox jumps",
    }
    titles = {"ordered": "Ordered", "shuffled": "Shuffled"}
    idx = build_index(topics)
    assert [s for s, _, _ in search('"quick brown"', idx, titles)] == ["ordered"]
    # without quotes both docs match (AND on the two tokens)
    assert sorted(s for s, _, _ in search("quick brown", idx, titles)) == \
        ["ordered", "shuffled"]


def test_phrase_and_term_combine():
    topics = {
        "a": "thank you email after the interview",
        "b": "thank you note with no other detail",
    }
    titles = {"a": "A", "b": "B"}
    idx = build_index(topics)
    assert [s for s, _, _ in search('interview "thank you"', idx, titles)] == ["a"]


def test_snippet_around_first_hit_with_ellipsis():
    filler = "lorem ipsum dolor sit amet " * 20
    topics = {"long": filler + "TARGETKEYWORD " + filler}
    titles = {"long": "Long doc"}
    idx = build_index(topics)
    [(slug, title, snippet)] = search("targetkeyword", idx, titles)
    assert slug == "long" and title == "Long doc"
    assert "TARGETKEYWORD" in snippet
    assert snippet.startswith("...") and snippet.endswith("...")
    assert len(snippet) <= 170  # ~160 chars plus two ellipses


def test_snippet_short_doc_no_ellipsis():
    topics = {"s": "short doc about onboarding"}
    idx = build_index(topics)
    [(_, _, snippet)] = search("onboarding", idx, {"s": "S"})
    assert snippet == "short doc about onboarding"


def test_empty_query_returns_nothing(topics, titles):
    idx = build_index(topics)
    assert search("", idx, titles) == []
    assert search("   ", idx, titles) == []


def test_missing_title_falls_back_to_slug(topics):
    idx = build_index(topics)
    [(slug, title, _)] = search("salary", idx, {})
    assert (slug, title) == ("salary", "salary")


def test_index_is_token_postings(topics):
    idx = build_index(topics)
    assert idx["postings"]["tracker"]["tracker"] == 3
    assert "intro" not in idx["postings"]["tracker"]


def test_module_imports_without_docs_bundle():
    # docs_search must never import candid.docs_bundle at module level.
    # (Checked via AST: in the integrated suite the bundle legitimately
    # exists in sys.modules, so we do not assert on sys.modules here.)
    import ast
    import candid.docs_search as mod
    source = open(mod.__file__, encoding="utf-8").read()
    tree = ast.parse(source)

    def _names(node):
        names = [a.name for a in node.names]
        if isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
        return names

    for stmt in tree.body:  # module-level statements only
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            assert not any("docs_bundle" in n for n in _names(stmt)), \
                f"top-level docs_bundle import found: {_names(stmt)}"
    # and the deferred import really is deferred: it lives in a function
    found_deferred = any(
        isinstance(node, (ast.Import, ast.ImportFrom))
        and any("docs_bundle" in n for n in _names(node))
        for func in ast.walk(tree) if isinstance(func, ast.FunctionDef)
        for node in ast.walk(func)
    )
    assert found_deferred, "expected a deferred docs_bundle import inside a function"

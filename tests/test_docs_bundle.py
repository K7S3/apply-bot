"""Tests for the offline docs bundle (candid/docs_bundle.py).

Stdlib only; no network access.
"""

import re

import pytest

import candid
from candid import docs_bundle
from candid.docs_bundle import (
    DOCS_DIR,
    DocsError,
    docs_version,
    get_topic,
    list_topics,
    render_text,
)

EXPECTED_SLUGS = [
    "dashboard",
    "faq",
    "followup",
    "glossary",
    "imports",
    "jobs",
    "matching",
    "mock",
    "negotiate",
    "offers",
    "onboarding",
    "prep",
    "salary",
    "tailoring",
    "tracking",
    "tutorial",
]


def test_docs_dir_exists():
    assert DOCS_DIR.is_dir()
    assert DOCS_DIR.name == "docs"


def test_list_topics_covers_all_expected_slugs():
    topics = list_topics()
    assert isinstance(topics, list)
    slugs = [s for s, _ in topics]
    assert slugs == sorted(slugs), "topics should be sorted by slug"
    assert slugs == EXPECTED_SLUGS


def test_list_topics_titles_from_headings():
    by_slug = dict(list_topics())
    assert by_slug["onboarding"] == "Onboarding: build your profile"
    assert by_slug["tutorial"] == "Tutorial: end-to-end walkthrough"
    for slug, title in by_slug.items():
        assert title, f"empty title for {slug}"


def test_list_topics_title_fallback_to_filename(tmp_path, monkeypatch):
    (tmp_path / "noheading.md").write_text(
        "Just some text, no heading.\n", encoding="utf-8"
    )
    (tmp_path / "withheading.md").write_text(
        "# Real Title\n\nBody.\n", encoding="utf-8"
    )
    monkeypatch.setattr(docs_bundle, "DOCS_DIR", tmp_path)
    by_slug = dict(list_topics())
    assert by_slug["noheading"] == "Noheading"
    assert by_slug["withheading"] == "Real Title"


def test_get_topic_returns_markdown():
    text = get_topic("matching")
    assert "# Matching" in text
    assert "python -m candid match" in text


def test_get_topic_all_topics_nonempty():
    for slug, _ in list_topics():
        assert get_topic(slug).strip(), f"empty topic {slug}"


def test_get_topic_unknown_slug_raises_docs_error():
    with pytest.raises(DocsError):
        get_topic("no-such-topic")


def test_get_topic_path_traversal_raises_docs_error():
    with pytest.raises(DocsError):
        get_topic("../__main__")
    with pytest.raises(DocsError):
        get_topic("sub/dir")


def test_docs_error_is_exception():
    assert issubclass(DocsError, Exception)


def test_docs_version_value():
    assert docs_version() == "0.3.0"


def test_docs_version_matches_package_version():
    # The coordinator aligns candid.__version__ to 0.3.0 at integration.
    assert docs_version() == candid.__version__


def test_render_text_strips_markdown():
    md = "# Title\n\nSome **bold** and *italic* and `code`.\n\n- item one\n- item two\n"
    text = render_text(md)
    assert "#" not in text
    assert "**" not in text
    assert "`" not in text
    assert "Title" in text
    assert "bold" in text and "italic" in text and "code" in text
    assert "item one" in text


def test_render_text_keeps_link_text():
    md = "See the [matching](matching.md) topic for details."
    text = render_text(md)
    assert "matching" in text
    assert "matching.md" not in text
    assert "[" not in text and "]" not in text


def test_render_text_drops_table_separators():
    md = "| a | b |\n| --- | --- |\n| 1 | 2 |\n"
    text = render_text(md)
    assert "---" not in text
    assert "1" in text and "2" in text


def test_render_text_real_topic():
    text = render_text(get_topic("glossary"))
    assert "Profile" in text
    assert not re.search(r"^#", text, re.M)
    assert "**" not in text

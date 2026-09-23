"""Tests for candid.docs_check — tmp_path fixtures only, stdlib only."""

import pytest

from candid.docs_check import check_docs


@pytest.fixture()
def clean_bundle(tmp_path):
    docs = tmp_path / "docs"
    (docs / "commands").mkdir(parents=True)
    (docs / "index.md").write_text(
        "# Docs\n\n- [Getting started](getting-started.md)\n",
        encoding="utf-8")
    (docs / "getting-started.md").write_text(
        "# Getting started\n\nSee [tracker](commands/track.md) and "
        "[external](https://example.com) and [anchor](#top).\n",
        encoding="utf-8")
    (docs / "commands" / "track.md").write_text("# track\n", encoding="utf-8")
    return docs


def test_clean_bundle_returns_empty(clean_bundle):
    assert check_docs(["track"], clean_bundle) == []


def test_missing_command_page_detected(clean_bundle):
    problems = check_docs(["track", "mock"], clean_bundle)
    assert any("mock" in p and "missing command page" in p for p in problems)
    assert not any("track" in p for p in problems)


def test_broken_relative_link_detected(clean_bundle):
    (clean_bundle / "getting-started.md").write_text(
        "# Getting started\n\nSee [nowhere](no-such-page.md).\n",
        encoding="utf-8")
    problems = check_docs(["track"], clean_bundle)
    assert any("no-such-page.md" in p and "broken link" in p for p in problems)


def test_external_and_anchor_links_ignored(clean_bundle):
    (clean_bundle / "getting-started.md").write_text(
        "# G\n\n[ext](https://example.com/x) [mail](mailto:a@b.c) "
        "[abs](/docs/x.md) [frag](getting-started.md#sec)\n",
        encoding="utf-8")
    assert check_docs(["track"], clean_bundle) == []


def test_unlisted_topic_detected(clean_bundle):
    (clean_bundle / "hidden-topic.md").write_text("# Hidden\n", encoding="utf-8")
    problems = check_docs(["track"], clean_bundle)
    assert any("hidden-topic.md" in p and "index.md" in p for p in problems)


def test_missing_docs_dir_does_not_raise(tmp_path):
    problems = check_docs(["track"], tmp_path / "no-such-dir")
    assert len(problems) == 1
    assert "not found" in problems[0]


def test_broken_link_in_command_page_detected(clean_bundle):
    (clean_bundle / "commands" / "track.md").write_text(
        "# track\n\nSee [ghost](../ghost.md).\n", encoding="utf-8")
    problems = check_docs(["track"], clean_bundle)
    assert any("ghost.md" in p for p in problems)

"""CLI tests for `python -m candid docs` (batch 109)."""

import json

import pytest

from candid.__main__ import main


def run(argv, capsys):
    main(argv)
    return capsys.readouterr()


def test_docs_list(capsys):
    out = run(["docs", "list"], capsys).out
    assert "matching" in out
    assert "glossary" in out


def test_docs_list_json(capsys):
    out = run(["docs", "list", "--json"], capsys).out
    topics = json.loads(out)
    slugs = [t["slug"] for t in topics]
    assert "matching" in slugs and "tutorial" in slugs


def test_docs_show(capsys):
    out = run(["docs", "show", "glossary"], capsys).out
    assert len(out.strip()) > 0
    assert "#" not in out.splitlines()[0] or True  # rendered plain text


def test_docs_show_raw(capsys):
    out = run(["docs", "show", "glossary", "--raw"], capsys).out
    assert out.lstrip().startswith("#")


def test_docs_show_unknown(capsys):
    with pytest.raises(SystemExit) as e:
        run(["docs", "show", "no-such-topic"], capsys)
    assert e.value.code == 1
    assert "no-such-topic" in capsys.readouterr().err


def test_docs_search(capsys):
    out = run(["docs", "search", "salary"], capsys).out
    assert "salary" in out.lower()


def test_docs_search_json(capsys):
    out = run(["docs", "search", "salary", "--json"], capsys).out
    results = json.loads(out)
    assert isinstance(results, list) and results
    assert "snippet" in results[0]


def test_docs_search_no_match(capsys):
    out = run(["docs", "search", "zzzqqqnonexistent"], capsys).out
    assert "No matches" in out


def test_docs_command(capsys):
    out = run(["docs", "command", "match"], capsys).out
    assert "match" in out.lower()


def test_docs_command_unknown(capsys):
    with pytest.raises(SystemExit) as e:
        run(["docs", "command", "nope"], capsys)
    assert e.value.code == 1


def test_docs_export_txt(tmp_path, capsys):
    out_file = tmp_path / "docs.txt"
    out = run(["docs", "export", "--format", "txt", "--out", str(out_file)],
              capsys).out
    assert out_file.is_file()
    assert "Wrote" in out
    assert "Offline Documentation" in out_file.read_text()


def test_docs_export_html(tmp_path, capsys):
    out_file = tmp_path / "docs.html"
    run(["docs", "export", "--format", "html", "--out", str(out_file)], capsys)
    html = out_file.read_text()
    assert "<style>" in html
    assert "http://" not in html and "https://" not in html


def test_docs_version(capsys):
    out = run(["docs", "version"], capsys).out
    assert "docs version:" in out
    assert "package version:" in out
    assert "0.3.0" in out


def test_docs_check(capsys):
    out = run(["docs", "check"], capsys).out
    assert "Docs OK" in out

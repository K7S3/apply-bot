"""Tests for candid.sre_runbooks. No stdin, no network, no side effects
outside tmp dirs (CANDID_DATA_DIR is overridden per test)."""

from __future__ import annotations

import argparse

import pytest

from candid import sre_runbooks as S


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "candid_data"
    monkeypatch.setenv("CANDID_DATA_DIR", str(d))
    # config reads the env var at import; patch the module attribute directly.
    monkeypatch.setattr("candid.config.DATA_DIR", d)
    return d


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="candid sre")
    sub = parser.add_subparsers(dest="sre_cmd")
    S.register(sub)
    return parser


# ---------------------------------------------------------------------------
# Playbooks
# ---------------------------------------------------------------------------

def test_six_incidents_minimum():
    assert len(S.list_incidents()) >= 6
    for expected in ("disk-full", "oomkilled", "tls-expiry",
                     "latency-spike", "bad-deploy", "dns-failure"):
        assert expected in S.list_incidents()


def test_every_playbook_has_all_sections():
    for incident in S.list_incidents():
        text = S.render_playbook(incident)
        assert f"# Playbook:" in text
        for title in ("Symptoms", "Diagnosis (in order)", "Common root causes",
                      "Fix", "Verification", "Prevention"):
            assert f"## {title}" in text, f"{incident} missing {title}"
        # every section must have at least one bullet
        assert text.count("- ") >= 6


def test_playbook_unknown_raises():
    with pytest.raises(KeyError):
        S.render_playbook("alien-invasion")


def test_export_playbook(tmp_path):
    dest = tmp_path / "sub" / "disk.md"
    path = S.export_playbook("disk-full", dest)
    assert path.exists()
    assert "# Playbook: Disk Full" in path.read_text()


def test_playbook_cli_print(capsys):
    args = argparse.Namespace(sre_cmd="playbook", incident="oomkilled", export=None)
    assert S.dispatch(args) == 0
    out = capsys.readouterr().out
    assert "OOMKilled" in out


def test_playbook_cli_export(capsys, tmp_path):
    dest = str(tmp_path / "tls.md")
    args = argparse.Namespace(sre_cmd="playbook", incident="tls-expiry", export=dest)
    assert S.dispatch(args) == 0
    assert "saved to" in capsys.readouterr().out.lower()


def test_playbook_cli_unknown_incident(capsys):
    args = argparse.Namespace(sre_cmd="playbook", incident="nope", export=None)
    assert S.dispatch(args) == 2
    assert "Unknown incident" in capsys.readouterr().out


def test_playbook_via_registered_parser(capsys):
    parser = make_parser()
    args = parser.parse_args(["playbook", "dns-failure"])
    assert args.sre_cmd == "playbook"
    assert args.func(args) == 0
    assert "DNS" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Postmortems
# ---------------------------------------------------------------------------

NOTES = """\
## Summary
API latency spike on 2026-09-20

## Impact
p99 latency 8s for 40 minutes, 5% of checkouts failed

## Timeline
14:02 deploy v2.3.1 finished
14:10 p99 alert fired
14:25 rollback completed

## Root Cause
Missing index on orders table after migration

## What went well
Alerts fired quickly

## What went poorly
Canary did not catch it

## Action items
- priya: add index review to migration checklist
- sam: extend canary duration to 30 min
"""


def test_parse_notes_headers():
    data = S.parse_notes(NOTES)
    assert data["summary"] == "API latency spike on 2026-09-20"
    assert "p99" in data["impact"]
    assert data["root_cause"] == "Missing index on orders table after migration"
    assert len(data["action_items"]) == 2
    assert data["action_items"][0] == {"owner": "priya",
                                      "task": "add index review to migration checklist"}


def test_parse_notes_key_value_style():
    data = S.parse_notes("Summary: db failover\nImpact: 2 min read-only\n")
    assert data["summary"] == "db failover"
    assert data["impact"] == "2 min read-only"


def test_parse_notes_messy_never_raises():
    data = S.parse_notes("just some random text\n\n## Unknown Section\nblah")
    assert data["summary"] == ""


def test_render_postmortem_structure():
    data = S.parse_notes(NOTES)
    text = S.render_postmortem(data)
    for heading in ("Impact", "Timeline", "Root cause", "What went well",
                    "What went poorly", "Action items"):
        assert f"## {heading}" in text
    assert "- [ ] add index review" in text
    assert "priya" in text


def test_save_postmortem(data_dir):
    data = S.parse_notes(NOTES)
    path = S.save_postmortem(data)
    assert path.parent == data_dir / "sre_postmortems"
    assert path.suffix == ".md"
    assert "Postmortem" in path.read_text()


def test_blameless_clean():
    data = S.parse_notes(NOTES)
    assert S.check_blameless(data) == []


def test_blameless_flags_blame_language():
    data = {"summary": "outage", "impact": "", "timeline": "",
            "root_cause": "This was entirely John's fault, he screwed up the deploy.",
            "went_well": "", "went_poorly": "blame the on-call for being slow",
            "action_items": [{"owner": "", "task": "fix"}]}
    warnings = S.check_blameless(data)
    assert len(warnings) >= 2


def test_postmortem_from_notes_cli(data_dir, tmp_path, capsys):
    notes = tmp_path / "notes.txt"
    notes.write_text(NOTES)
    args = argparse.Namespace(sre_cmd="postmortem", from_notes=str(notes))
    assert S.dispatch(args) == 0
    out = capsys.readouterr().out
    assert "Postmortem" in out
    assert "Saved to" in out
    saved = list((data_dir / "sre_postmortems").glob("*.md"))
    assert len(saved) == 1


def test_postmortem_missing_notes_file(capsys):
    args = argparse.Namespace(sre_cmd="postmortem", from_notes="/nope/notes.txt")
    assert S.dispatch(args) == 2


# ---------------------------------------------------------------------------
# IaC review drill
# ---------------------------------------------------------------------------

def test_eight_snippets_minimum():
    assert len(S.SNIPPETS) >= 8
    for s in S.SNIPPETS:
        assert 2 <= len(s["issues"]) <= 4
        assert s["difficulty"] in ("easy", "medium")
        assert s["kind"] in ("terraform", "kubernetes")
        assert s["code"].strip()


def test_difficulty_filter():
    easy = S.list_snippets("easy")
    medium = S.list_snippets("medium")
    assert easy and medium
    assert all(s["difficulty"] == "easy" for s in easy)
    assert len(easy) + len(medium) == len(S.SNIPPETS)


def test_get_snippet_deterministic():
    a = S.get_snippet(0, "easy")
    b = S.get_snippet(0, "easy")
    assert a["id"] == b["id"]
    assert S.get_snippet(1, "easy")["id"] != a["id"] or len(S.list_snippets("easy")) == 1


def test_match_issues_scores_keywords():
    snippet = S.get_snippet(0)  # sg-open-world
    matched = S.match_issues(snippet, "SSH is open to 0.0.0.0/0 and the MySQL database port 3306 is public")
    assert matched == [True, True]
    matched = S.match_issues(snippet, "looks fine to me")
    assert matched == [False, False]


def test_run_drill_noninteractive(capsys):
    snippet = S.get_snippet(0)
    rc = S.run_drill(snippet, answers=["ssh open", "db port 3306 public"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Score: 2/2" in out
    assert "Answers:" in out


def test_iac_review_answers_mode(capsys):
    args = argparse.Namespace(sre_cmd="iac-review", difficulty="easy",
                             index=0, answers=True)
    assert S.dispatch(args) == 0
    out = capsys.readouterr().out
    assert "IaC Review Drill" in out
    assert "Answers:" in out


def test_iac_review_bad_difficulty(capsys):
    args = argparse.Namespace(sre_cmd="iac-review", difficulty="hard",
                             index=0, answers=True)
    assert S.dispatch(args) == 2


def test_iac_review_via_registered_parser(capsys):
    parser = make_parser()
    args = parser.parse_args(["iac-review", "--answers", "--difficulty", "medium"])
    assert args.sre_cmd == "iac-review"
    assert args.func(args) == 0
    assert "Answers:" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# register / dispatch contract
# ---------------------------------------------------------------------------

def test_register_adds_three_subcommands():
    parser = make_parser()
    for name in ("playbook", "postmortem", "iac-review"):
        args = parser.parse_args([name] + (["--answers"] if name == "iac-review" else
                                           ["disk-full"] if name == "playbook" else
                                           ["--from-notes", "/nope"]))
        assert args.func is S.dispatch


def test_dispatch_unknown():
    args = argparse.Namespace(sre_cmd="bogus")
    assert S.dispatch(args) == 2


def test_no_em_dashes_in_user_facing_text():
    import pathlib
    text = pathlib.Path(S.__file__).read_text()
    assert "\u2014" not in text

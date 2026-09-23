"""Tests for the `candid release` CLI wiring in candid/__main__.py.

Run: python3 -m pytest tests/test_release_cli.py -q
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-release-cli"

from candid.__main__ import build_parser, cmd_release  # noqa: E402


SUBCOMMANDS = [
    "checklist", "report", "tests", "docs", "version", "bump",
    "notes", "secrets", "tag", "verify", "migrate",
]


def test_all_subcommands_parse():
    p = build_parser()
    for sub in SUBCOMMANDS:
        argv = ["release", sub]
        if sub == "bump":
            argv.append("patch")
        args = p.parse_args(argv)
        assert args.cmd == "release", sub
        assert args.what == sub, sub
        assert args.func is cmd_release, sub


def test_release_version_output(capsys):
    cmd_release(argparse.Namespace(what="version"))
    out = capsys.readouterr().out
    assert "candid version:" in out
    assert "[PASS]" in out or "[SKIP]" in out


def test_release_docs_output(capsys):
    cmd_release(argparse.Namespace(what="docs"))
    out = capsys.readouterr().out
    assert "cli commands documented" in out


def test_release_notes_output(capsys):
    cmd_release(argparse.Namespace(what="notes", since=None, write=False))
    out = capsys.readouterr().out
    assert "Changes since" in out or "No changes found" in out


def test_release_secrets_output(capsys):
    cmd_release(argparse.Namespace(what="secrets"))
    out = capsys.readouterr().out
    assert "forbidden files" in out


def test_release_migrate_output(capsys):
    cmd_release(argparse.Namespace(what="migrate", from_ref=None, to_ref="HEAD"))
    out = capsys.readouterr().out
    assert "Migration notes" in out


def test_release_tag_parses():
    p = build_parser()
    args = p.parse_args(["release", "tag"])
    assert args.what == "tag"
    assert args.go is False
    assert args.notes == ""
    args = p.parse_args(["release", "tag", "--go", "--notes", "hello"])
    assert args.go is True
    assert args.notes == "hello"

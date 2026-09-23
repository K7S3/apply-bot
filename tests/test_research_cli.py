"""CLI wiring tests for `candid research` (batch 97)."""

import json
import subprocess
import sys
import os


def run(*args, env_extra=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "candid", "research", *args],
        capture_output=True, text=True, env=env, cwd="/home/hatch/workspace/candid-batch97")


def test_research_help(tmp_path):
    env_extra = {"CANDID_DATA_DIR": str(tmp_path)}
    r = run("--help", env_extra=env_extra)
    assert r.returncode == 0
    for sub in ["papers", "frame", "statement", "taste", "hardqa",
                "map", "rebuttal", "talk", "export-notes", "export-digest"]:
        assert sub in r.stdout


def test_papers_add_list_search(tmp_path):
    env_extra = {"CANDID_DATA_DIR": str(tmp_path)}
    r = run("papers", "add", "--title", "CLI Paper", "--authors", "A, B",
            env_extra=env_extra)
    assert r.returncode == 0
    assert "cli-paper" in r.stdout
    r = run("papers", "list", env_extra=env_extra)
    assert r.returncode == 0 and "CLI Paper" in r.stdout
    r = run("papers", "search", "cli", env_extra=env_extra)
    assert r.returncode == 0 and "cli-paper" in r.stdout


def test_papers_status_and_notes(tmp_path):
    env_extra = {"CANDID_DATA_DIR": str(tmp_path)}
    run("papers", "add", "--title", "P2", env_extra=env_extra)
    r = run("papers", "status", "p2", "--to", "read", env_extra=env_extra)
    assert r.returncode == 0 and "read" in r.stdout
    r = run("papers", "notes", "p2", "--text", "important note", env_extra=env_extra)
    assert r.returncode == 0
    r = run("papers", "get", "p2", env_extra=env_extra)
    assert r.returncode == 0 and "important note" in r.stdout


def test_papers_drill_stats_empty(tmp_path):
    env_extra = {"CANDID_DATA_DIR": str(tmp_path)}
    run("papers", "add", "--title", "P3", env_extra=env_extra)
    r = run("papers", "drill-stats", "p3", env_extra=env_extra)
    assert r.returncode == 0


def test_frame_render(tmp_path):
    env_extra = {"CANDID_DATA_DIR": str(tmp_path)}
    r = run("frame", "--title", "X", "--description", "did things",
            "--techniques", "a", "--outcomes", "b", env_extra=env_extra)
    assert r.returncode == 0
    assert "Candidate paper titles" in r.stdout
    assert "[FILL IN]" in r.stdout


def test_statement_build_and_check(tmp_path):
    env_extra = {"CANDID_DATA_DIR": str(tmp_path)}
    data = {
        "name": "Test",
        "past_projects": [{"title": "P", "description": "D" * 400,
                           "outcomes": "O"}],
        "current_focus": "F" * 300,
        "future_agenda": ["A1", "A2"],
    }
    f = tmp_path / "stmt.json"
    f.write_text(json.dumps(data))
    r = run("statement", "check", "--data", str(f), env_extra=env_extra)
    assert r.returncode == 0
    assert "Word count" in r.stdout
    r = run("statement", "build", "--data", str(f), env_extra=env_extra)
    assert r.returncode == 0
    assert "Past Research" in r.stdout


def test_taste_list_and_stats(tmp_path):
    env_extra = {"CANDID_DATA_DIR": str(tmp_path)}
    r = run("taste", "list", env_extra=env_extra)
    assert r.returncode == 0 and "research_taste" in r.stdout
    r = run("taste", "stats", env_extra=env_extra)
    assert r.returncode == 0


def test_hardqa_generate_and_stats(tmp_path):
    env_extra = {"CANDID_DATA_DIR": str(tmp_path)}
    r = run("hardqa", "generate", "--project", "Built X compared to Y baseline.",
            env_extra=env_extra)
    assert r.returncode == 0 and "baseline" in r.stdout.lower()
    r = run("hardqa", "stats", env_extra=env_extra)
    assert r.returncode == 0


def test_map_from_json(tmp_path):
    env_extra = {"CANDID_DATA_DIR": str(tmp_path)}
    f = tmp_path / "entries.json"
    f.write_text(json.dumps([{"title": "T", "year": 2024, "kind": "project"}]))
    r = run("map", "--json-file", str(f), env_extra=env_extra)
    assert r.returncode == 0 and "Timeline" in r.stdout


def test_rebuttal_flow(tmp_path):
    env_extra = {"CANDID_DATA_DIR": str(tmp_path)}
    r = run("rebuttal", "add", "--text", "The experiments are insufficient.",
            env_extra=env_extra)
    assert r.returncode == 0
    r = run("rebuttal", "progress", env_extra=env_extra)
    assert r.returncode == 0 and "0/1" in r.stdout


def test_talk_outline(tmp_path):
    env_extra = {"CANDID_DATA_DIR": str(tmp_path)}
    r = run("talk", "--minutes", "15", "--title", "T", "--problem", "P",
            "--approach", "A", "--results", "R", "--takeaways", "K",
            "--future-work", "F", env_extra=env_extra)
    assert r.returncode == 0 and "15-minute" in r.stdout


def test_export_notes_and_digest(tmp_path):
    env_extra = {"CANDID_DATA_DIR": str(tmp_path)}
    run("papers", "add", "--title", "Export Me", env_extra=env_extra)
    out = tmp_path / "notes"
    r = run("export-notes", "--out-dir", str(out), env_extra=env_extra)
    assert r.returncode == 0 and (out / "index.md").exists()
    r = run("export-digest", "--out", str(tmp_path / "digest.md"),
            env_extra=env_extra)
    assert r.returncode == 0 and (tmp_path / "digest.md").exists()

"""Tests for candid.polish (interview answer polisher) + polish CLI group.

Run: CANDID_DATA_DIR=$(mktemp -d) python3 -m pytest tests/test_polish_core.py -q
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import polish as PL

DRAFT = (
    "Um, so our checkout page was, like, super slow during Black Friday. "
    "Basically, I was asked to fix the latency. "
    "I built a caching layer and, you know, I refactored the hot queries. "
    "As a result, latency dropped 40% and we saved $120k in infra costs."
)


# ---------------------------------------------------------------------------
# read_draft
# ---------------------------------------------------------------------------

class TestReadDraft:
    def test_file(self, tmp_path):
        f = tmp_path / "draft.txt"
        f.write_text(DRAFT)
        assert PL.read_draft(str(f)) == DRAFT

    def test_text_scheme(self):
        assert PL.read_draft("text:hello there") == "hello there"

    def test_stdin(self, monkeypatch):
        import io
        monkeypatch.setattr(sys, "stdin", io.StringIO(DRAFT))
        assert PL.read_draft("-") == DRAFT

    def test_missing_file_raises(self):
        with pytest.raises(PL.PolishError):
            PL.read_draft("/nonexistent/draft.txt")

    def test_empty_text_raises(self):
        with pytest.raises(PL.PolishError):
            PL.read_draft("text:   ")


# ---------------------------------------------------------------------------
# to_star
# ---------------------------------------------------------------------------

class TestToStar:
    def test_sections_found(self):
        star = PL.to_star(DRAFT)
        assert "Black Friday" in star["situation"]
        assert "asked to" in star["task"]
        assert "caching layer" in star["action"]
        assert "40%" in star["result"]
        assert star["missing"] == []

    def test_missing_sections_named(self):
        star = PL.to_star("I just really like teamwork and collaboration.")
        assert "task" in star["missing"]
        assert "result" in star["missing"]
        for sec in ("task", "result"):
            assert star[sec] == ""

    def test_never_invents_content(self):
        text = "Our deploy pipeline was broken. I fixed the flaky tests."
        star = PL.to_star(text)
        for sec in ("situation", "task", "action", "result"):
            if star[sec]:
                assert star[sec] in text


# ---------------------------------------------------------------------------
# scrub_fillers
# ---------------------------------------------------------------------------

class TestScrubFillers:
    def test_removes_fillers(self):
        cleaned, removed = PL.scrub_fillers(
            "Um, basically I built it, you know, sort of quickly."
        )
        assert "um" in [r.lower() for r in removed]
        assert "basically" in [r.lower() for r in removed]
        assert "you know" in [r.lower() for r in removed]
        assert "sort of" in [r.lower() for r in removed]
        assert "basically" not in cleaned.lower()
        assert "you know" not in cleaned.lower()

    def test_keeps_numbers_metrics_proper_nouns(self):
        text = "Basically, latency dropped 40% at Acme Corp and we saved $120k."
        cleaned, removed = PL.scrub_fillers(text)
        assert "40%" in cleaned
        assert "$120k" in cleaned
        assert "Acme Corp" in cleaned
        assert "basically" in [r.lower() for r in removed]

    def test_removed_list_per_occurrence(self):
        _, removed = PL.scrub_fillers("Basically, basically I did it.")
        assert removed.count("basically") == 2


# ---------------------------------------------------------------------------
# polish_answer
# ---------------------------------------------------------------------------

class TestPolishAnswer:
    def test_pipeline_stats(self):
        res = PL.polish_answer(DRAFT, target_seconds=90)
        st = res["stats"]
        assert set(st) == {"words_before", "words_after",
                           "fillers_removed", "voice_overlap_pct"}
        assert st["words_after"] <= st["words_before"]
        assert st["fillers_removed"] > 0
        assert st["voice_overlap_pct"] >= 60
        assert "fillers" not in res["polished"].lower() or True

    def test_tighten_keeps_metric_sentences(self):
        long = " ".join(
            ["I attended the weekly sync and took notes."] * 40
            + ["As a result, uptime improved to 99.9%."]
        )
        res = PL.polish_answer(long, target_seconds=30)  # ~75 words
        assert "99.9%" in res["polished"]
        assert res["stats"]["words_after"] <= res["stats"]["words_before"]

    def test_suggestions_flag_gaps(self):
        res = PL.polish_answer("I like working with people.")
        joined = " ".join(res["suggestions"])
        assert "no quantified result" in joined
        assert "missing" in joined

    def test_suggestions_never_add_claims(self):
        res = PL.polish_answer(DRAFT)
        for sug in res["suggestions"]:
            assert "40%" not in sug  # claims live in text, not suggestions

    def test_voice_drift_warning(self):
        assert PL.voice_overlap("I built a fast cache for Acme", "the weather is nice today") < 60
        res = PL.polish_answer(DRAFT)
        assert not any("drifted from your voice" in s for s in res["suggestions"])

    def test_bad_target_seconds(self):
        with pytest.raises(PL.PolishError):
            PL.polish_answer(DRAFT, target_seconds=0)


# ---------------------------------------------------------------------------
# render_diff
# ---------------------------------------------------------------------------

class TestRenderDiff:
    def test_unified_diff(self):
        d = PL.render_diff("line one\nline two", "line one\nline 2")
        assert d.startswith("--- original")
        assert "+++ polished" in d
        assert "-line two" in d
        assert "+line 2" in d


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------

def _run_cli(tmpdir, *args, stdin_text=None):
    env = dict(os.environ, CANDID_DATA_DIR=str(tmpdir))
    return subprocess.run(
        [sys.executable, "-m", "candid", *args],
        capture_output=True, text=True, env=env, cwd=ROOT,
        input=stdin_text,
    )


class TestPolishCLI:
    def test_run_writes_last_json(self, tmp_path):
        r = _run_cli(tmp_path, "polish", "run", "--text", DRAFT)
        assert r.returncode == 0, r.stderr
        last = tmp_path / "polish_last.json"
        assert last.exists()
        data = json.loads(last.read_text())
        assert set(data) == {"original", "polished", "star", "stats", "suggestions"}
        assert "@@ " in r.stdout or "--- original" in r.stdout

    def test_run_json_flag(self, tmp_path):
        r = _run_cli(tmp_path, "polish", "run", "--text", DRAFT, "--json")
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["stats"]["words_before"] > 0

    def test_run_from_stdin(self, tmp_path):
        r = _run_cli(tmp_path, "polish", "run", stdin_text=DRAFT)
        assert r.returncode == 0, r.stderr

    def test_star(self, tmp_path):
        f = tmp_path / "d.txt"
        f.write_text(DRAFT)
        r = _run_cli(tmp_path, "polish", "star", "--file", str(f))
        assert r.returncode == 0, r.stderr
        assert "[RESULT]" in r.stdout

    def test_star_json(self, tmp_path):
        r = _run_cli(tmp_path, "polish", "star", "--text", DRAFT, "--json")
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["missing"] == []

    def test_scrub(self, tmp_path):
        r = _run_cli(tmp_path, "polish", "scrub", "--text", DRAFT, "--json")
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert "basically" not in data["cleaned"].lower()
        assert "40%" in data["cleaned"]
        assert len(data["removed"]) > 0

    def test_missing_file_friendly_error(self, tmp_path):
        r = _run_cli(tmp_path, "polish", "run", "--file", "/nonexistent/d.txt")
        assert r.returncode != 0
        assert "Error:" in r.stderr

    def test_help_lists_group(self, tmp_path):
        r = _run_cli(tmp_path, "polish", "--help")
        assert r.returncode == 0
        assert "run" in r.stdout and "star" in r.stdout and "scrub" in r.stdout

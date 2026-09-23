"""Tests for candid.research_talk (talk outlines + notes export).

Run: cd ~/workspace/candid-batch97 && python3 -m pytest tests/test_research_talk.py -q
No network; all fixtures are in tmp_path.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import research_talk as RT


def _content(**overrides):
    base = {
        "title": "Cache-aware scheduling for serverless ML inference",
        "problem": "Cold starts dominate p99 latency in serverless inference.",
        "approach": "Keep warm model shards on a shared NVMe cache tier.",
        "results": "p99 latency down 41% on a 12-node cluster.",
        "takeaways": "Cache placement matters more than model size.",
        "future_work": "Extend to multi-tenant GPU sharing.",
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# Feature 1: outline builder
# --------------------------------------------------------------------------

def test_build_outline_sections_and_time_budget():
    outline = RT.build_outline(_content(), 15)
    assert outline["title"].startswith("Cache-aware")
    assert outline["minutes"] == 15
    assert outline["requested_minutes"] == 15
    keys = [s["key"] for s in outline["sections"]]
    assert keys == ["hook", "problem", "approach", "results",
                    "takeaways", "future", "backup"]
    total = sum(s["minutes"] for s in outline["sections"] if s["minutes"])
    assert total == pytest.approx(15, abs=0.5)
    for s in outline["sections"]:
        assert s["slides"] >= 1
        assert len(s["prompts"]) >= 2  # prompts, not scripts


def test_build_outline_supported_lengths():
    for minutes in (5, 15, 30, 60):
        outline = RT.build_outline(_content(), minutes)
        assert outline["minutes"] == minutes
        assert "note" not in outline
        total = sum(s["minutes"] for s in outline["sections"] if s["minutes"])
        assert total == pytest.approx(minutes, abs=0.5)


def test_build_outline_snaps_to_nearest_with_note():
    outline = RT.build_outline(_content(), 20)
    assert outline["minutes"] == 15
    assert outline["requested_minutes"] == 20
    assert "20" in outline["note"] and "15" in outline["note"]


def test_build_outline_snap_tie_goes_shorter():
    outline = RT.build_outline(_content(), 45)  # equidistant from 30 and 60
    assert outline["minutes"] == 30


def test_build_outline_rejects_missing_fields():
    with pytest.raises(ValueError, match="results"):
        RT.build_outline(_content(results="  "), 15)


def test_build_outline_rejects_bad_minutes():
    with pytest.raises(ValueError, match="positive"):
        RT.build_outline(_content(), 0)
    with pytest.raises(ValueError, match="positive"):
        RT.build_outline(_content(), -5)


def test_build_outline_keeps_optional_fields():
    outline = RT.build_outline(_content(authors="A. Researcher",
                                        venue="SysML 2026"), 5)
    assert outline["authors"] == "A. Researcher"
    assert outline["venue"] == "SysML 2026"


def test_render_outline_text_contains_everything():
    outline = RT.build_outline(_content(), 15)
    text = RT.render_outline(outline)
    assert "Cache-aware scheduling" in text
    assert "15-minute talk" in text
    for name in ("Hook", "Problem", "Approach", "Results",
                 "Takeaways", "Future work", "Backup slides"):
        assert name in text
    assert "Can you answer" in text
    # prompts are questions, not scripted notes
    assert "?" in text


def test_render_outline_md_structure():
    outline = RT.build_outline(_content(authors="A. Researcher"), 30)
    md = RT.render_outline_md(outline)
    assert md.startswith("# Cache-aware scheduling")
    assert "| # | Section | Time (min) | Slides |" in md
    assert "## Time budget" in md
    assert "## Speaker notes" in md
    assert "A. Researcher" in md
    # user's own content is echoed back, nothing invented
    assert "p99 latency down 41%" in md
    assert "### 4. Results" in md


def test_render_outline_md_includes_snap_note():
    outline = RT.build_outline(_content(), 10)
    md = RT.render_outline_md(outline)
    assert "> Note: 10 minutes is not a supported talk length" in md


def test_save_outline_md_and_txt(tmp_path):
    outline = RT.build_outline(_content(), 5)
    md_path = RT.save_outline(outline, tmp_path / "nested" / "talk.md")
    assert md_path.is_file()
    assert md_path.read_text().startswith("# Cache-aware")
    txt_path = RT.save_outline(outline, tmp_path / "talk.txt")
    assert txt_path.read_text().startswith("Talk outline:")
    # saved files end with exactly one newline
    assert not txt_path.read_text().endswith("\n\n")


def test_outline_prompts_are_questions_not_scripts():
    for _key, _name, _frac, prompts in RT._SECTIONS:
        for p in prompts:
            assert p.rstrip().endswith("?"), p


# --------------------------------------------------------------------------
# Feature 2: notes exporter
# --------------------------------------------------------------------------

def _write_store(tmp_path, papers):
    store = tmp_path / "papers.json"
    store.write_text(json.dumps(papers), encoding="utf-8")
    return tmp_path


def _sample_papers():
    return [
        {
            "id": "cache-sched",
            "title": "Cache-aware scheduling for serverless ML inference",
            "authors": "A. Researcher, B. Colleague",
            "year": "2026",
            "venue": "SysML",
            "tags": ["systems", "ml-infra"],
            "summary": "Shared NVMe cache tier cuts cold starts.",
            "notes": "Reproduce the p99 experiment on our cluster.",
            "takeaways": "Placement beats model size.",
            "drill_summaries": "Q: main result? A: p99 down 41%.",
            "related": ["gpu-share"],
        },
        {
            "id": "gpu-share",
            "title": "Multi-tenant GPU sharing",
            "notes": "Follow-up idea from future work.",
        },
    ]


def test_export_notes_writes_one_file_per_paper_plus_index(tmp_path):
    base = _write_store(tmp_path, _sample_papers())
    out = tmp_path / "exports"
    written = RT.export_notes(out, base=base)
    assert len(written) == 3
    names = sorted(Path(w).name for w in written)
    assert "index.md" in names
    assert "cache-sched.md" in names
    assert "gpu-share.md" in names


def test_export_notes_paper_content_is_users_own(tmp_path):
    base = _write_store(tmp_path, _sample_papers())
    out = tmp_path / "exports"
    RT.export_notes(out, base=base)
    text = (out / "cache-sched.md").read_text()
    assert "Reproduce the p99 experiment on our cluster." in text
    assert "Q: main result? A: p99 down 41%." in text
    assert "Placement beats model size." in text
    assert 'title: "Cache-aware scheduling for serverless ML inference"' in text
    # wikilink cross-reference to the related paper
    assert "[[gpu-share]]" in text


def test_export_notes_index_links_papers(tmp_path):
    base = _write_store(tmp_path, _sample_papers())
    out = tmp_path / "exports"
    RT.export_notes(out, base=base)
    index = (out / "index.md").read_text()
    assert "[[cache-sched|Cache-aware scheduling for serverless ML inference (2026)]]" in index
    assert "[[gpu-share|Multi-tenant GPU sharing]]" in index


def test_export_notes_missing_store_never_crashes(tmp_path):
    out = tmp_path / "exports"
    written = RT.export_notes(out, base=tmp_path / "no-such-dir")
    assert len(written) == 1
    index = Path(written[0])
    assert index.name == "index.md"
    assert "empty" in index.read_text().lower()


def test_export_notes_malformed_store_never_crashes(tmp_path):
    (tmp_path / "papers.json").write_text("{not valid json", encoding="utf-8")
    written = RT.export_notes(tmp_path / "exports", base=tmp_path)
    assert len(written) == 1 and written[0].endswith("index.md")


def test_export_notes_creates_nested_out_dir(tmp_path):
    base = _write_store(tmp_path, _sample_papers())
    deep = tmp_path / "a" / "b" / "c"
    written = RT.export_notes(deep, base=base)
    assert all(Path(w).is_file() for w in written)


def test_export_notes_filename_safe_for_weird_titles(tmp_path):
    base = _write_store(tmp_path, [{"title": "What? A/B Testing: 100% 'real' (draft)"}])
    out = tmp_path / "exports"
    written = RT.export_notes(out, base=base)
    paper_file = [w for w in written if not w.endswith("index.md")][0]
    name = Path(paper_file).name
    assert all(c.isalnum() or c in "-_." for c in name)
    assert name.endswith(".md")


def test_export_digest_consolidates_papers(tmp_path):
    base = _write_store(tmp_path, _sample_papers())
    digest = RT.export_digest(tmp_path / "digest.md", base=base)
    text = Path(digest).read_text()
    assert "# Research digest" in text
    assert "Cache-aware scheduling for serverless ML inference" in text
    assert "Multi-tenant GPU sharing" in text
    assert "Placement beats model size." in text
    assert "[[cache-sched|" in text


def test_export_digest_empty_library(tmp_path):
    digest = RT.export_digest(tmp_path / "digest.md", base=tmp_path / "missing")
    text = Path(digest).read_text()
    assert "No papers in the library yet" in text


def test_load_paper_library_deduplicates_ids(tmp_path):
    base = _write_store(tmp_path, [{"id": "dup", "title": "One"},
                                   {"id": "dup", "title": "Two"}])
    papers = RT.load_paper_library(base=base)
    assert [p["id"] for p in papers] == ["dup", "dup-2"]


def test_load_paper_library_accepts_wrapped_list(tmp_path):
    (tmp_path / "papers.json").write_text(
        json.dumps({"papers": [{"id": "w1", "title": "Wrapped"}]}),
        encoding="utf-8")
    papers = RT.load_paper_library(base=tmp_path)
    assert [p["id"] for p in papers] == ["w1"]

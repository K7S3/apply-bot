"""Tests for candid.polish_export (Worker D, batch-80).

All tests run against a seeded DATA_DIR/polish_library.json in a tmpdir via
the CANDID_DATA_DIR env override.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from candid import polish_export
from candid.polish_export import (
    ExportError,
    approved_entries,
    competency_tags,
    drill_order,
    export_markdown,
    flashcards,
    format_cards,
    get_entry,
    load_library,
    print_sheet,
    star_recap,
)

SEED_LIBRARY = {
    "entries": [
        {
            "id": "ans-1",
            "name": "debugging outage",
            "question": "Tell me about a time you debugged a production outage.",
            "original": "I fixed the outage it was bad.",
            "polished": (
                "Last quarter our checkout service went down during a sale. "
                "I was the on-call engineer and had to restore it quickly. "
                "I traced the spike in latency to a connection pool leak, "
                "rolled out a fix, and added metrics so we would catch it earlier. "
                "The service recovered within an hour and the postmortem led to "
                "a new alert that has fired twice since."
            ),
            "status": "approved",
            "story_id": "story-debug",
            "created_at": "2026-09-20T10:00:00",
        },
        {
            "id": "ans-2",
            "name": "leading migration",
            "question": "Describe a project you led.",
            "original": "I led the migration project.",
            "polished": (
                "I led a team of four engineers migrating our billing pipeline "
                "to a new provider. I broke the work into milestones, ran "
                "weekly reviews with stakeholders, and we shipped the migration "
                "two weeks early with zero failed payments."
            ),
            "status": "approved",
            "story_id": None,
            "created_at": "2026-09-21T10:00:00",
        },
        {
            "id": "ans-3",
            "name": "weakness draft",
            "question": "What is your greatest weakness?",
            "original": "I work too hard.",
            "polished": "I sometimes take on too much myself instead of delegating.",
            "status": "draft",
            "created_at": "2026-09-21T11:00:00",
        },
    ]
}


@pytest.fixture()
def lib_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    # Rebind DATA_DIR since candid.config read it at import time.
    monkeypatch.setattr(polish_export, "DATA_DIR", tmp_path)
    (tmp_path / "polish_library.json").write_text(
        json.dumps(SEED_LIBRARY), encoding="utf-8"
    )
    return tmp_path


def test_load_library(lib_dir):
    assert len(load_library()) == 3


def test_load_library_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(polish_export, "DATA_DIR", tmp_path)
    assert load_library() == []


def test_load_library_bad_json(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(polish_export, "DATA_DIR", tmp_path)
    (tmp_path / "polish_library.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(ExportError):
        load_library()


def test_approval_gate(lib_dir):
    approved = approved_entries()
    assert {e["id"] for e in approved} == {"ans-1", "ans-2"}


def test_get_entry_missing(lib_dir):
    with pytest.raises(ExportError):
        get_entry("nope")


def test_export_all_approved(lib_dir):
    path = export_markdown()
    text = Path(path).read_text(encoding="utf-8")
    assert path.endswith("polish_cheatsheet.md")
    assert "debugged a production outage" in text
    assert "Describe a project you led" in text
    # draft entry must not appear
    assert "greatest weakness" not in text
    assert "## " in text and "**Competencies:**" in text
    assert "STAR recap" in text


def test_export_single_entry(lib_dir):
    path = export_markdown(entry_id="ans-2", path=str(lib_dir / "one.md"))
    text = Path(path).read_text(encoding="utf-8")
    assert "Describe a project you led" in text
    assert "production outage" not in text


def test_export_draft_entry_refused(lib_dir):
    with pytest.raises(ExportError):
        export_markdown(entry_id="ans-3")


def test_export_missing_id(lib_dir):
    with pytest.raises(ExportError):
        export_markdown(entry_id="missing")


def test_export_empty_library(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(polish_export, "DATA_DIR", tmp_path)
    (tmp_path / "polish_library.json").write_text(
        json.dumps({"entries": []}), encoding="utf-8"
    )
    with pytest.raises(ExportError):
        export_markdown()


def test_print_sheet_width_and_plain_text(lib_dir):
    sheet = print_sheet()
    assert "##" not in sheet  # no markdown headings
    for line in sheet.splitlines():
        assert len(line) <= 80, f"line too long: {line!r}"
    assert "QUESTION:" in sheet
    assert "greatest weakness" not in sheet


def test_print_sheet_single(lib_dir):
    sheet = print_sheet(entry_id="ans-1")
    assert "production outage" in sheet
    assert "project you led" not in sheet


def test_print_sheet_draft_refused(lib_dir):
    with pytest.raises(ExportError):
        print_sheet(entry_id="ans-3")


def test_competency_tags():
    entry = SEED_LIBRARY["entries"][0]
    tags = competency_tags(entry)
    assert "reliability" in tags
    assert "debugging" in tags
    assert "performance" in tags
    lead = SEED_LIBRARY["entries"][1]
    assert "leadership" in competency_tags(lead)


def test_star_recap():
    recap = star_recap(SEED_LIBRARY["entries"][0]["polished"])
    assert recap["situation"].startswith("Last quarter")
    assert recap["result"].endswith("since.")
    assert "connection pool leak" in recap["action"]
    single = star_recap("One sentence only.")
    assert single["situation"] == single["result"] == "One sentence only."
    assert star_recap("") == {
        "situation": "", "task": "", "action": "", "result": "",
    }


def test_flashcards(lib_dir):
    cards = flashcards()
    assert len(cards) == 2
    assert cards[0]["front"] == "Tell me about a time you debugged a production outage."
    assert "checkout service" in cards[0]["back"]
    # draft excluded
    assert all("weakness" not in c["front"] for c in cards)


def test_format_cards():
    cards = [
        {"front": "Q1", "back": "A1"},
        {"front": "Q2", "back": "A2"},
    ]
    text = format_cards(cards)
    assert "Card 1/2" in text and "Card 2/2" in text
    assert "Q: Q1" in text and "A: A2" in text
    assert format_cards([]).startswith("No flashcards")


def test_drill_order_deterministic():
    cards = [{"front": f"q{i}", "back": ""} for i in range(10)]
    a = drill_order(cards, seed=7)
    b = drill_order(cards, seed=7)
    c = drill_order(cards, seed=8)
    assert a == b
    assert a != c
    # input not mutated, all cards preserved
    assert cards == [{"front": f"q{i}", "back": ""} for i in range(10)]
    assert sorted(x["front"] for x in a) == sorted(x["front"] for x in cards)


def test_flashcards_roundtrip_seed(lib_dir):
    cards = flashcards()
    shuffled = drill_order(cards, seed=0)
    text = format_cards(shuffled)
    assert "Card 1/2" in text

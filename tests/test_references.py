"""Tests for candid.references: reference sheet generator."""

from __future__ import annotations

import json

import pytest

from candid import references
from candid.references import (
    ReferencesError,
    add_reference,
    list_references,
    remove_reference,
    render_sheet,
)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "candid_data"
    monkeypatch.setenv("CANDID_DATA_DIR", str(d))
    return d


def test_add_list_round_trip(data_dir):
    add_reference("Jane Doe", "Former manager", contact="jane@example.com")
    refs = list_references()
    assert len(refs) == 1
    assert refs[0]["name"] == "Jane Doe"
    assert refs[0]["relationship"] == "Former manager"
    assert refs[0]["contact"] == "jane@example.com"
    # persisted under CANDID_DATA_DIR
    stored = json.loads((data_dir / "references.json").read_text())
    assert stored[0]["name"] == "Jane Doe"


def test_add_requires_name_and_relationship(data_dir):
    with pytest.raises(ReferencesError):
        add_reference("", "Former manager")
    with pytest.raises(ReferencesError):
        add_reference("Jane Doe", "")


def test_add_duplicate_refused(data_dir):
    add_reference("Jane Doe", "Former manager")
    with pytest.raises(ReferencesError):
        add_reference("jane doe", "Colleague")  # case-insensitive duplicate


def test_remove_reference(data_dir):
    add_reference("Jane Doe", "Former manager")
    add_reference("John Smith", "Colleague", contact="555-0100")
    removed = remove_reference("jane doe")  # case-insensitive
    assert removed["name"] == "Jane Doe"
    assert [r["name"] for r in list_references()] == ["John Smith"]
    with pytest.raises(ReferencesError):
        remove_reference("Nobody Here")


def test_render_markdown_sheet(data_dir):
    add_reference("Jane Doe", "Former manager", contact="jane@example.com",
                  notes="Managed me at Acme")
    sheet = render_sheet("Keshavan Seshadri", output="markdown")
    assert "Jane Doe" in sheet
    assert "Former manager" in sheet
    assert "jane@example.com" in sheet
    assert "Professional References" in sheet
    assert "Keshavan Seshadri" in sheet


def test_render_text_sheet(data_dir):
    add_reference("Jane Doe", "Former manager")
    sheet = render_sheet("Keshavan Seshadri", output="text")
    assert "Jane Doe" in sheet
    assert "Former manager" in sheet
    assert "#" not in sheet.splitlines()[0]


def test_render_refuses_when_empty(data_dir):
    with pytest.raises(ReferencesError) as exc:
        render_sheet("Keshavan Seshadri")
    assert "add_reference" in str(exc.value)  # clear next step


def test_render_available_upon_request(data_dir):
    # The alternative short form works with no referees stored.
    sheet = render_sheet("Keshavan Seshadri", on_request=True)
    assert "References available upon request" in sheet
    assert "Jane" not in sheet


def test_render_rejects_unknown_output(data_dir):
    add_reference("Jane Doe", "Former manager")
    with pytest.raises(ReferencesError):
        render_sheet("Keshavan Seshadri", output="pdf")


def test_determinism(data_dir):
    add_reference("Jane Doe", "Former manager", contact="jane@example.com")
    assert render_sheet("Keshavan Seshadri") == render_sheet("Keshavan Seshadri")
    assert list_references() == list_references()

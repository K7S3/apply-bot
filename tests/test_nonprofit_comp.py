"""Tests for candid.nonprofit_comp: honest, labeled compensation notes."""

from __future__ import annotations

import re

from candid.nonprofit_comp import (
    estimate_pslf_value,
    nonprofit_comp_note,
    nonprofit_negotiation_guide,
    render_nonprofit_comp,
)

SENTINEL_COMPANY = "Sentinel Test Org"  # no real data may exist for this


def test_note_with_salary_text_shows_range_and_context():
    note = nonprofit_comp_note("Data Analyst", SENTINEL_COMPANY,
                               "$60,000 - $75,000 a year")
    assert set(note.keys()) == {"notes", "sources"}
    joined = " ".join(note["notes"])
    assert "$60,000 - $75,000 a year" in joined  # the posted range, echoed
    assert "levels.fyi" in joined or "LCA" in joined
    assert any("studentaid.gov" in n for n in note["notes"])  # PSLF note present
    assert note["sources"], "sources must be non-empty"


def test_note_without_salary_text_advises_asking_early():
    note = nonprofit_comp_note("Program Manager", SENTINEL_COMPANY)
    joined = " ".join(note["notes"])
    assert "omit ranges" in joined or "ask" in joined.lower()
    assert "approved salary band" in joined or "band" in joined


def test_note_no_invented_numbers():
    # Without salary_text and without a loan balance, the note must not
    # contain any invented dollar figures for the sentinel employer.
    note = nonprofit_comp_note("Analyst", SENTINEL_COMPANY)
    joined = " ".join(note["notes"])
    dollars = re.findall(r"\$\s?[\d,]+", joined)
    assert dollars == [], f"invented dollar amounts found: {dollars}"


def test_note_pslf_loan_balance_echoes_only_user_number():
    note = nonprofit_comp_note("Analyst", SENTINEL_COMPANY,
                               loan_balance=42000.0)
    joined = " ".join(note["notes"])
    assert "$42,000.00" in joined  # user's own number, echoed with label
    # No other dollar amounts may appear.
    dollars = re.findall(r"\$[\d,]+\.\d{2}\b", joined)
    assert dollars == ["$42,000.00"], f"unexpected amounts: {dollars}"


def test_estimate_pslf_value_arithmetic():
    result = estimate_pslf_value(loan_balance=50000.0,
                                 monthly_payment=300.0,
                                 months_remaining=60)
    assert result["loan_balance"] == 50000.0
    assert result["payments_remaining_total"] == 18000.0
    # forgiven = 50000 - 60*300 = 32000
    assert result["forgiven_principal_estimate"] == 32000.0
    assert "not financial advice" in result["disclaimer"].lower()
    assert "formula" in result and "loan_balance" in result["formula"]


def test_estimate_pslf_value_zero_months():
    result = estimate_pslf_value(10000.0, 250.0, 0)
    assert result["forgiven_principal_estimate"] == 10000.0
    assert result["payments_remaining_total"] == 0.0


def test_estimate_pslf_value_rejects_negatives():
    import pytest
    with pytest.raises(ValueError):
        estimate_pslf_value(-1.0, 250.0, 12)


def test_guide_contains_key_sections():
    guide = nonprofit_negotiation_guide("Program Director")
    low = guide.lower()
    assert "benefits" in low
    assert "pslf" in low
    assert "title" in low
    assert "professional development" in low
    assert "flexib" in low  # flexible work
    assert "review" in low and ("six months" in low or "raise" in low)
    assert "sign-on" in low
    assert "program director" in low  # role wired in


def test_guide_includes_constraints_when_given():
    guide = nonprofit_negotiation_guide("Analyst", constraints="frozen band")
    assert "frozen band" in guide


def test_guide_honest_tone_no_bluff_tactics():
    guide = nonprofit_negotiation_guide("Analyst")
    low = guide.lower()
    assert "never invent" in low or "only cite real" in low
    assert "acknowledge" in low


def test_render_output_sanity():
    note = nonprofit_comp_note("Analyst", SENTINEL_COMPANY,
                               "$50,000 - $60,000 a year")
    rendered = render_nonprofit_comp(note)
    assert "Nonprofit comp note" in rendered
    assert "$50,000 - $60,000 a year" in rendered
    assert "Sources:" in rendered
    assert "studentaid.gov" in rendered
    # One numbered line per note.
    numbered = [l for l in rendered.splitlines()
                if re.match(r"^\d+\. ", l)]
    assert len(numbered) == len(note["notes"])

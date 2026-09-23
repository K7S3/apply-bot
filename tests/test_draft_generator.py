"""Tests for candid.drafting.drafts (drafts only - no sending)."""

from __future__ import annotations

import inspect

import pytest

from candid.drafting import drafts
from candid.drafting.drafts import KINDS, TONES, generate


FULL_CONTEXT = {
    "company": "Acme Robotics",
    "role": "Machine Learning Engineer",
    "contact_name": "Priya Nair",
    "interviewer_names": "Priya Nair and Tom Alvarez",
    "user_name": "Keshavan Seshadri",
    "topic": "ads ranking infrastructure",
    "applied_date": "2026-09-15",
    "decision_date": "2026-10-05",
    "target_role": "Machine Learning Engineer",
    "location": "New York, NY",
    "source": "your careers page",
}


def test_all_kinds_have_templates():
    assert set(KINDS) == {
        "thank_you",
        "check_in",
        "referral_request",
        "post_interview",
        "offer_stall",
        "rejection_thanks",
        "cold_intro",
    }
    assert set(KINDS) == set(drafts._TEMPLATES.keys())


@pytest.mark.parametrize("kind", KINDS)
def test_every_kind_generates_subject_and_body(kind):
    result = generate(kind, FULL_CONTEXT)
    assert result["kind"] == kind
    assert isinstance(result["subject"], str) and result["subject"]
    assert isinstance(result["body"], str) and result["body"]
    assert result["missing"] == []
    # All placeholders should be gone when context is complete.
    assert "{" not in result["subject"]
    assert "{" not in result["body"]


@pytest.mark.parametrize("kind", KINDS)
def test_drafts_are_multisentence(kind):
    result = generate(kind, FULL_CONTEXT)
    sentences = [s for s in result["body"].replace("\n", " ").split(".") if s.strip()]
    assert len(sentences) >= 2, kind


@pytest.mark.parametrize("kind", KINDS)
def test_missing_context_reports_and_preserves_placeholders(kind):
    result = generate(kind, {})
    assert result["missing"], kind  # non-empty list
    assert len(result["missing"]) == len(set(result["missing"]))  # deduped
    combined = result["subject"] + "\n" + result["body"]
    for token in result["missing"]:
        assert "{" + token + "}" in combined, (kind, token)


def test_partial_context_reports_only_missing():
    result = generate("thank_you", {"company": "Acme", "role": "MLE"})
    assert "contact_name" in result["missing"]
    assert "company" not in result["missing"]
    assert "role" not in result["missing"]
    assert "Acme" in result["subject"]
    assert "{contact_name}" in result["body"]  # preserved verbatim


def test_tone_variants_differ():
    prof = generate("thank_you", FULL_CONTEXT, tone="professional")
    friendly = generate("thank_you", FULL_CONTEXT, tone="friendly")
    concise = generate("thank_you", FULL_CONTEXT, tone="concise")
    assert prof["tone"] == "professional"
    assert friendly["tone"] == "friendly"
    assert concise["tone"] == "concise"
    assert len(prof["body"]) != len(friendly["body"]) or prof["body"] != friendly["body"]
    assert friendly["body"] != concise["body"]


def test_unknown_tone_falls_back_to_professional():
    result = generate("check_in", FULL_CONTEXT, tone="chatty")
    assert result["tone"] == "professional"


def test_unknown_kind_raises():
    with pytest.raises(ValueError, match="Unknown draft kind"):
        generate("love_letter", FULL_CONTEXT)


def test_deterministic():
    a = generate("cold_intro", FULL_CONTEXT, tone="friendly")
    b = generate("cold_intro", FULL_CONTEXT, tone="friendly")
    assert a == b


@pytest.mark.parametrize("tone", TONES)
def test_all_tones_defined_or_fallback(tone):
    # Should never raise, even when a kind lacks that tone's template.
    result = generate("offer_stall", FULL_CONTEXT, tone=tone)
    assert result["tone"] in TONES
    assert result["subject"] and result["body"]


def _stripped_source(module) -> str:
    """Module source with docstrings and comments removed (AST-based)."""
    import ast

    source = inspect.getsource(module)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None and node.body and isinstance(node.body[0], ast.Expr):
                # Blank out the docstring so words like "socket" in prose
                # don't trip the check.
                node.body[0].value = ast.Constant(value="")
    return ast.unparse(tree)


def _imported_modules(module) -> list[str]:
    import ast

    tree = ast.parse(inspect.getsource(module))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module.split(".")[0])
    return names


def test_no_sending_code_in_module():
    source = _stripped_source(drafts).lower()
    imports = _imported_modules(drafts)
    for banned in ("smtplib", "socket", "requests", "urllib", "http", "sendmail"):
        assert banned not in source, banned
        assert banned not in imports, banned

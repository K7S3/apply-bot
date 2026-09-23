"""Tests for candid.drafting.personalize (drafts only - no sending)."""

from __future__ import annotations

import inspect

from candid.drafting import personalize
from candid.drafting.personalize import apply_tokens, preview_substitutions

PROFILE = {
    "full_name": "Keshavan Seshadri",
    "target_role": "Machine Learning Engineer",
    "location": "New York, NY",
    "email": "keshavan@example.com",
    "phone": "+1 201-555-0100",
    "years_experience": "6",
    "headline": "Product-centric ML engineer",
    "linkedin": "https://linkedin.com/in/keshavan",
    "github": "https://github.com/keshavan",
}


def test_apply_tokens_substitutes_known():
    text, missing = apply_tokens(
        "Hi, I'm {full_name}, a {target_role} based in {location}.", PROFILE
    )
    assert missing == []
    assert text == "Hi, I'm Keshavan Seshadri, a Machine Learning Engineer based in New York, NY."


def test_apply_tokens_derives_first_and_last_name():
    text, missing = apply_tokens("Dear {first_name} {last_name},", PROFILE)
    assert missing == []
    assert text == "Dear Keshavan Seshadri,"


def test_apply_tokens_explicit_first_name_wins():
    profile = dict(PROFILE, first_name="Kesh")
    text, missing = apply_tokens("{first_name}", profile)
    assert (text, missing) == ("Kesh", [])


def test_apply_tokens_aliases():
    text, missing = apply_tokens("{name} seeks a {role} in {city}.", PROFILE)
    assert missing == []
    assert text == "Keshavan Seshadri seeks a Machine Learning Engineer in New York, NY."


def test_apply_tokens_reports_missing_and_preserves():
    text, missing = apply_tokens("I'm {full_name}, phone {phone}, website {website}.", PROFILE)
    assert missing == ["website"]
    assert text == "I'm Keshavan Seshadri, phone +1 201-555-0100, website {website}."


def test_apply_tokens_empty_string_counts_as_missing():
    profile = dict(PROFILE, phone="")
    text, missing = apply_tokens("Call me at {phone}.", profile)
    assert missing == ["phone"]
    assert "{phone}" in text


def test_apply_tokens_dedupes_repeated_missing():
    _, missing = apply_tokens("{github} and again {github} and {website}", {})
    assert missing == ["github", "website"]


def test_apply_tokens_no_tokens():
    assert apply_tokens("Plain text, no placeholders.", PROFILE) == (
        "Plain text, no placeholders.",
        [],
    )


def test_preview_substitutions_shows_mapping():
    context = {
        "user_name": "{full_name}",
        "role": "{target_role}",
        "company": "Acme",
    }
    preview = preview_substitutions(context, PROFILE)
    assert preview["user_name"]["value"] == "Keshavan Seshadri"
    assert preview["user_name"]["resolved"] is True
    assert preview["role"]["value"] == "Machine Learning Engineer"
    # Plain values pass through untouched.
    assert preview["company"]["value"] == "Acme"
    assert preview["company"]["resolved"] is True


def test_preview_substitutions_flags_unresolved():
    preview = preview_substitutions({"website": "{website}"}, PROFILE)
    assert preview["website"]["resolved"] is False
    assert preview["website"]["unresolved_tokens"] == ["website"]


def test_deterministic():
    a = apply_tokens("{first_name} {target_role}", PROFILE)
    b = apply_tokens("{first_name} {target_role}", PROFILE)
    assert a == b


def test_no_sending_code_in_module():
    import ast

    source = inspect.getsource(personalize)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if node.body and isinstance(node.body[0], ast.Expr):
                node.body[0].value = ast.Constant(value="")
    stripped = ast.unparse(tree).lower()
    imports = []
    for node in ast.walk(ast.parse(inspect.getsource(personalize))):
        if isinstance(node, ast.Import):
            imports.extend(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module.split(".")[0])
    for banned in ("smtplib", "socket", "requests", "urllib", "http", "sendmail"):
        assert banned not in stripped, banned
        assert banned not in imports, banned

"""Tests for candid.apply_fields (port of 3A sensitive.py classifier)."""

from candid.apply_fields import classify


def test_safe_first_name():
    assert classify("First Name") == ("safe", "first_name")


def test_safe_email():
    assert classify("Email address") == ("safe", "email")


def test_safe_phone():
    assert classify("Mobile phone") == ("safe", "phone")


def test_sensitive_sponsorship():
    assert classify("Will you now or in the future require sponsorship?") == (
        "sensitive",
        "work_authorization",
    )


def test_sensitive_desired_salary():
    assert classify("Desired salary") == ("sensitive", "compensation")


def test_sensitive_certify():
    assert classify("I certify the information above is accurate") == (
        "sensitive",
        "attestation",
    )


def test_unknown_nonsense_label():
    assert classify("Preferred dinosaur name") == ("unknown", None)


def test_sensitive_wins_over_safe():
    # Mentions salary but also looks like a safe address field;
    # sensitive must win.
    assert classify("Salary for mailing address notifications") == (
        "sensitive",
        "compensation",
    )


def test_empty_label():
    assert classify("") == ("unknown", None)
    assert classify(None) == ("unknown", None)


def test_case_insensitive():
    assert classify("FIRST NAME") == ("safe", "first_name")
    assert classify("Are you AUTHORIZED to work in the US?") == (
        "sensitive",
        "work_authorization",
    )

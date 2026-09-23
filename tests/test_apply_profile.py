"""Tests for candid.apply_profile."""

import pytest

from candid.apply_profile import (
    PROFILE_KEYS,
    ApplyProfile,
    ApplyProfileError,
    load_apply_profile,
)


FAKE_PROFILE = {
    "first_name": "Alex",
    "last_name": "Rivera",
    "email": "alex.rivera@example.com",
    "phone": "+1 555-010-2030",
}


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_profile_keys():
    assert PROFILE_KEYS == frozenset(
        {
            "first_name",
            "last_name",
            "full_name",
            "email",
            "phone",
            "address",
            "city",
            "state",
            "zip",
            "country",
            "linkedin",
            "website",
            "github",
        }
    )


def test_missing_file_raises():
    with pytest.raises(ApplyProfileError) as exc_info:
        load_apply_profile("definitely-not-a-real-profile.yaml")
    assert "profile.yaml.example" in str(exc_info.value)


def test_unknown_key_rejected(tmp_path):
    p = _write(
        tmp_path,
        "profile.yaml",
        "first_name: Alex\nfavourite_color: blue\n",
    )
    with pytest.raises(ApplyProfileError) as exc_info:
        load_apply_profile(p)
    assert "favourite_color" in str(exc_info.value)


def test_sensitive_like_key_rejected(tmp_path):
    p = _write(
        tmp_path,
        "profile.yaml",
        "first_name: Alex\ndesired_salary: 99999\n",
    )
    with pytest.raises(ApplyProfileError):
        load_apply_profile(p)


def test_valid_contact_file_loads(tmp_path):
    p = _write(
        tmp_path,
        "profile.yaml",
        "".join(f"{k}: {v}\n" for k, v in FAKE_PROFILE.items()),
    )
    profile = load_apply_profile(p)
    assert isinstance(profile, ApplyProfile)
    assert profile.value("first_name") == "Alex"
    assert profile.value("last_name") == "Rivera"
    assert profile.value("email") == "alex.rivera@example.com"
    assert profile.value("phone") == "+1 555-010-2030"


def test_value_defaults_to_empty():
    profile = ApplyProfile()
    assert profile.value("city") == ""
    assert profile.value("no_such_key") == ""


def test_values_coerced_to_str(tmp_path):
    p = _write(tmp_path, "profile.yaml", "zip: 10019\nphone: 5550102030\n")
    profile = load_apply_profile(p)
    assert profile.value("zip") == "10019"
    assert profile.value("phone") == "5550102030"

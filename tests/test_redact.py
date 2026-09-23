"""Tests for candid.redact (PII redaction engine)."""

from __future__ import annotations

import platform

from candid import redact


def _findings_map(text):
    _, findings = redact.redact_text(text)
    return {f["kind"]: f["count"] for f in findings}


def test_email_redacted():
    out, findings = redact.redact_text("contact keshavan@example.com please")
    assert "[EMAIL]" in out
    assert "keshavan@example.com" not in out
    assert _findings_map("a@b.com and c@d.org") == {"email": 2}


def test_phone_redacted():
    for raw in ["+1 (555) 123-4567", "555-123-4567", "555.123.4567", "+44 20 7946 0958"]:
        out, _ = redact.redact_text(f"call {raw} now")
        assert "[PHONE]" in out, raw
        assert raw not in out
    assert _findings_map("call 555-123-4567 or 555-987-6543") == {"phone": 2}


def test_phone_does_not_eat_dates_or_years():
    out, findings = redact.redact_text("on 2026-09-22 at 20:13:54 it broke")
    assert "[PHONE]" not in out
    assert findings == []


def test_ipv4_redacted():
    out, findings = redact.redact_text("server at 192.168.1.100 failed")
    assert "[IP]" in out and "192.168.1.100" not in out
    assert _findings_map("from 10.0.0.1 to 8.8.8.8") == {"ip": 2}


def test_ipv6_redacted():
    out, findings = redact.redact_text("addr fe80::1 is link local")
    assert "[IP]" in out and "fe80::1" not in out
    assert _findings_map("addr fe80::1 is link local") == {"ip": 1}


def test_home_paths_redacted():
    cases = [
        ("/home/keshavan/resumes/a.pdf", "<HOME>/resumes/a.pdf"),
        ("/Users/keshavan/Library/x", "<HOME>/Library/x"),
        ("C:\\Users\\keshavan\\docs\\x.txt", "<HOME>\\docs\\x.txt"),
    ]
    for raw, expected in cases:
        out, _ = redact.redact_text(f"open {raw}")
        assert expected in out, raw
        assert "keshavan" not in out
    assert _findings_map("/home/keshavan/a /Users/keshavan/b") == {"home": 2}


def test_bare_username_in_other_paths():
    out, findings = redact.redact_text(
        "src /home/alice/proj failed; cache at /tmp/alice/cache"
    )
    assert "<HOME>/proj" in out
    assert "/tmp/[USER]/cache" in out
    assert "alice" not in out
    counts = {f["kind"]: f["count"] for f in findings}
    assert counts["home"] == 1
    assert counts["username"] == 1


def test_mac_redacted():
    out, _ = redact.redact_text("mac AA:BB:CC:DD:EE:FF seen")
    assert "[MAC]" in out and "AA:BB:CC:DD:EE:FF" not in out
    assert _findings_map("AA-BB-CC-DD-EE-FF") == {"mac": 1}


def test_tokens_redacted():
    samples = [
        "api_key=supersecret123",
        "Authorization: Bearer abcdef1234567890",
        "key sk-abcdefghijklmnop123456",
        "aws AKIAIOSFODNN7EXAMPLE used",
        "token: mysecrettoken99",
    ]
    for raw in samples:
        out, _ = redact.redact_text(f"value {raw}")
        assert "[TOKEN]" in out, raw
    key_block = (
        "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSk\n"
        "-----END PRIVATE KEY-----"
    )
    out, _ = redact.redact_text(f"key:\n{key_block}")
    assert "[TOKEN]" in out and "BEGIN PRIVATE KEY" not in out
    assert _findings_map("api_key=supersecret1 and Bearer bbbbbbbb99")["token"] == 2


def test_windows_sid_redacted():
    sid = "S-1-5-21-1234567890-1234567890-1234567890-1001"
    out, _ = redact.redact_text(f"user {sid} logged in")
    assert "[SID]" in out and sid not in out
    assert _findings_map(sid) == {"sid": 1}


def test_idempotent():
    text = (
        "user keshavan@example.com called +1 (555) 123-4567 from 10.0.0.1 "
        "mac AA:BB:CC:DD:EE:FF key sk-abcdefghijklmnop123456 "
        "at /home/keshavan/x sid S-1-5-21-1-2-3-1001"
    )
    once = redact.redact_text(text)[0]
    twice = redact.redact_text(once)[0]
    assert once == twice
    # Redacting a second time finds nothing new but stays stable.
    assert redact.redact_text(twice)[0] == twice


def test_redact_argv():
    argv = ["candid", "tailor", "--email", "keshavan@example.com", "/home/keshavan/r.pdf"]
    out = redact.redact_argv(argv)
    assert out[0] == "candid"
    assert out[3] == "[EMAIL]"
    assert out[4] == "<HOME>/r.pdf"
    assert redact.redact_argv([]) == []
    assert redact.redact_argv(None) == []


def test_redact_platform_replaces_hostname():
    node = platform.node().strip()
    plat = f"Linux-6.8.0-52-generic-{node}-x86_64-with-glibc2.39"
    out = redact.redact_platform(plat)
    if node:
        assert node not in out
        assert "[HOST]" in out
    # Idempotent too.
    assert redact.redact_platform(out) == out

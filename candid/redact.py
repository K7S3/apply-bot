"""PII redaction engine for crash logs and bug reports.

Pure local string rewriting. No network calls, ever.

Redaction markers (stable and readable):
    email addresses      -> [EMAIL]
    phone-number-like    -> [PHONE]
    IPv4 / IPv6          -> [IP]
    home directory paths -> <HOME>
    usernames in paths   -> [USER]
    MAC addresses        -> [MAC]
    tokens / secrets     -> [TOKEN]
    Windows SIDs         -> [SID]

``redact_text`` is idempotent: redacting already-redacted text changes nothing.
"""

from __future__ import annotations

import platform as _platform
import re

# Finding kinds, in stable report order.
KINDS = ("token", "email", "mac", "ip", "sid", "home", "username", "phone")

# --- token / secret patterns -------------------------------------------------
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----"
)
_TOKEN_RES = (
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),  # OpenAI-style secret keys
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key ids
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"),  # GitHub tokens
    re.compile(r"\bxox[bap]-[A-Za-z0-9-]{8,}\b"),  # Slack tokens
    re.compile(
        r"(?i)\b(api[_-]?key|secret|passwd|password|pwd)\s*[:=]\s*['\"]?[^\s\"']{4,}['\"]?"
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]{8,}=*"),
    re.compile(r"(?i)\btoken\s*[:=]\s*['\"]?[^\s\"']{8,}['\"]?"),
)

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

_MAC_RE = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")

# Candidate IPv6 spans; validated by _ipv6_repl (rejects clock times like
# 20:13:54 and requires real IPv6 structure: :: compression, a hex letter,
# or a full 8-group address).
_IPV6_RE = re.compile(
    r"(?<![\w:.])([0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,})(?![\w:.])"
)
_TIME_LIKE_RE = re.compile(r"\d{1,2}:\d{2}(:\d{2})?")


def _ipv6_repl(match: re.Match) -> str:
    """Return [IP] for real IPv6 addresses, else the original text."""
    text = match.group(0)
    if _TIME_LIKE_RE.fullmatch(text):
        return text
    groups = text.split(":")
    if "::" in text or re.search(r"[a-fA-F]", text) or len(groups) == 8:
        return "[IP]"
    return text
_IPV4_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b"
)

_SID_RE = re.compile(r"\bS-1(?:-\d+){2,}\b")

# /home/<user>, /Users/<user> (prefix + user captured; rest of path preserved)
_HOME_UNIX_RE = re.compile(r"(?P<prefix>/home/|/Users/)(?P<user>[^/\\\s:;\"']+)")
# C:\Users\<user> (prefix + user captured; rest of path preserved)
_HOME_WIN_RE = re.compile(
    r"(?P<prefix>[A-Za-z]:[\\/]Users[\\/])(?P<user>[^\\/:\s\"']+)"
)

# Loose phone-number-like sequence; validated by _phone_repl (digit count, dates).
_PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d\s()./\-]{6,}\d(?!\w)")
_DATE_LIKE_RE = re.compile(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}")


def _phone_repl(match: re.Match) -> str:
    """Return [PHONE] for phone-like sequences, else the original text."""
    text = match.group(0)
    if _DATE_LIKE_RE.search(text):
        return text  # ISO-ish dates are not phone numbers
    digits = re.sub(r"\D", "", text)
    has_separator = bool(re.search(r"[+\s()./\-]", text))
    if has_separator:
        looks_like_phone = 7 <= len(digits) <= 15
    else:
        # Bare digit runs need to be long to count (avoids years, line numbers).
        looks_like_phone = 10 <= len(digits) <= 15
    return "[PHONE]" if looks_like_phone else text


def redact_text(text: str) -> tuple[str, list[dict]]:
    """Redact PII from ``text``.

    Returns ``(redacted_text, findings)`` where each finding is
    ``{"kind": <kind>, "count": <n>}`` for kinds that were redacted.
    Idempotent: redacting the output again changes nothing.
    """
    counts: dict[str, int] = {}
    seen_users: list[str] = []

    def _record(kind: str, n: int) -> None:
        if n:
            counts[kind] = counts.get(kind, 0) + n

    def _sub(pattern: re.Pattern, repl, text: str) -> tuple[str, int]:
        n = 0

        def _inner(match: re.Match) -> str:
            nonlocal n
            new = repl(match) if callable(repl) else repl
            if new != match.group(0):
                n += 1
            return new

        return pattern.sub(_inner, text), n

    out = text or ""

    # 1. Private key blocks and token/secret patterns -> [TOKEN]
    out, n = _sub(_PRIVATE_KEY_RE, "[TOKEN]", out)
    total_tokens = n
    for token_re in _TOKEN_RES:
        out, n = _sub(token_re, "[TOKEN]", out)
        total_tokens += n
    _record("token", total_tokens)

    # 2. Emails -> [EMAIL]
    out, n = _sub(_EMAIL_RE, "[EMAIL]", out)
    _record("email", n)

    # 3. MAC addresses -> [MAC] (before IP passes so colons are gone)
    out, n = _sub(_MAC_RE, "[MAC]", out)
    _record("mac", n)

    # 4. IPv6 then IPv4 -> [IP]
    out, n = _sub(_IPV6_RE, _ipv6_repl, out)
    ip_count = n
    out, n = _sub(_IPV4_RE, "[IP]", out)
    ip_count += n
    _record("ip", ip_count)

    # 5. Windows SIDs -> [SID] (before phones: SID digit runs look phone-like)
    out, n = _sub(_SID_RE, "[SID]", out)
    _record("sid", n)

    # 6. Home directory paths -> <HOME>, remembering usernames for pass 7.
    def _home_repl(prefix: str, match: re.Match) -> str:
        user = match.group("user")
        if user and user not in seen_users:
            seen_users.append(user)
        return "<HOME>"

    out, n = _sub(_HOME_UNIX_RE, lambda m: _home_repl("/home/", m), out)
    home_count = n
    out, n = _sub(_HOME_WIN_RE, lambda m: _home_repl("win", m), out)
    home_count += n
    _record("home", home_count)

    # 7. Bare usernames seen in home paths, appearing in other path contexts.
    username_count = 0
    for user in seen_users:
        user_re = re.compile(r"(?<=[/\\])" + re.escape(user) + r"(?=[/\\]|$|[\s\"'])")
        out, n = _sub(user_re, "[USER]", out)
        username_count += n
    _record("username", username_count)

    # 8. Phone-number-like sequences -> [PHONE]
    out, n = _sub(_PHONE_RE, _phone_repl, out)
    _record("phone", n)

    findings = [{"kind": kind, "count": counts[kind]} for kind in KINDS if counts.get(kind)]
    return out, findings


def redact_argv(argv: list[str] | tuple[str, ...] | None) -> list[str]:
    """Redact PII from each argv entry (paths get <HOME>)."""
    return [redact_text(arg)[0] for arg in (argv or [])]


def redact_platform(platform_string: str | None) -> str:
    """Redact a platform string, replacing the hostname (node) with [HOST]."""
    text, _ = redact_text(platform_string or "")
    node = _platform.node().strip()
    if node:
        text = text.replace(node, "[HOST]")
    return text

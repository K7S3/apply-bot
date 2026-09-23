"""Deterministic email-draft quality checks and send-time guidance.

``check(draft)`` runs a fixed set of heuristic checks over a draft
``{"subject": ..., "body": ...}`` and returns a list of
``{"check", "severity", "message"}`` findings (empty list means clean).
``best_send_time()`` returns a documented send-time heuristic.

No sending, no network, no LLM: everything here is pure local heuristics.
"""

import re

# ---------------------------------------------------------------------------
# Check definitions
# ---------------------------------------------------------------------------

_SPAM_WORDS = ("free", "guarantee", "act now")

_MAX_SUBJECT_CHARS = 60
_MAX_BODY_WORDS = 200
_MAX_EXCLAMATIONS = 2
_MAX_CAPS_RATIO = 0.30

_GREETING_RE = re.compile(
    r"^(hi|hello|hey|dear|good morning|good afternoon|good evening)\b",
    re.IGNORECASE,
)

_SIGNOFF_RE = re.compile(
    r"^(best|regards|thank you|thanks|sincerely|cheers|"
    r"warm regards|kind regards)\b",
    re.IGNORECASE,
)


def _caps_ratio(text):
    letters = re.findall(r"[A-Za-z]", text)
    if not letters:
        return 0.0
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters)


def check(draft):
    """Run quality checks on a draft.

    Args:
        draft: dict with ``subject`` and ``body`` strings.

    Returns:
        list of ``{"check", "severity", "message"}`` dicts. Severity is one
        of ``"error"``, ``"warn"``, ``"info"``. An empty list means the
        draft passed every check.
    """
    subject = (draft.get("subject") or "").strip()
    body = (draft.get("body") or "").strip()
    findings = []

    # --- subject checks ----------------------------------------------------
    if not subject:
        findings.append({
            "check": "subject_present",
            "severity": "error",
            "message": "Subject line is missing or empty.",
        })
    elif len(subject) > _MAX_SUBJECT_CHARS:
        findings.append({
            "check": "subject_length",
            "severity": "warn",
            "message": ("Subject is %d characters; keep it under %d so it "
                        "is not cut off in inboxes." % (len(subject),
                                                         _MAX_SUBJECT_CHARS)),
        })

    # --- body length -------------------------------------------------------
    words = len(body.split())
    if words > _MAX_BODY_WORDS:
        findings.append({
            "check": "body_length",
            "severity": "warn",
            "message": ("Body is %d words; consider trimming below %d words "
                        "for a cold outreach email." % (words,
                                                         _MAX_BODY_WORDS)),
        })

    # --- spam triggers -----------------------------------------------------
    lowered = body.lower()
    for word in _SPAM_WORDS:
        if word in lowered:
            findings.append({
                "check": "spam_words",
                "severity": "warn",
                "message": ("Contains the spam-trigger phrase %r, which can "
                            "trip spam filters." % word),
            })

    if body.count("!") > _MAX_EXCLAMATIONS:
        findings.append({
            "check": "exclamation_marks",
            "severity": "warn",
            "message": ("Contains %d exclamation marks; more than %d reads "
                        "as salesy." % (body.count("!"), _MAX_EXCLAMATIONS)),
        })

    if _caps_ratio(body) > _MAX_CAPS_RATIO:
        findings.append({
            "check": "excessive_caps",
            "severity": "warn",
            "message": "Excessive capitalisation reads as shouting; "
                       "use normal sentence case.",
        })

    # --- greeting / signoff ------------------------------------------------
    lines = [ln for ln in body.splitlines() if ln.strip()]
    if lines and not _GREETING_RE.match(lines[0].strip()):
        findings.append({
            "check": "greeting_present",
            "severity": "info",
            "message": "No greeting detected on the first line "
                       "(e.g. 'Hi <name>,').",
        })
    tail = [ln.strip() for ln in lines[-3:]]
    if not any(_SIGNOFF_RE.match(ln) for ln in tail):
        findings.append({
            "check": "signoff_present",
            "severity": "info",
            "message": "No signoff detected at the end "
                       "(e.g. 'Best,').",
        })

    return findings


# ---------------------------------------------------------------------------
# Send-time heuristic
# ---------------------------------------------------------------------------

def best_send_time():
    """Return a simple, documented send-time heuristic.

    Returns:
        dict with ``weekday``, ``window``, and ``rationale``. Assumes the
        recipient's local timezone; adjust when the recipient's timezone is
        known to differ.
    """
    return {
        "weekday": "Tuesday-Thursday",
        "window": "9:00-11:00 AM",
        "rationale": (
            "Mid-week mornings are the standard B2B outreach window: "
            "recipients have cleared the Monday backlog and are still in "
            "active work mode, before Friday wind-down. Times are given in "
            "the recipient's local timezone (assumed); shift the window if "
            "the recipient is in a different timezone. Avoid weekends and "
            "late-night sends, which read as low-effort or automated."
        ),
    }

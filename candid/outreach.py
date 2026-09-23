"""Personalized outreach draft generator (batch-68, feature W2).

Builds grounded, send-ready-as-text drafts for reaching out to hiring
managers. Groundedness is critical: every specific in a draft must come
from the hiring-manager dossier (candid.hm) or from profile experience
bullets (candid.profile). Nothing is invented. If the dossier has no
usable specifics, the draft says so plainly and degrades to a shorter
honest draft instead of faking a hook.

Drafts only - nothing here sends email or messages anywhere.
"""

from __future__ import annotations

import json
from pathlib import Path

from candid import config as C

# ---------------------------------------------------------------------------
# public constants
# ---------------------------------------------------------------------------

TONES = ("warm", "concise", "formal")
CHANNELS = ("email", "linkedin", "dm")
TEMPLATES = ("specific-hook", "mutual-connection", "recent-news")

LINKEDIN_MAX_CHARS = 300

_PLACEHOLDER_TOKENS = (
    "[Your Name]", "[Name]", "[Company]", "[Role]", "[Mutual]",
    "{{", "}}", "TODO", "XXX",
)


class OutreachError(Exception):
    """Raised when an outreach draft cannot be built from the given inputs."""


# ---------------------------------------------------------------------------
# dossier access (defensive - candid.hm is being built in parallel)
# ---------------------------------------------------------------------------

def _get_dossier_fn():
    """Return candid.hm.get_dossier, or raise OutreachError if unavailable."""
    try:
        from candid import hm
    except ImportError as exc:
        raise OutreachError(
            "Hiring-manager dossiers are unavailable: candid.hm could not be "
            "imported. The hm module is still being built; try again later."
        ) from exc
    fn = getattr(hm, "get_dossier", None)
    if not callable(fn):
        raise OutreachError(
            "Hiring-manager dossiers are unavailable: candid.hm.get_dossier "
            "is missing. The hm module is still being built; try again later."
        )
    return fn


def _coalesce(value):
    return str(value or "").strip()


# ---------------------------------------------------------------------------
# grounded extraction helpers
# ---------------------------------------------------------------------------

def _first_sentence(text):
    """First sentence of a blob of text, for use as a hook quote."""
    text = _coalesce(text)
    if not text:
        return ""
    for sep in (". ", ".\n", "! ", "? "):
        if sep in text:
            head = text.split(sep, 1)[0]
            return (head + sep.strip()[0]).strip() if head else text
    return text[:160].strip()


def _dossier_hooks(dossier):
    """Concrete, quotable specifics from the dossier: (dossier_key, text)."""
    hooks = []
    notes = _first_sentence(dossier.get("notes"))
    if notes:
        hooks.append(("notes", notes))
    for interest in dossier.get("interests") or []:
        text = _coalesce(interest)
        if text and not any(text == h[1] for h in hooks):
            hooks.append(("interests", text))
    for src in dossier.get("sources") or []:
        if isinstance(src, dict):
            label = _coalesce(src.get("label"))
            url = _coalesce(src.get("url"))
        else:
            label, url = _coalesce(src), ""
        if label and not any(label == h[1] for h in hooks):
            hooks.append(("sources", label + (f" ({url})" if url else "")))
    return hooks


def _profile_anchor(profile):
    """One grounded profile specific: most recent experience entry.

    Returns (anchor_text, reference_note). Never invents metrics.
    """
    exp = profile.get("experience") or []
    first = exp[0] if exp else {}
    title = _coalesce(first.get("title")) or "engineer"
    company = _coalesce(first.get("company"))
    bullets = [b for b in (first.get("bullets") or []) if _coalesce(b)]
    anchor = f"{title}" + (f" at {company}" if company else "")
    if bullets:
        anchor += f"; {_first_sentence(bullets[0]).rstrip('.!?')}"
    return anchor, "experience"


def _profile_title(profile) -> str:
    """Most recent experience title, for a/an article agreement."""
    exp = profile.get("experience") or []
    first = exp[0] if exp else {}
    return _coalesce(first.get("title")) or "engineer"


def _article(word: str) -> str:
    """'a' or 'an' for a job title ('an ML Engineer', 'a designer')."""
    w = _coalesce(word).strip()
    if not w:
        return "a"
    first = w.split()[0]
    if len(first) > 1 and first.isupper():
        # Acronym: go by the pronounced first letter (F, L, M, N, S, X...)
        return "an" if first[0] in "AEFHILMNORSX" else "a"
    return "an" if w[0].lower() in "aeiou" else "a"


def _hook_inline(hook: str) -> str:
    """Normalize a hook for inline use: 'Gave a talk on X.' -> 'gave a talk on X'."""
    text = _coalesce(hook).strip()
    was_sentence = text != text.rstrip(".!?")
    text = text.rstrip(".!?").strip()
    if was_sentence and text:
        text = text[0].lower() + text[1:]
    return text


def _validate(profile, dossier, channel, tone, template):
    if channel not in CHANNELS:
        raise OutreachError(
            f"Unknown channel {channel!r}. Choose one of: {', '.join(CHANNELS)}."
        )
    if tone not in TONES:
        raise OutreachError(
            f"Unknown tone {tone!r}. Choose one of: {', '.join(TONES)}."
        )
    if template not in TEMPLATES:
        raise OutreachError(
            f"Unknown template {template!r}. Choose one of: {', '.join(TEMPLATES)}."
        )
    if not isinstance(profile, dict) or not _coalesce(profile.get("name")):
        raise OutreachError(
            "Profile is missing a name; onboarding data is required."
        )
    if not isinstance(dossier, dict):
        raise OutreachError("Dossier must be a dict from candid.hm.get_dossier().")


def _greeting(tone, hm_name):
    first = hm_name.split()[0] if hm_name else ""
    if tone == "formal":
        return f"Dear {hm_name}," if hm_name else "Hello,"
    return f"Hi {first}," if first else "Hi there,"


def _signoff(tone, name):
    word = {"warm": "Best regards", "concise": "Thanks", "formal": "Respectfully"}[tone]
    return f"{word},\n{name}"


def _fit_linkedin(text):
    """Hard cap a message at LINKEDIN_MAX_CHARS characters."""
    if len(text) <= LINKEDIN_MAX_CHARS:
        return text
    return text[: LINKEDIN_MAX_CHARS - 3].rstrip() + "..."


def _assert_no_placeholders(text, where):
    for token in _PLACEHOLDER_TOKENS:
        if token in text:
            raise OutreachError(
                f"Generated {where} contains an unfilled placeholder token "
                f"{token!r}; refusing to emit an unfinished draft."
            )


# ---------------------------------------------------------------------------
# template bodies
# ---------------------------------------------------------------------------

def _degraded_body(profile, dossier, role, tone, references):
    """Honest short draft used when the dossier has no usable specifics."""
    name = _coalesce(profile["name"])
    hm_name = _coalesce(dossier.get("name"))
    company = _coalesce(dossier.get("company"))
    team = _coalesce(dossier.get("team"))
    anchor, _ = _profile_anchor(profile)
    title = _profile_title(profile)
    if company:
        references.append("company")
    if team:
        references.append("team")
    greeting = _greeting(tone, hm_name)
    role_bit = f" about the {role} role" if role else ""
    team_bit = f" on the {team} team" if team else ""
    company_bit = f" at {company}" if company else ""
    body = (
        f"{greeting}\n\n"
        f"I will be upfront: I could not find much public detail about "
        f"your work{team_bit}{company_bit}, so I have no specific hook here, "
        f"just a straightforward introduction{role_bit}.\n\n"
        f"I am {_article(title)} {anchor}, and I would welcome a brief conversation about "
        f"whether my background fits what your team needs.\n\n"
        f"{_signoff(tone, name)}"
    )
    return body


def _template_specific_hook(profile, dossier, role, tone, hooks, references):
    key, hook = hooks[0]
    references.append(key)
    name = _coalesce(profile["name"])
    hm_name = _coalesce(dossier.get("name"))
    company = _coalesce(dossier.get("company"))
    team = _coalesce(dossier.get("team"))
    if company:
        references.append("company")
    anchor, _ = _profile_anchor(profile)
    title = _profile_title(profile)
    role_bit = f"the {role} role" if role else "an open role"
    team_bit = f" on the {team} team" if team else ""
    company_bit = f" at {company}" if company else ""
    body = (
        f"{_greeting(tone, hm_name)}\n\n"
        f"Your note about {_hook_inline(hook)} stood out to me{team_bit}{company_bit} - "
        f"it is closely related to my work as {_article(title)} {anchor}.\n\n"
        f"I am interested in {role_bit}, and I would love a brief chat "
        f"about how your team approaches problems like this.\n\n"
        f"{_signoff(tone, name)}"
    )
    return body


def _template_mutual_connection(profile, dossier, role, tone, hooks,
                                mutual_connection, references):
    if not _coalesce(mutual_connection):
        raise OutreachError(
            "The 'mutual-connection' template needs a named mutual connection: "
            "pass mutual_connection='Full Name'. Refusing to invent one."
        )
    name = _coalesce(profile["name"])
    hm_name = _coalesce(dossier.get("name"))
    company = _coalesce(dossier.get("company"))
    team = _coalesce(dossier.get("team"))
    conn = _coalesce(mutual_connection)
    if company:
        references.append("company")
    anchor, _ = _profile_anchor(profile)
    title = _profile_title(profile)
    hook_bit = ""
    if hooks:
        key, hook = hooks[0]
        references.append(key)
        hook_bit = f" I also noticed your note about {_hook_inline(hook)}, which connects to my work.\n\n"
    role_bit = f"the {role} role" if role else "an open role"
    team_bit = f" on the {team} team" if team else ""
    company_bit = f" at {company}" if company else ""
    body = (
        f"{_greeting(tone, hm_name)}\n\n"
        f"{conn} suggested I reach out to you{team_bit}{company_bit}. "
        f"I am {_article(title)} {anchor}, and I am interested in {role_bit}.{hook_bit}\n"
        f"Would you be open to a short conversation next week?\n\n"
        f"{_signoff(tone, name)}"
    )
    return body


def _template_recent_news(profile, dossier, role, tone, hooks, references):
    source_hooks = [h for h in hooks if h[0] == "sources"]
    if not source_hooks:
        return None  # caller degrades
    references.append("sources")
    name = _coalesce(profile["name"])
    hm_name = _coalesce(dossier.get("name"))
    company = _coalesce(dossier.get("company"))
    team = _coalesce(dossier.get("team"))
    if company:
        references.append("company")
    _, source_text = source_hooks[0]
    anchor, _ = _profile_anchor(profile)
    title = _profile_title(profile)
    role_bit = f"the {role} role" if role else "an open role"
    team_bit = f" on the {team} team" if team else ""
    company_bit = f" at {company}" if company else ""
    body = (
        f"{_greeting(tone, hm_name)}\n\n"
        f"I came across {source_text}{team_bit}{company_bit}, and it "
        f"prompted me to reach out. As {_article(title)} {anchor}, the direction described "
        f"there overlaps with what I do day to day.\n\n"
        f"I am interested in {role_bit} and would value a brief chat about "
        f"what the team is working on next.\n\n"
        f"{_signoff(tone, name)}"
    )
    return body


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def draft_outreach(profile, dossier, role="", channel="email", tone="warm",
                   template="specific-hook", mutual_connection=None):
    """Draft one outreach message grounded in the dossier and profile.

    Returns {"subject" (email only), "body", "template_used", "references"}.
    "references" lists the dossier keys actually used. LinkedIn messages are
    hard-capped at 300 characters.
    """
    _validate(profile, dossier, channel, tone, template)

    hooks = _dossier_hooks(dossier)
    references = ["name"] if _coalesce(dossier.get("name")) else []

    if template == "specific-hook":
        body = (_template_specific_hook(profile, dossier, role, tone, hooks, references)
                if hooks else _degraded_body(profile, dossier, role, tone, references))
        degraded = not hooks
    elif template == "mutual-connection":
        body = _template_mutual_connection(
            profile, dossier, role, tone, hooks, mutual_connection, references)
        degraded = False
    else:  # recent-news
        body = _template_recent_news(profile, dossier, role, tone, hooks, references)
        if body is None:
            body = _degraded_body(profile, dossier, role, tone, references)
            degraded = True
        else:
            degraded = False

    template_used = "degraded-honest" if degraded else template

    subject = None
    if channel == "email":
        hm_company = _coalesce(dossier.get("company"))
        pname = _coalesce(profile["name"])
        if role and hm_company:
            subject = f"{role} at {hm_company} - introduction from {pname}"
        elif role:
            subject = f"Introduction from {pname} re: {role}"
        elif hm_company:
            subject = f"Introduction from {pname} ({hm_company})"
        else:
            subject = f"Introduction from {pname}"

    if channel == "linkedin":
        body = _fit_linkedin(body)

    _assert_no_placeholders(body, "body")
    if subject:
        _assert_no_placeholders(subject, "subject")

    result = {
        "body": body,
        "template_used": template_used,
        "references": references,
    }
    if channel == "email":
        result["subject"] = subject
    return result


def outreach_variants(profile, dossier, role=""):
    """Return 3 labeled draft variants: LinkedIn request, short DM, full email.

    Each variant carries a "when_to_use" note explaining the situation it
    fits. Drafts only; nothing is sent.
    """
    variants = []

    request = draft_outreach(
        profile, dossier, role=role, channel="linkedin",
        tone="warm", template="specific-hook",
    )
    variants.append({
        "label": "linkedin connection request",
        "channel": "linkedin",
        "when_to_use": (
            "First touch when you are not connected yet. Keep it under "
            "300 characters; lead with one concrete dossier hook."
        ),
        **request,
    })

    dm = draft_outreach(
        profile, dossier, role=role, channel="dm",
        tone="concise", template="specific-hook",
    )
    variants.append({
        "label": "short DM",
        "channel": "dm",
        "when_to_use": (
            "Follow-up direct message once connected (LinkedIn, email reply, "
            "or recruiter thread). Shorter than email, still grounded in one "
            "specific hook."
        ),
        **dm,
    })

    email = draft_outreach(
        profile, dossier, role=role, channel="email",
        tone="warm", template="specific-hook",
    )
    variants.append({
        "label": "full email",
        "channel": "email",
        "when_to_use": (
            "Full cold email when you have the hiring manager's address. "
            "Includes a subject line and the most complete grounded pitch."
        ),
        **email,
    })
    return variants


def build_from_files(profile_path=None, dossier_ref=None):
    """Load profile.json and a hiring-manager dossier from disk/config.

    Returns (profile, dossier). Raises OutreachError with a clear message
    when anything is missing or unreadable.
    """
    from candid import profile as P

    path = Path(profile_path) if profile_path else C.PROFILE_PATH
    if not path.exists():
        raise OutreachError(
            f"Profile file not found at {path}. Run onboarding first so "
            "profile.json exists under the candid data dir."
        )
    try:
        profile = P.load_profile(path)
    except Exception as exc:
        raise OutreachError(f"Could not load profile from {path}: {exc}") from exc
    if not isinstance(profile, dict) or not _coalesce(profile.get("name")):
        raise OutreachError(
            f"Profile at {path} has no usable 'name'; re-run onboarding."
        )

    if not _coalesce(dossier_ref):
        raise OutreachError(
            "dossier_ref is required: pass the hiring-manager reference "
            "(name or id) used by candid.hm.get_dossier()."
        )
    get_dossier = _get_dossier_fn()
    try:
        dossier = get_dossier(dossier_ref)
    except OutreachError:
        raise
    except Exception as exc:
        raise OutreachError(
            f"Could not load dossier for {dossier_ref!r}: {exc}"
        ) from exc
    if not dossier:
        raise OutreachError(
            f"No dossier found for {dossier_ref!r}. Check the reference and "
            "make sure the hiring-manager dossier was built."
        )
    return profile, dossier

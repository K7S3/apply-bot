"""Token personalization for candid drafts.

Replaces ``{tokens}`` in draft text with values from a user profile dict
(loaded from ``candid_data/profile.json`` by convention, but any dict
works). No LLM, no network: pure string substitution.

Canonical tokens mirror common profile keys:

=================  =====================================================
token              profile source
=================  =====================================================
``{full_name}``    ``profile["full_name"]``
``{first_name}``   ``profile["first_name"]`` (or derived from full_name)
``{last_name}``    ``profile["last_name"]`` (or derived from full_name)
``{target_role}``  ``profile["target_role"]``
``{location}``     ``profile["location"]``
``{email}``        ``profile["email"]``
``{phone}``        ``profile["phone"]``
``{years_experience}`` ``profile["years_experience"]``
``{headline}``     ``profile["headline"]``
``{linkedin}``     ``profile["linkedin"]``
``{github}``       ``profile["github"]``
``{website}``      ``profile["website"]``
=================  =====================================================
"""

from __future__ import annotations

from string import Formatter

_FORMATTER = Formatter()

#: Tokens recognized by :func:`apply_tokens`, mapped to the profile key
#: that provides their value. A profile key maps to itself; aliases map
#: to the canonical key.
TOKEN_SOURCES: dict[str, str] = {
    "full_name": "full_name",
    "first_name": "first_name",
    "last_name": "last_name",
    "target_role": "target_role",
    "location": "location",
    "email": "email",
    "phone": "phone",
    "years_experience": "years_experience",
    "headline": "headline",
    "linkedin": "linkedin",
    "github": "github",
    "website": "website",
    # Friendly aliases: also accepted as tokens.
    "name": "full_name",
    "role": "target_role",
    "city": "location",
    "years": "years_experience",
}


def _resolve(token: str, profile: dict) -> object:
    """Resolve a single token against a profile dict.

    Returns the value, or ``None`` when the profile has no usable value
    for it. ``first_name``/``last_name`` fall back to splitting
    ``full_name`` when the explicit keys are absent.
    """
    key = TOKEN_SOURCES.get(token, token)
    value = profile.get(key)
    if value is not None and value != "":
        return value
    if token in ("first_name", "last_name"):
        full = profile.get("full_name") or ""
        parts = str(full).split()
        if parts:
            return parts[0] if token == "first_name" else parts[-1]
    return None


def apply_tokens(text: str, profile: dict) -> tuple[str, list[str]]:
    """Substitute ``{tokens}`` in ``text`` from ``profile``.

    Args:
        text: draft text (or subject line) containing ``{token}``
            placeholders.
        profile: mapping of profile keys to values, e.g.
            ``{"full_name": "Keshavan Seshadri", "target_role": "MLE", ...}``.

    Returns:
        ``(filled_text, missing)`` where ``missing`` lists, in order of
        first appearance, the tokens that could not be resolved. Those
        tokens are left verbatim (``{token}``) in the returned text.

    This function never sends anything and never touches the network.
    """
    missing: list[str] = []
    parts: list[str] = []
    for literal, field, fmt, conv in _FORMATTER.parse(text):
        parts.append(literal)
        if field is None:
            continue
        value = _resolve(field, profile) if not (conv or fmt) else None
        if value is None:
            if field not in missing:
                missing.append(field)
            parts.append("{" + field + "}")
        else:
            parts.append(str(value))
    return "".join(parts), missing


def preview_substitutions(context: dict, profile: dict) -> dict:
    """Preview how tokens in ``context`` values resolve against ``profile``.

    For each key in ``context``, shows ``{"value": ..., "resolved": bool,
    "source": <profile key or None>}``. Any ``{token}`` found inside a
    context value is also expanded inline (so users can see exactly what
    will land in the final draft).

    Args:
        context: the draft context dict (placeholder -> value).
        profile: the user profile dict.

    Returns:
        dict mapping context key -> preview info dict.
    """
    preview: dict[str, dict] = {}
    for key, value in context.items():
        if isinstance(value, str) and "{" in value:
            expanded, missing = apply_tokens(value, profile)
        else:
            expanded, missing = value, []
        token = key if key in TOKEN_SOURCES else None
        source = TOKEN_SOURCES.get(key) if token else None
        preview[key] = {
            "value": expanded,
            "resolved": not missing and expanded not in (None, ""),
            "source": source,
            "unresolved_tokens": missing,
        }
    return preview

"""The "why the switch" cover-letter generator for career switchers.

- ``switch_paragraph(profile_summary, target_role, company)``: one concise
  paragraph covering the through-line from past work to the target role,
  why this company, and what the switcher brings. Built strictly from the
  facts you supply in ``profile_summary``; anything unknown is marked
  ``[PLACEHOLDER]`` instead of being invented.
- ``full_switch_letter(...)``: greeting + switch paragraph + closing,
  assembled into a complete cover-letter draft. Drafts only, never sends.

``profile_summary`` is a dict with any of these optional keys::

    past_role, past_domain, years_experience (int or str),
    transferable_skills (list of str), target_strengths (list of str),
    motivation (str: why the new field), company_note (str: why this company),
    location, links (list of str)

Deterministic and offline: no network, no paid APIs, no LLMs.
"""

from __future__ import annotations

__all__ = [
    "SwitchLetterError",
    "PLACEHOLDER",
    "switch_paragraph",
    "full_switch_letter",
]


class SwitchLetterError(Exception):
    """Raised when a cover letter cannot be drafted (bad input)."""


PLACEHOLDER = "[PLACEHOLDER]"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(summary: dict, key: str) -> str:
    """Non-empty string value for key, or "" when missing/blank."""
    val = summary.get(key)
    if val is None:
        return ""
    text = str(val).strip()
    return text


def _as_list(value) -> list[str]:
    """Coerce a scalar or list into a list of non-empty strings."""
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple)) else [value]
    return [str(i).strip() for i in items if str(i).strip()]


def _oxford(items: list[str]) -> str:
    """Join a list like 'a', 'a and b', 'a, b, and c'."""
    items = list(items)
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _sentence(text: str) -> str:
    """Ensure trailing sentence punctuation."""
    text = text.strip()
    if text and text[-1] not in ".!?":
        text += "."
    return text


# ---------------------------------------------------------------------------
# The switch paragraph
# ---------------------------------------------------------------------------

def switch_paragraph(profile_summary: dict, target_role: str, company: str) -> str:
    """Build the one "why the switch" paragraph.

    Covers, in order: the through-line from past work, why the target field,
    what the switcher brings, and why this company. Every claim is drawn
    from ``profile_summary``; missing facts become ``[PLACEHOLDER]``.
    """
    if not isinstance(profile_summary, dict):
        raise SwitchLetterError("profile_summary must be a dict.")
    target_role = (target_role or "").strip()
    company = (company or "").strip()
    if not target_role:
        raise SwitchLetterError("target_role is required.")
    if not company:
        raise SwitchLetterError("company is required.")

    sentences: list[str] = []

    # 1. The pivot: past work -> target role.
    past_role = _get(profile_summary, "past_role")
    past_domain = _get(profile_summary, "past_domain")
    years = _get(profile_summary, "years_experience")
    if past_role and past_domain:
        tenure = f"After {years} years" if years else "After a number of years"
        sentences.append(
            f"{tenure} as a {past_role} in {past_domain}, "
            f"I am making a deliberate move into {target_role}."
        )
    elif past_role:
        sentences.append(
            f"After building my career as a {past_role}, "
            f"I am making a deliberate move into {target_role}."
        )
    else:
        sentences.append(
            f"I am making a deliberate move into {target_role}. "
            f"My previous role: {PLACEHOLDER}."
        )

    # 2. The through-line: transferable skills.
    skills = _as_list(profile_summary.get("transferable_skills"))
    if skills:
        sentences.append(
            f"The through-line across my work has been {_oxford(skills)}, "
            f"strengths that map directly onto {target_role} work."
        )
    else:
        sentences.append(f"My transferable strengths: {PLACEHOLDER}.")

    # 3. The motivation: why the new field. Copied verbatim, never invented.
    motivation = _get(profile_summary, "motivation")
    if motivation:
        sentences.append(_sentence(motivation))
    else:
        sentences.append(f"What draws me to this field: {PLACEHOLDER}.")

    # 4. What the switcher brings to this company.
    strengths = _as_list(profile_summary.get("target_strengths")) or skills
    if strengths:
        sentences.append(
            f"What I bring to {company}: {_oxford(strengths)}, "
            f"applied to {target_role} problems from day one."
        )
    else:
        sentences.append(f"What I bring to {company}: {PLACEHOLDER}.")

    # 5. Why this company specifically.
    company_note = _get(profile_summary, "company_note")
    if company_note:
        sentences.append(
            _sentence(f"What draws me to {company} specifically: {company_note}")
        )
    else:
        sentences.append(f"Why {company} specifically: {PLACEHOLDER}.")

    return " ".join(sentences)


# ---------------------------------------------------------------------------
# Full letter assembly (drafts only, never sends)
# ---------------------------------------------------------------------------

def full_switch_letter(profile_summary: dict, target_role: str, company: str,
                       name: str = "", greeting: str = "Dear Hiring Manager",
                       email: str = "", phone: str = "") -> str:
    """Assemble a complete cover-letter draft from the switch paragraph.

    Returns the draft text. Nothing is ever sent automatically; copy, edit,
    and send it yourself.
    """
    paragraph = switch_paragraph(profile_summary, target_role, company)
    greeting = (greeting or "Dear Hiring Manager").strip() or "Dear Hiring Manager"
    company = company.strip()

    lines = [
        f"{greeting},",
        "",
        f"I am applying for the {target_role.strip()} position at {company}.",
        "",
        paragraph,
        "",
        "I would welcome the chance to discuss how my background maps to the "
        f"team's needs at {company}. Thank you for your consideration.",
        "",
        "Sincerely,",
        (name or "").strip() or PLACEHOLDER,
    ]
    contact = " | ".join(p for p in ((email or "").strip(), (phone or "").strip()) if p)
    if contact:
        lines.append(contact)
    lines.extend([
        "",
        "---",
        "Draft only: generated by candid from the facts you supplied; "
        "it was never sent automatically.",
    ])
    return "\n".join(lines)

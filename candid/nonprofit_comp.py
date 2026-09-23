"""Nonprofit compensation notes: honest, labeled context for offers from
mission-driven employers.

Every quantitative claim here comes from function inputs. Anything that is
not user-supplied is labeled as general context, never as a fact about a
specific employer. No network calls, no fabricated figures.
"""

from __future__ import annotations


def nonprofit_comp_note(title: str, company: str, salary_text: str = "",
                        sector: str = "nonprofit",
                        loan_balance: float = 0.0) -> dict:
    """Build an honest compensation note for a nonprofit-sector role.

    Args:
        title: Role title (echoed only; never used to invent a number).
        company: Employer name (echoed only; no employer data fabricated).
        salary_text: Posted salary text, if the employer provided one.
        sector: Sector label shown in the notes ("nonprofit" default).
        loan_balance: Optional user-provided federal loan balance, used
            only to show the PSLF arithmetic formula with their own number.

    Returns:
        {"notes": [str, ...], "sources": [str, ...]} where every note is
        labeled and no salary figure is invented.
    """
    notes: list[str] = []
    sources: list[str] = []

    if salary_text and salary_text.strip():
        text = salary_text.strip()
        notes.append(
            f"Posted range for '{title}' at {company}: {text}. "
            f"This is the employer's stated range; treat it as the starting "
            f"point, not a verdict."
        )
        notes.append(
            f"{sector.capitalize()} roles in this family typically price "
            f"below for-profit medians; verify the posted range against "
            f"levels.fyi and DOL H-1B LCA data where available before "
            f"deciding whether it is competitive."
        )
        sources.append("Employer posting (salary_text as provided)")
        sources.append("levels.fyi (suggested cross-check)")
        sources.append("DOL H-1B LCA disclosure data (suggested cross-check)")
    else:
        notes.append(
            f"No salary range was provided for '{title}' at {company}. Many "
            f"nonprofits omit ranges; ask for the band early in the process "
            f"so you are not negotiating against yourself."
        )
        notes.append(
            f"When the range is missing, ask: 'What is the approved salary "
            f"band for this role?' A vague answer is itself information."
        )
        sources.append("No posted range (salary_text not provided)")

    # PSLF value framing: no dollar value invented; formula uses their number.
    pslf = (
        "PSLF (Public Service Loan Forgiveness): qualifying employment at a "
        "501(c)(3) nonprofit or government employer can make remaining "
        "federal direct loan balance forgiven after 120 qualifying monthly "
        "payments. Price that into total comp as a real benefit, not a "
        "footnote. Verify your eligibility and payment count at "
        "studentaid.gov."
    )
    if loan_balance and loan_balance > 0:
        pslf += (
            f" With your stated balance of ${loan_balance:,.2f}, the rough "
            f"arithmetic is: forgiven amount ~= loan_balance - (payments "
            f"already counting toward 120 x your monthly payment). See "
            f"estimate_pslf_value() for the labeled formula."
        )
    notes.append(pslf)
    sources.append("studentaid.gov (PSLF eligibility)")

    notes.append(
        "Nonprofit offers often have more give on benefits, title scope, "
        "professional development budgets, and work flexibility than on "
        "base salary. Negotiate the whole package, not just the number."
    )
    sources.append("candid.nonprofit_comp (general nonprofit context)")

    return {"notes": notes, "sources": sources}


def render_nonprofit_comp(note: dict) -> str:
    """Render a nonprofit comp note as a compact CLI block."""
    lines = ["== Nonprofit comp note =="]
    for i, text in enumerate(note.get("notes", []), start=1):
        lines.append(f"{i}. {text}")
    sources = note.get("sources", [])
    if sources:
        lines.append("")
        lines.append("Sources: " + "; ".join(sources))
    return "\n".join(lines)


def nonprofit_negotiation_guide(role: str, constraints: str = "") -> str:
    """Return Markdown-ish negotiation guidance for a nonprofit-sector role.

    Grounded, respectful tone. Acknowledges real budget constraints and
    pivots to movable levers: benefits/PSLF value, title scope, professional
    development budget, flexible work, raise review timeline, and sign-on vs
    base. No invented tactics.
    """
    extra = ""
    if constraints and constraints.strip():
        extra = f"\n\nTheir stated constraints: {constraints.strip()}\n"

    return f"""### Negotiating a nonprofit offer: {role}

Nonprofit hiring managers usually work within real, board-approved budget
bands. Acknowledge that honestly; it builds trust and keeps the conversation
about solving the problem together, not beating the budget.

1. **Lead with mission alignment, then be direct about the number.**
   "I want this work and this team. To say yes, I need the total package
   to land around [your target]. Can we get there, even if not all of it
   is in base?"

2. **Benefits and PSLF are part of the money.** If you carry federal loans,
   qualifying 501(c)(3) employment counts toward PSLF (120 qualifying
   payments). Price that in explicitly: "The PSLF value is part of why this
   offer works for me." Verify eligibility at studentaid.gov.

3. **Title and scope are negotiable currency.** A more accurate title and a
   written scope (team size, budget owned, direct reports) compounds into
   your next role's comp. Get the scope in the offer letter, not just the
   title.

4. **Ask for a professional development budget.** Conferences, courses, and
   certifications are often easier for a nonprofit to approve than base
   salary, and they pay you back in the next negotiation.

5. **Lock a raise review timeline.** "Can we agree in writing to revisit
   base at six months against these milestones?" A dated, milestone-linked
   review beats a vague "we'll see at annual."

6. **Sign-on vs base.** If base is truly capped, a one-time sign-on can
   bridge a first-year gap without breaking their band. Ask: "Is there any
   flexibility on a sign-on, even a modest one, to get me to yes?"

7. **Flexible work has dollar value.** Remote days, schedule flexibility,
   and extra PTO reduce your real costs. Name them as tradeable items:
   "If base can't move, could we do [specific ask]?"

8. **Never invent a competing offer.** Nonprofit recruiters talk to each
   other; a bluff that gets caught ends the process. Only cite real
   alternatives, and frame them as context, not threats.

Close with a deadline you control: "If we can land the package by [date],
I'm ready to sign and close out my search."
{extra}
*Remember: get the final terms in writing before you resign anywhere.*"""


def estimate_pslf_value(loan_balance: float, monthly_payment: float,
                        months_remaining: int) -> dict:
    """Pure arithmetic estimate of potential PSLF forgiveness.

    Formula: forgiven_principal ~= loan_balance - (months_remaining * monthly_payment)

    This is a rough estimate, not advice. It ignores interest accrual,
    payment-plan changes, and eligibility rules; verify everything at
    studentaid.gov.
    """
    if loan_balance < 0 or monthly_payment < 0 or months_remaining < 0:
        raise ValueError("loan_balance, monthly_payment, and months_remaining "
                         "must be non-negative")

    payments_total = monthly_payment * months_remaining
    forgiven_principal = loan_balance - payments_total

    return {
        "loan_balance": loan_balance,
        "monthly_payment": monthly_payment,
        "months_remaining": months_remaining,
        "payments_remaining_total": round(payments_total, 2),
        "forgiven_principal_estimate": round(forgiven_principal, 2),
        "formula": ("forgiven_principal ~= loan_balance "
                    "- (months_remaining * monthly_payment)"),
        "disclaimer": ("Rough estimate only, not financial advice. Ignores "
                       "interest accrual, payment-plan changes, and PSLF "
                       "eligibility rules. Verify at studentaid.gov."),
    }

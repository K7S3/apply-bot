"""What security interview loops look like, by company type.

Each loop describes the rounds a security-engineer candidate can expect at
startups, big tech, fintech, and consulting firms: round name, focus, and
1-2 practical tips.

Usage:
    from candid import security_loop
    for round_ in security_loop.get_loop("startup")["rounds"]:
        print(round_["name"], "-", round_["focus"])
"""

from __future__ import annotations

LOOPS: dict[str, dict] = {
    "startup": {
        "label": "Startup security engineer",
        "rounds": [
            {
                "name": "Recruiter screen",
                "focus": "Fit, scope of the security role, and whether you can be the whole security team.",
                "tips": [
                    "Ask who owns security today (a founder, a platform engineer) and what incidents hurt most recently.",
                    "Show breadth: you will be expected to cover appsec, infra, and response at once.",
                ],
            },
            {
                "name": "Hiring manager deep-dive",
                "focus": "Past hands-on security work and judgment under resource constraints.",
                "tips": [
                    "Prepare 2-3 stories where you did a lot with little: tooling, prioritization, automation.",
                    "Be concrete about what you would do in the first 30/60/90 days.",
                ],
            },
            {
                "name": "Technical security interview",
                "focus": "Practical appsec or infra security: find the bug, fix the config, read a snippet.",
                "tips": [
                    "Practice spotting OWASP Top 10 issues in short code samples and explaining impact + fix.",
                    "Narrate your reasoning out loud; startups hire for how you think under ambiguity.",
                ],
            },
            {
                "name": "Threat-model / system design",
                "focus": "Design review of a realistic product: trust boundaries, top threats, cheap mitigations.",
                "tips": [
                    "Start with assets and data flow before jumping to threats; draw the diagram.",
                    "Prioritize: say what you would fix first and what you would accept as residual risk.",
                ],
            },
            {
                "name": "Founder / behavioral",
                "focus": "Ownership, velocity, and whether you can say no to a founder without breaking the relationship.",
                "tips": [
                    "Show security-as-enabler stories: how you shipped faster *and* safer.",
                    "Ask about the security budget reality: headcount, tools, and board-level support.",
                ],
            },
        ],
        "notes": "Startups compress the loop (often 3-4 rounds) and weigh pragmatism over "
                 "process knowledge. Expect to be asked what you would NOT do given limited time.",
    },
    "bigtech": {
        "label": "Big tech security engineer",
        "rounds": [
            {
                "name": "Recruiter screen",
                "focus": "Level, team fit, and logistics; confirm the security sub-role (appsec, detection, platform).",
                "tips": [
                    "Clarify which security org you are interviewing for; big tech has many.",
                    "Have a crisp 2-minute career narrative ready.",
                ],
            },
            {
                "name": "Hiring manager screen",
                "focus": "Depth in your specialty and cross-functional collaboration at scale.",
                "tips": [
                    "Prepare stories about influencing teams you did not own.",
                    "Show how you measured security outcomes, not just activity.",
                ],
            },
            {
                "name": "Security technical deep-dive",
                "focus": "Deep expertise in one domain: crypto, detection, platform hardening, or appsec internals.",
                "tips": [
                    "Go one level deeper than comfortable: interviewers probe until they find your edge.",
                    "Say 'I don't know' cleanly, then reason from first principles.",
                ],
            },
            {
                "name": "Threat-model / design round",
                "focus": "Security architecture for a large distributed system, with attacker tradeoffs.",
                "tips": [
                    "Enumerate attacker capabilities explicitly, then design against them.",
                    "Discuss defense in depth and where you would place detection vs prevention.",
                ],
            },
            {
                "name": "Coding / scripting round",
                "focus": "Pragmatic scripting: parse logs, write a detector, automate a security task.",
                "tips": [
                    "Practice small data-wrangling tasks in your strongest language.",
                    "Correctness and clarity beat cleverness.",
                ],
            },
            {
                "name": "Behavioral (leadership principles)",
                "focus": "Ownership, bias for action, and earn-trust stories mapped to company values.",
                "tips": [
                    "Map each STAR story to a named company value before the loop.",
                    "Include one story about a mistake and what you changed.",
                ],
            },
        ],
        "notes": "Big tech loops are the longest (5-6 rounds) and most standardized. Bar-raiser "
                 "style rounds judge trajectory, not just current skills.",
    },
    "fintech": {
        "label": "Fintech security engineer",
        "rounds": [
            {
                "name": "Recruiter screen",
                "focus": "Regulated-industry fit, clearance/background basics, and compensation band.",
                "tips": [
                    "Expect background and reference checks to be mentioned early; nothing to fear, just plan for time.",
                    "Signal comfort with audit-driven work, not just hacking.",
                ],
            },
            {
                "name": "Hiring manager screen",
                "focus": "Experience with regulated environments, incident discipline, and change control.",
                "tips": [
                    "Prepare stories about working within change-management and approval processes.",
                    "Show you can be rigorous without being a blocker.",
                ],
            },
            {
                "name": "Technical security interview",
                "focus": "Appsec plus data protection: PII handling, encryption, access controls on money movement.",
                "tips": [
                    "Know PCI DSS scope basics and tokenization/encryption patterns cold.",
                    "Walk through how you would protect a payment flow end to end.",
                ],
            },
            {
                "name": "Threat-model / risk round",
                "focus": "Fraud and abuse modeling: how attackers steal money or data, and layered defenses.",
                "tips": [
                    "Think like a fraudster first, then as the defender: enumerate abuse cases.",
                    "Quantify risk in business terms: loss exposure, regulatory fines, customer trust.",
                ],
            },
            {
                "name": "Behavioral / compliance culture",
                "focus": "Judgment under regulatory pressure and working with auditors and risk teams.",
                "tips": [
                    "Have an audit or compliance story ready, even a small one.",
                    "Show respect for the second line of defense; fintech security partners with risk, not around it.",
                ],
            },
        ],
        "notes": "Fintech weighs governance and audit-readiness more than other tracks. "
                 "Expect questions about SOC 2, PCI DSS, and evidence collection.",
    },
    "consulting": {
        "label": "Security consulting (advisory / pentest)",
        "rounds": [
            {
                "name": "Recruiter screen",
                "focus": "Client-facing fit, travel/engagement model, and technical specialty.",
                "tips": [
                    "Clarify the mix: pentesting, assessments, or advisory; each interviews differently.",
                    "Show you can explain technical findings to non-technical clients.",
                ],
            },
            {
                "name": "Technical screen",
                "focus": "Hands-on fundamentals: methodology, tooling, and a walkthrough of a past engagement.",
                "tips": [
                    "Be ready to narrate a full engagement: scoping, testing, reporting, retest.",
                    "Name your methodology (OWASP Testing Guide, PTES, NIST) and why you follow it.",
                ],
            },
            {
                "name": "Practical / lab exercise",
                "focus": "Live or take-home exploitation: find and document vulnerabilities in a target.",
                "tips": [
                    "Document as you go: consultants are judged on report quality as much as findings.",
                    "Rate severity with a clear rationale, not just CVSS numbers.",
                ],
            },
            {
                "name": "Report writing / presentation",
                "focus": "Turn findings into an executive-ready report and defend recommendations.",
                "tips": [
                    "Structure findings: business impact first, technical detail second.",
                    "Practice presenting a finding to a 'CFO' who asks why they should pay to fix it.",
                ],
            },
            {
                "name": "Partner / behavioral",
                "focus": "Client management, difficult conversations, and business development instincts.",
                "tips": [
                    "Prepare a story about a difficult client conversation and how you kept trust.",
                    "Show curiosity about the business side: scoping, selling, and repeat engagements.",
                ],
            },
        ],
        "notes": "Consulting loops test communication as a core skill, not a soft add-on. "
                 "Your report sample and presentation round often decide the outcome.",
    },
}


def get_loop(slug: str) -> dict:
    """Return the loop dict for ``slug``; raises ValueError if unknown."""
    try:
        return LOOPS[slug]
    except KeyError:
        raise ValueError(f"unknown loop slug: {slug!r}")


def loop_names() -> list[str]:
    """Return the available loop slugs."""
    return list(LOOPS)

"""Security behavioral STAR prompts for the interview track.

Twelve prompts, each with per-part scaffolding hints (situation/task/action/
result). ``build_story`` helps the user draft a STAR answer from one of their
own resume bullets; it never invents metrics or events, and ``needs_input``
honestly flags every slot the user still has to personalize.

Usage:
    from candid import security_star
    story = security_star.build_story("pushback-risky-ship",
                                      "Blocked launch of PII export feature until field-level encryption added")
"""

from __future__ import annotations

PROMPTS: list[dict] = [
    {
        "id": "found-vulnerability",
        "prompt": "Tell me about a time you found a significant vulnerability. What was it and how did you handle it?",
        "competency": "vulnerability management",
        "scaffolding": {
            "situation": "Describe the system or codebase where you were working and how the vulnerability surfaced (code review, scan, pentest, bug bounty).",
            "task": "Explain what was at stake: what data or service was exposed and what your responsibility was.",
            "action": "Walk through how you confirmed it, assessed severity, and drove the fix (patch, mitigation, disclosure).",
            "result": "Share the outcome: time to remediate, recurrence prevention, or process change you introduced.",
        },
    },
    {
        "id": "handled-incident",
        "prompt": "Walk me through a security incident you responded to. What happened and what did you learn?",
        "competency": "incident response",
        "scaffolding": {
            "situation": "Set the scene: what alerted you and what the initial blast-radius looked like.",
            "task": "State your role in the response (responder, lead, on-call) and what had to be decided fast.",
            "action": "Describe containment and eradication steps, who you coordinated with, and how you communicated.",
            "result": "Give the resolution and one concrete lesson: what changed in runbooks, monitoring, or process afterward.",
        },
    },
    {
        "id": "pushback-risky-ship",
        "prompt": "Tell me about a time you pushed back on shipping something risky. How did you make your case?",
        "competency": "influence and judgment",
        "scaffolding": {
            "situation": "Describe the feature or launch, its deadline pressure, and the risk you spotted.",
            "task": "Explain why it fell to you to raise the concern and what you were weighing (user trust, compliance).",
            "action": "Show how you framed the risk in business terms, proposed an alternative or delay, and who you aligned with.",
            "result": "Share what was decided and what the team did differently next time.",
        },
    },
    {
        "id": "security-velocity-tradeoff",
        "prompt": "How have you balanced shipping velocity with security requirements?",
        "competency": "security/velocity tradeoff",
        "scaffolding": {
            "situation": "Describe a project where security work competed directly with a launch timeline.",
            "task": "Explain your mandate: keep the team fast while not accepting unacceptable risk.",
            "action": "Walk through how you prioritized (threat-model triage, paved-road defaults, phased rollout) and what you automated.",
            "result": "Share how velocity was preserved or what guardrail now makes this class of issue cheap.",
        },
    },
    {
        "id": "mentored-security",
        "prompt": "Tell me about a time you helped engineers get better at security.",
        "competency": "mentorship and enablement",
        "scaffolding": {
            "situation": "Describe the gap you saw: repeated vulnerability classes or low security fluency on the team.",
            "task": "Explain what you wanted the team to be able to do without you.",
            "action": "Describe what you built or taught: workshops, secure defaults, review checklists, office hours.",
            "result": "Share the change in behavior or metrics you saw, and how it stuck after you stepped back.",
        },
    },
    {
        "id": "threat-modeled-feature",
        "prompt": "Walk me through how you threat-modeled a feature end to end.",
        "competency": "threat modeling",
        "scaffolding": {
            "situation": "Describe the feature: its assets, trust boundaries, and data flow at a high level.",
            "task": "Explain why you were threat-modeling it: design review gate, compliance need, or past incident.",
            "action": "Walk through the method you used (STRIDE, attack tree, etc.) and the top threats you surfaced.",
            "result": "Share the design changes that came out of it and which ones actually mattered most.",
        },
    },
    {
        "id": "audit-response",
        "prompt": "Tell me about a time you went through a security audit or compliance review.",
        "competency": "governance and compliance",
        "scaffolding": {
            "situation": "Name the audit context (SOC 2, ISO 27001, customer security review) and your company's readiness.",
            "task": "Explain your role: owning evidence, remediating findings, or answering auditor questions.",
            "action": "Describe how you gathered evidence, closed gaps, and kept engineering work unblocked during the audit.",
            "result": "Share the outcome and one systemic fix you made so the next audit is easier.",
        },
    },
    {
        "id": "false-positive-flood",
        "prompt": "How have you dealt with alert fatigue or a flood of false positives?",
        "competency": "detection engineering",
        "scaffolding": {
            "situation": "Describe the noisy detector or scanner and how it was hurting the team's responsiveness.",
            "task": "Explain what good looked like: signal the team could actually act on.",
            "action": "Walk through how you tuned, rewrote, or replaced the detection, including how you validated it.",
            "result": "Share the before/after in alert volume or response quality, and how you prevented regression.",
        },
    },
    {
        "id": "secure-by-default",
        "prompt": "Tell me about something you built or changed to make the secure path the easy path.",
        "competency": "platform security",
        "scaffolding": {
            "situation": "Describe the insecure-by-default workflow engineers were using (secrets in code, wide-open policies).",
            "task": "Explain what you wanted developers to do instead, with no extra effort.",
            "action": "Describe the paved road you built: libraries, templates, CI checks, or platform defaults.",
            "result": "Share adoption and the reduction in the risky pattern you observed.",
        },
    },
    {
        "id": "third-party-risk",
        "prompt": "Tell me about a time you handled a vulnerability in a third-party dependency or vendor.",
        "competency": "supply chain security",
        "scaffolding": {
            "situation": "Describe the dependency or vendor and how the vulnerability came to your attention.",
            "task": "Explain your scope: assess exposure across your systems and decide the response.",
            "action": "Walk through triage (are we affected?), mitigation, patching or vendoring, and stakeholder updates.",
            "result": "Share the outcome and any lasting change: SBOM adoption, scanning, or vendor policy.",
        },
    },
    {
        "id": "disagreement-eng-leadership",
        "prompt": "Tell me about a time you disagreed with engineering leadership about a security decision.",
        "competency": "influence under pressure",
        "scaffolding": {
            "situation": "Describe the decision on the table and why leadership leaned the other way.",
            "task": "Explain your responsibility: protecting users or the business even when it was unpopular.",
            "action": "Show how you presented evidence, quantified risk, and offered options rather than just a veto.",
            "result": "Share how it resolved and how the working relationship came out of it.",
        },
    },
    {
        "id": "learned-from-mistake",
        "prompt": "Tell me about a security mistake you made or missed, and what you changed because of it.",
        "competency": "growth and accountability",
        "scaffolding": {
            "situation": "Describe the miss: a vulnerability that shipped, a misconfigured control, a slow response.",
            "task": "Own your part: what was your responsibility in that moment.",
            "action": "Walk through the postmortem, what root cause you found, and the fix you drove.",
            "result": "Share how it changed your habits, your team's process, or how you mentor others now.",
        },
    },
]

_PROMPT_BY_ID = {p["id"]: p for p in PROMPTS}


def get_prompt(prompt_id: str) -> dict:
    """Return the prompt dict for ``prompt_id``; raises ValueError if unknown."""
    try:
        return _PROMPT_BY_ID[prompt_id]
    except KeyError:
        raise ValueError(f"unknown prompt id: {prompt_id!r}")


def build_story(prompt_id: str, resume_bullet: str) -> dict:
    """Draft a STAR outline from the user's own resume bullet.

    The star slots echo the bullet text plus the prompt's scaffolding hints.
    No metrics, dates, or events are invented: anything the user has not
    supplied stays generic, and every such slot is listed in ``needs_input``.

    Returns ``{"prompt", "bullet", "star": {situation, task, action, result},
    "needs_input": [slot names]}``.
    """
    prompt = get_prompt(prompt_id)
    bullet = (resume_bullet or "").strip()
    if not bullet:
        raise ValueError("resume_bullet must be a non-empty string")
    hints = prompt["scaffolding"]
    star = {
        "situation": f"Starting from your experience: {bullet}. {hints['situation']} "
                     "Add: the system involved, when this happened, and how you got involved.",
        "task": f"Your responsibility in that work: {bullet}. {hints['task']} "
                "Add: what was expected of you specifically.",
        "action": f"What you actually did, in your words: {bullet}. {hints['action']} "
                  "Add: 2-4 concrete steps you took, in order.",
        "result": f"The outcome to quantify from your records: {bullet}. {hints['result']} "
                  "Add: time-to-fix, volume reduced, or adoption; only numbers you can verify.",
    }
    needs_input = ["situation", "task", "action", "result"]
    return {"prompt": prompt["prompt"], "bullet": bullet, "star": star, "needs_input": needs_input}

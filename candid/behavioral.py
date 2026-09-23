"""Behavioral interview prep beyond STAR.

STAR is a format, not a strategy. Interviewers at most companies score
candidates against an explicit values framework (Amazon's Leadership
Principles, Meta's values, Netflix's culture memo, ...). This module:

  frameworks()            leadership-principle frameworks per company type
  framework_for_company() pick the right framework for a company name
  lp_questions()          principle-tagged question bank (with interviewer probes)
  values_prompts()        values-alignment / "why us" prompts per company type
  stories_from_profile()  pull story bullets out of a candid profile
  map_stories()           score each story against each principle; find gaps
  coverage_report()       markdown: which principles are covered / thin / missing
  drill()                 one principle-tagged question + follow-up probes
  scaffold_story()        STAR, STAR-V (values tie-in), PAR, SOAR scaffolds
  trap_questions()        red-flag questions (salary, gaps, leaving) + framing
  pitch()                 90-second "tell me about yourself" mapped to values
  pack_section()          markdown section wired into the prep pack

Everything is local and deterministic. Questions here are canonical,
widely-documented behavioral prompts tagged to principles - never presented
as "recently asked at company X" (that claim lives in prep_questions.py,
which only carries sourced reports).
"""

from __future__ import annotations

import random
import re
from datetime import date

# ---------------------------------------------------------------------------
# Leadership-principle frameworks, keyed by company type.
# Principle text is paraphrased from each company's public values material.
# ---------------------------------------------------------------------------

FRAMEWORKS: dict[str, dict] = {
    "amazon": {
        "name": "Amazon Leadership Principles",
        "source": "Amazon's public Leadership Principles (16)",
        "principles": [
            {"id": "customer_obsession", "name": "Customer Obsession",
             "desc": "Start with the customer and work backwards; earn and keep trust.",
             "listens_for": "Specific customer pain, how you measured it, what you changed.",
             "signals": ["customer", "user", "client feedback", "pain point", "trust", "experience"]},
            {"id": "ownership", "name": "Ownership",
             "desc": "Think long term; act on behalf of the whole company, not just your team.",
             "listens_for": "You doing unglamorous work outside your lane without being asked.",
             "signals": ["took ownership", "responsible", "volunteered", "initiative", "unasked"]},
            {"id": "invent_simplify", "name": "Invent and Simplify",
             "desc": "Expect and require innovation; simplify processes and systems.",
             "listens_for": "A genuinely new approach, and complexity you removed.",
             "signals": ["invented", "new approach", "simplified", "automated", "redesigned"]},
            {"id": "right_lot", "name": "Are Right, A Lot",
             "desc": "Strong judgment and instincts; seek diverse perspectives.",
             "listens_for": "A call you made under uncertainty and how you pressure-tested it.",
             "signals": ["judgment", "decision", "data", "perspectives", "bet"]},
            {"id": "learn_curious", "name": "Learn and Be Curious",
             "desc": "Never done learning; explore new possibilities.",
             "listens_for": "Something hard you learned fast and applied.",
             "signals": ["learned", "curious", "explored", "studied", "experiment"]},
            {"id": "hire_develop", "name": "Hire and Develop the Best",
             "desc": "Raise the bar with every hire; coach people to grow.",
             "listens_for": "Someone you hired or mentored who leveled up.",
             "signals": ["hired", "mentored", "coached", "grew", "bar", "feedback"]},
            {"id": "insist_highest", "name": "Insist on the Highest Standards",
             "desc": "Relentlessly high standards; drive quality even when unpopular.",
             "listens_for": "Pushing back on 'good enough' and the quality bar you set.",
             "signals": ["standards", "quality", "bar", "rigor", "review"]},
            {"id": "think_big", "name": "Think Big",
             "desc": "Small thinking is a self-fulfilling prophecy; think in 10x terms.",
             "listens_for": "Ambition of the goal and how you sold others on it.",
             "signals": ["vision", "ambitious", "10x", "scale", "big bet"]},
            {"id": "bias_action", "name": "Bias for Action",
             "desc": "Speed matters; many decisions are reversible two-way doors.",
             "listens_for": "Moving fast with incomplete information; what you did vs. waited for.",
             "signals": ["moved fast", "shipped", "deadline", "quickly", "prototype"]},
            {"id": "frugality", "name": "Frugality",
             "desc": "Constraints breed resourcefulness; no scoreboard for headcount or budget.",
             "listens_for": "More accomplished with less; creative use of constraints.",
             "signals": ["constraint", "budget", "resourceful", "cost", "lean"]},
            {"id": "earn_trust", "name": "Earn Trust",
             "desc": "Listen attentively, speak candidly, treat others respectfully.",
             "listens_for": "A relationship you repaired or candor that was hard to give.",
             "signals": ["trust", "candid", "honest", "listened", "transparent"]},
            {"id": "dive_deep", "name": "Dive Deep",
             "desc": "Operate at all levels; stay connected to details; audit when needed.",
             "listens_for": "A detail you caught that changed the outcome.",
             "signals": ["detail", "deep dive", "root cause", "audited", "debugged"]},
            {"id": "backbone", "name": "Have Backbone; Disagree and Commit",
             "desc": "Respectfully challenge decisions you disagree with, then commit fully.",
             "listens_for": "Real disagreement (not a strawman), then full commitment.",
             "signals": ["disagreed", "pushed back", "challenged", "committed", "convinced"]},
            {"id": "deliver_results", "name": "Deliver Results",
             "desc": "Focus on key inputs; deliver with quality and on time despite setbacks.",
             "listens_for": "Obstacles overcome and the metric that moved.",
             "signals": ["delivered", "results", "shipped", "metric", "on time", "overcame"]},
            {"id": "strive_best", "name": "Strive to be Earth's Best Employer",
             "desc": "Create a safer, more productive, higher-performing, diverse, just culture.",
             "listens_for": "How you made the team or workplace better for others.",
             "signals": ["culture", "inclusive", "safe", "team health", "diversity"]},
            {"id": "success_scale", "name": "Success and Scale Bring Broad Responsibility",
             "desc": "We are big and impactful; be humble and consider the wider community.",
             "listens_for": "Considering second-order effects beyond your team.",
             "signals": ["impact", "community", "responsibility", "broader", "effects"]},
        ],
    },
    "meta": {
        "name": "Meta Values",
        "source": "Meta's public company values",
        "principles": [
            {"id": "move_fast", "name": "Move Fast",
             "desc": "Move fast together, in one direction; speed enables learning.",
             "listens_for": "Velocity with alignment - shipping fast without breaking the team.",
             "signals": ["moved fast", "shipped", "velocity", "iterated", "launched"]},
            {"id": "long_term", "name": "Focus on Long-Term Impact",
             "desc": "Solve the hard problems that compound over decades, not quarters.",
             "listens_for": "Choosing durable impact over the quick win.",
             "signals": ["long term", "durable", "compounding", "hard problem", "investment"]},
            {"id": "build_awesome", "name": "Build Awesome Things",
             "desc": "Ship products people love; craft matters.",
             "listens_for": "Pride in craft and user delight, not just completion.",
             "signals": ["craft", "delight", "polish", "loved", "quality"]},
            {"id": "live_future", "name": "Live in the Future",
             "desc": "Build for where the world is going; be early and be bold.",
             "listens_for": "Bets on emerging tech or behavior shifts you saw early.",
             "signals": ["future", "emerging", "early", "trend", "next"]},
            {"id": "direct_respect", "name": "Be Direct and Respect Colleagues",
             "desc": "Candor with care; feedback is a gift given respectfully.",
             "listens_for": "Hard feedback given or received well.",
             "signals": ["direct", "candid", "feedback", "respect", "honest"]},
            {"id": "metamates", "name": "Meta, Metamates, Me",
             "desc": "Company first, team second, self third; steward the mission.",
             "listens_for": "Putting team/company above personal credit.",
             "signals": ["team first", "credit", "mission", "unselfish", "helped"]},
        ],
    },
    "google": {
        "name": "Google Hiring Attributes",
        "source": "Google's public hiring attributes (incl. Googleyness)",
        "principles": [
            {"id": "cognitive", "name": "General Cognitive Ability",
             "desc": "Learn fast, reason from first principles, handle ambiguity.",
             "listens_for": "Structured thinking on a novel problem.",
             "signals": ["first principles", "structured", "reasoned", "ambiguous", "novel"]},
            {"id": "leadership", "name": "Emergent Leadership",
             "desc": "Step up when needed; influence without authority.",
             "listens_for": "Leading without a title; rallying others.",
             "signals": ["led", "influenced", "rallied", "stepped up", "without authority"]},
            {"id": "role_knowledge", "name": "Role-Related Knowledge",
             "desc": "Depth in your craft; know what great looks like.",
             "listens_for": "Technical depth and judgment about quality.",
             "signals": ["deep", "expertise", "craft", "best practice", "mastery"]},
            {"id": "googleyness", "name": "Googleyness",
             "desc": "Comfort with ambiguity, bias to action, collaborative, puts user first.",
             "listens_for": "Humility, collaboration, user focus, fun with hard problems.",
             "signals": ["collaborat", "user first", "humble", "ambiguous", "team"]},
        ],
    },
    "netflix": {
        "name": "Netflix Culture Values",
        "source": "Netflix public culture memo",
        "principles": [
            {"id": "judgment", "name": "Judgment",
             "desc": "Make wise decisions despite ambiguity; identify root causes.",
             "listens_for": "A tough call with incomplete data that proved right.",
             "signals": ["judgment", "decision", "root cause", "ambiguity", "wise"]},
            {"id": "communication", "name": "Communication",
             "desc": "Candid, articulate, and great listening; candor with intent.",
             "listens_for": "Radical candor that changed an outcome.",
             "signals": ["candid", "feedback", "listened", "articulate", "transparent"]},
            {"id": "curiosity", "name": "Curiosity",
             "desc": "Learn rapidly and eagerly; seek alternate perspectives.",
             "listens_for": "Proactive learning that paid off.",
             "signals": ["curious", "learned", "explored", "questioned", "studied"]},
            {"id": "courage", "name": "Courage",
             "desc": "Say what you think even if controversial; take smart risks.",
             "listens_for": "Speaking up at personal cost.",
             "signals": ["courage", "spoke up", "risk", "controversial", "unpopular"]},
            {"id": "passion", "name": "Passion",
             "desc": "Inspire others with thirst for excellence; care intensely.",
             "listens_for": "Energy that lifted the people around you.",
             "signals": ["passion", "inspired", "excellence", "care", "energy"]},
            {"id": "innovation", "name": "Innovation",
             "desc": "Reconceptualize issues to discover practical solutions.",
             "listens_for": "Reframing a problem to unlock a new solution.",
             "signals": ["innovated", "reframed", "new approach", "creative", "rethought"]},
            {"id": "integrity", "name": "Integrity",
             "desc": "Be honest, authentic, non-political, and only say things about fellow employees you would say to their face.",
             "listens_for": "Honesty when it was costly.",
             "signals": ["honest", "integrity", "authentic", "admitted", "mistake"]},
            {"id": "impact", "name": "Impact",
             "desc": "Accomplish amazing amounts of important work.",
             "listens_for": "Outsized output on what mattered most.",
             "signals": ["impact", "shipped", "results", "important", "delivered"]},
        ],
    },
    "microsoft": {
        "name": "Microsoft Culture",
        "source": "Microsoft's public culture attributes",
        "principles": [
            {"id": "growth_mindset", "name": "Growth Mindset",
             "desc": "Learn-it-all beats know-it-all; seek feedback and grow.",
             "listens_for": "Feedback you acted on; a belief you changed.",
             "signals": ["growth", "feedback", "learned", "mistake", "changed"]},
            {"id": "customer_obsessed", "name": "Customer Obsessed",
             "desc": "Deeply understand customers; build what they need.",
             "listens_for": "Customer insight driving a decision.",
             "signals": ["customer", "user", "feedback", "need", "empathy"]},
            {"id": "one_microsoft", "name": "One Microsoft",
             "desc": "Collaborate across boundaries; success is shared.",
             "listens_for": "Cross-team wins you enabled.",
             "signals": ["collaborat", "across teams", "partnered", "shared", "together"]},
            {"id": "diverse_inclusive", "name": "Diverse and Inclusive",
             "desc": "Everyone can thrive; seek out different voices.",
             "listens_for": "Actively including perspectives unlike your own.",
             "signals": ["inclusive", "diverse", "voices", "belonging", "perspective"]},
            {"id": "make_difference", "name": "Making a Difference",
             "desc": "Empower every person and organization to achieve more.",
             "listens_for": "Work whose purpose extended past the team.",
             "signals": ["purpose", "empower", "difference", "mission", "helped"]},
        ],
    },
    "apple": {
        "name": "Apple Interview Themes",
        "source": "Apple's public values + widely reported interview focus",
        "principles": [
            {"id": "craft", "name": "Craft and Detail",
             "desc": "Obsession with the details users feel but never notice.",
             "listens_for": "A detail you sweated that elevated the product.",
             "signals": ["detail", "craft", "polish", "pixel", "refined"]},
            {"id": "deep_expertise", "name": "Deep Functional Expertise",
             "desc": "Be the expert in your domain; depth over breadth.",
             "listens_for": "Mastery and strong technical opinions.",
             "signals": ["expert", "deep", "mastery", "opinion", "depth"]},
            {"id": "collaboration", "name": "Deep Collaboration",
             "desc": "Small expert teams; debate hard, align fully.",
             "listens_for": "Healthy conflict inside a tight team.",
             "signals": ["collaborat", "debate", "aligned", "team", "disagreed"]},
            {"id": "user_focus", "name": "User-First Simplicity",
             "desc": "Start from the user experience and work backwards to technology.",
             "listens_for": "Simplifying for the user, even at technical cost.",
             "signals": ["user", "simple", "experience", "intuitive", "removed"]},
            {"id": "ownership", "name": "Ownership and Accountability",
             "desc": "Directly responsible individuals; own the outcome end to end.",
             "listens_for": "End-to-end ownership of an outcome.",
             "signals": ["owned", "responsible", "end to end", "accountable", "drove"]},
        ],
    },
    "startup": {
        "name": "Startup Behavioral Themes",
        "source": "Common early-stage interview themes (generic)",
        "principles": [
            {"id": "ownership", "name": "Extreme Ownership",
             "desc": "Wear many hats; nothing is 'not my job'.",
             "listens_for": "Doing whatever the company needed, title aside.",
             "signals": ["owned", "hats", "whatever", "initiative", "volunteered"]},
            {"id": "velocity", "name": "Velocity",
             "desc": "Ship, learn, iterate; perfect is the enemy of launched.",
             "listens_for": "Cycle time from idea to shipped.",
             "signals": ["shipped", "fast", "iterated", "launched", "mvp"]},
            {"id": "resourcefulness", "name": "Resourcefulness",
             "desc": "Get it done with no budget, no team, no permission.",
             "listens_for": "Creative scrappiness under constraints.",
             "signals": ["scrappy", "constraint", "no budget", "figured out", "hacked"]},
            {"id": "ambiguity", "name": "Comfort with Ambiguity",
             "desc": "Create clarity where none exists; define your own roadmap.",
             "listens_for": "Thriving when the plan was blank.",
             "signals": ["ambiguous", "undefined", "figured out", "roadmap", "unclear"]},
            {"id": "mission", "name": "Mission Alignment",
             "desc": "Genuinely care about the problem; startups filter for belief.",
             "listens_for": "Why THIS problem, personally.",
             "signals": ["mission", "believe", "care", "problem", "why"]},
        ],
    },
    "finance": {
        "name": "Finance / Banking Behavioral Themes",
        "source": "Common sell-side and buy-side interview themes (generic)",
        "principles": [
            {"id": "client_trust", "name": "Client Trust",
             "desc": "Clients trust you with their money; never break that.",
             "listens_for": "Handling sensitive situations with discretion.",
             "signals": ["client", "trust", "confidential", "discretion", "fiduciary"]},
            {"id": "risk_awareness", "name": "Risk Awareness",
             "desc": "See the downside before the upside; controls matter.",
             "listens_for": "A risk you flagged that others missed.",
             "signals": ["risk", "downside", "controls", "flagged", "exposure"]},
            {"id": "integrity", "name": "Regulatory Integrity",
             "desc": "Do the right thing when nobody is watching; compliance is the floor.",
             "listens_for": "Choosing compliance over convenience or profit.",
             "signals": ["compliance", "regulation", "right thing", "ethical", "audit"]},
            {"id": "pressure", "name": "Performance Under Pressure",
             "desc": "Deadlines are real (deals, earnings); stay sharp when it counts.",
             "listens_for": "High-stakes delivery without cutting corners.",
             "signals": ["deadline", "pressure", "overnight", "delivered", "calm"]},
            {"id": "ownership", "name": "Ownership",
             "desc": "Own your book of work; mistakes are yours to surface early.",
             "listens_for": "Surfacing a mistake fast and fixing it.",
             "signals": ["owned", "mistake", "surfaced", "responsible", "fixed"]},
        ],
    },
    "consulting": {
        "name": "Consulting Behavioral Themes",
        "source": "Common MBB / Big-4 interview themes (generic)",
        "principles": [
            {"id": "structured", "name": "Structured Problem Solving",
             "desc": "Break messy problems into MECE pieces; hypothesis-driven.",
             "listens_for": "How you structured an ambiguous problem.",
             "signals": ["structured", "framework", "hypothesis", "broke down", "mece"]},
            {"id": "client_impact", "name": "Client Impact",
             "desc": "Recommendations that changed what the client actually did.",
             "listens_for": "Influence on a real decision, with the outcome.",
             "signals": ["client", "recommendation", "impact", "changed", "adopted"]},
            {"id": "teamwork", "name": "Teamwork and Leadership",
             "desc": "Make the team better; lead workstreams and people.",
             "listens_for": "Leading peers and developing juniors.",
             "signals": ["team", "led", "workstream", "mentored", "peers"]},
            {"id": "communication", "name": "Executive Communication",
             "desc": "Top-down, crisp, pyramid-principle communication.",
             "listens_for": "Distilling complexity for senior stakeholders.",
             "signals": ["executive", "crisp", "storyline", "presented", "synthesized"]},
            {"id": "drive", "name": "Drive and Resilience",
             "desc": "Sustain intensity through long engagements and setbacks.",
             "listens_for": "Pushing through when the engagement got hard.",
             "signals": ["drive", "resilience", "pushed", "setback", "sustained"]},
        ],
    },
    "default": {
        "name": "General Behavioral Themes",
        "source": "Generic themes used when no company-specific framework matches",
        "principles": [
            {"id": "ownership", "name": "Ownership",
             "desc": "Own outcomes end to end, not just tasks.",
             "listens_for": "You treating the result as yours.",
             "signals": ["owned", "responsible", "drove", "initiative", "accountable"]},
            {"id": "collaboration", "name": "Collaboration",
             "desc": "Make the people around you more effective.",
             "listens_for": "Helping others succeed, not just yourself.",
             "signals": ["collaborat", "helped", "team", "partnered", "supported"]},
            {"id": "communication", "name": "Communication",
             "desc": "Clear, candid, audience-aware communication.",
             "listens_for": "Adapting the message to the audience.",
             "signals": ["communicat", "presented", "explained", "candid", "stakeholder"]},
            {"id": "learning", "name": "Learning Agility",
             "desc": "Learn fast, admit gaps, apply feedback.",
             "listens_for": "A skill you picked up quickly under pressure.",
             "signals": ["learned", "feedback", "grew", "new", "adapted"]},
            {"id": "impact", "name": "Impact and Results",
             "desc": "Focus energy on what moves the metric.",
             "listens_for": "Outcomes with numbers attached.",
             "signals": ["impact", "results", "metric", "improved", "delivered"]},
            {"id": "integrity", "name": "Integrity",
             "desc": "Do the right thing, especially when it costs you.",
             "listens_for": "Honesty under pressure.",
             "signals": ["honest", "integrity", "right thing", "admitted", "ethical"]},
        ],
    },
}

_COMPANY_TO_FRAMEWORK = {
    "amazon": "amazon", "aws": "amazon", "wholefoods": "amazon", "zappos": "amazon",
    "meta": "meta", "facebook": "meta", "instagram": "meta", "whatsapp": "meta", "oculus": "meta",
    "google": "google", "alphabet": "google", "youtube": "google", "deepmind": "google", "waymo": "google",
    "netflix": "netflix",
    "microsoft": "microsoft", "linkedin": "microsoft", "github": "microsoft",
    "apple": "apple",
    "mckinsey": "consulting", "bcg": "consulting", "bain": "consulting",
    "deloitte": "consulting", "accenture": "consulting", "pwc": "consulting",
}


def _normalize(company: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (company or "").lower())


def framework_for_company(company: str) -> str:
    """Return the framework key best matching a company name."""
    slug = _normalize(company)
    if not slug:
        return "default"
    for key, fw in _COMPANY_TO_FRAMEWORK.items():
        if key in slug or slug in key:
            return fw
    banks = ("bankofamerica", "jpmorgan", "goldmansachs", "morganstanley",
             "citigroup", "wellsfargo", "barclays", "hsbc", "ubs", "capitalone")
    if any(b in slug for b in banks):
        return "finance"
    return "default"


def get_framework(key: str) -> dict:
    if key not in FRAMEWORKS:
        raise KeyError(f"Unknown behavioral framework '{key}'. "
                       f"Choose from: {', '.join(sorted(FRAMEWORKS))}")
    return FRAMEWORKS[key]


def principle_lookup(framework_key: str, principle_id: str) -> dict:
    fw = get_framework(framework_key)
    for p in fw["principles"]:
        if p["id"] == principle_id:
            return p
    raise KeyError(f"Unknown principle '{principle_id}' in framework '{framework_key}'.")

# ---------------------------------------------------------------------------
# Principle-tagged question bank.
# Canonical behavioral prompts (publicly documented everywhere); each is
# tagged to one framework + principle and ships with 2-3 interviewer-style
# follow-up probes - the "tell me more" layer where loops are actually won.
# ---------------------------------------------------------------------------

def _q(framework: str, principle: str, q: str, followups: list[str]) -> dict:
    return {"framework": framework, "principle": principle, "q": q,
            "followups": followups}


LP_QUESTIONS: list[dict] = [
    # ---- Amazon (16 LPs x 2) ----
    _q("amazon", "customer_obsession",
       "Tell me about a time you went above and beyond for a customer. What was the situation and the outcome?",
       ["How did you know this is what the customer actually wanted?",
        "What did you sacrifice to make it happen?"]),
    _q("amazon", "customer_obsession",
       "Describe a time you used customer feedback to change a decision or a product.",
       ["What was the feedback, exactly, and how did you collect it?",
        "How did you measure whether the change worked?"]),
    _q("amazon", "ownership",
       "Tell me about a time you took on something outside your role because it needed doing.",
       ["Why didn't you just hand it to the team that owned it?",
        "What was the long-term effect on the team or system?"]),
    _q("amazon", "ownership",
       "Describe a time you cleaned up someone else's mess or inherited a failing project.",
       ["How did you decide what to fix first?",
        "What would you do differently if you inherited it again?"]),
    _q("amazon", "invent_simplify",
       "Tell me about the most innovative thing you have built or process you invented.",
       ["What existed before, and why was it insufficient?",
        "What did you simplify away, and what did that cost?"]),
    _q("amazon", "invent_simplify",
       "Describe a time you simplified a complex process or system.",
       ["How did you convince stakeholders the simpler version was enough?",
        "What broke, if anything, when you simplified?"]),
    _q("amazon", "right_lot",
       "Tell me about a time you made a judgment call with incomplete data. Were you right?",
       ["What perspectives did you seek before deciding?",
        "What would have changed your mind?"]),
    _q("amazon", "right_lot",
       "Describe a decision you got wrong. How did you find out, and what did you do?",
       ["How long did it take you to admit it was wrong?",
        "What check would have caught it earlier?"]),
    _q("amazon", "learn_curious",
       "Tell me about a time you had to learn a completely new domain quickly.",
       ["How did you structure your learning?",
        "What did you get wrong early on?"]),
    _q("amazon", "learn_curious",
       "What is the most interesting thing you have learned recently, and how have you applied it?",
       ["Why did you go learn that on your own?",
        "How did it change how you work?"]),
    _q("amazon", "hire_develop",
       "Tell me about someone you hired who turned out great - or didn't. What did you learn?",
       ["What specifically did you see in them during hiring?",
        "What do you look for now that you didn't then?"]),
    _q("amazon", "hire_develop",
       "Describe a time you coached someone who was struggling. What happened?",
       ["How did you diagnose the real problem vs. the symptom?",
        "What was the hardest feedback you had to give them?"]),
    _q("amazon", "insist_highest",
       "Tell me about a time you refused to ship something that wasn't good enough.",
       ["Who pushed back on you, and how did you handle it?",
        "How do you define 'good enough' vs. perfect?"]),
    _q("amazon", "insist_highest",
       "Describe a time you raised the quality bar for your team.",
       ["What was the bar before, concretely?",
        "Did anyone resent it? How did you bring them along?"]),
    _q("amazon", "think_big",
       "Tell me about the most ambitious goal you set. Did you hit it?",
       ["Why that goal and not something safer?",
        "How did you get others to buy into the ambition?"]),
    _q("amazon", "think_big",
       "Describe a time you proposed an idea others thought was too big or unrealistic.",
       ["What was their objection, specifically?",
        "What happened to the idea?"]),
    _q("amazon", "bias_action",
       "Tell me about a time you moved fast without all the information. What was the result?",
       ["What was the worst case if you were wrong?",
        "What did you do in the first 48 hours?"]),
    _q("amazon", "bias_action",
       "Describe a time you cut through bureaucracy to get something done.",
       ["Whose approval did you skip, and why was that okay?",
        "What guardrails did you keep in place?"]),
    _q("amazon", "frugality",
       "Tell me about a time you accomplished more with fewer resources than expected.",
       ["What constraint forced the creativity?",
        "What would you have done with 10x the budget - and why was your way better?"]),
    _q("amazon", "frugality",
       "Describe a time you had to say no to a resource request (headcount, budget, time).",
       ["How did you make the call?",
        "How did the requester react?"]),
    _q("amazon", "earn_trust",
       "Tell me about a time you had to earn a skeptical stakeholder's trust.",
       ["What made them skeptical in the first place?",
        "What was the turning point?"]),
    _q("amazon", "earn_trust",
       "Describe a time you gave difficult feedback to a peer or manager.",
       ["How did you phrase it?",
        "How did the relationship change afterwards?"]),
    _q("amazon", "dive_deep",
       "Tell me about a time your attention to detail caught something important others missed.",
       ["How deep did you go, concretely?",
        "What process did you change so it wouldn't happen again?"]),
    _q("amazon", "dive_deep",
       "Describe a time you audited or investigated something end to end to find a root cause.",
       ["Walk me through the layers you peeled back.",
        "What was the actual root cause vs. what everyone assumed?"]),
    _q("amazon", "backbone",
       "Tell me about a time you disagreed with your manager or team and pushed back.",
       ["How did you disagree without being disagreeable?",
        "Did you commit fully once the decision was made? How?"]),
    _q("amazon", "backbone",
       "Describe a time you were overruled. How did you handle it?",
       ["Did you keep arguing, or commit? Why?",
        "Looking back, were they right?"]),
    _q("amazon", "deliver_results",
       "Tell me about a time you delivered critical results despite major setbacks.",
       ["What was the setback, and what was your contingency?",
        "What metric proved you delivered?"]),
    _q("amazon", "deliver_results",
       "Describe the hardest deadline you have ever hit. How?",
       ["What did you cut, and what did you protect?",
        "What did the team learn about scoping from it?"]),
    _q("amazon", "strive_best",
       "Tell me about a time you made your team or workplace better for others.",
       ["Who benefited, specifically?",
        "Did it cost you anything personally?"]),
    _q("amazon", "strive_best",
       "Describe a time you improved inclusion or psychological safety on a team.",
       ["What was the problem you observed?",
        "How did you know it worked?"]),
    _q("amazon", "success_scale",
       "Tell me about a time you considered the broader impact of your work beyond your team.",
       ["Who else was affected that you hadn't initially considered?",
        "What did you change once you saw the wider impact?"]),
    _q("amazon", "success_scale",
       "Describe a decision where you weighed company-wide or societal impact over local wins.",
       ["What was the tension, exactly?",
        "How did you make the tradeoff?"]),
    # ---- Meta (6 x 2) ----
    _q("meta", "move_fast",
       "Tell me about a time you shipped something fast. What did speed cost, and was it worth it?",
       ["How did you keep the team aligned at that pace?",
        "What would you slow down for next time?"]),
    _q("meta", "move_fast",
       "Describe a time you unblocked a stuck project and got it moving again.",
       ["What was stuck, exactly?",
        "What did you do in the first week?"]),
    _q("meta", "long_term",
       "Tell me about a time you chose long-term impact over a quick win.",
       ["How did you justify the slower payoff to stakeholders?",
        "Did the long-term bet pay off?"]),
    _q("meta", "long_term",
       "Describe a hard technical problem you invested in that took months to pay off.",
       ["Why was it worth months of investment?",
        "How did you keep momentum while results were invisible?"]),
    _q("meta", "build_awesome",
       "Tell me about something you built that you are genuinely proud of. What made it great?",
       ["What detail are you proudest of that nobody noticed?",
        "What would you rebuild differently?"]),
    _q("meta", "build_awesome",
       "Describe a time you went beyond 'works' to make something people love.",
       ["How did you know users loved it, not just used it?",
        "Where did the extra polish come from - time you stole from where?"]),
    _q("meta", "live_future",
       "Tell me about a time you bet on where technology was heading.",
       ["What signal convinced you early?",
        "What did skeptics say?"]),
    _q("meta", "live_future",
       "Describe a time you brought a new technology or idea into your team before it was mainstream.",
       ["How did you de-risk the bet?",
        "What happened?"]),
    _q("meta", "direct_respect",
       "Tell me about a time you gave direct feedback that was hard to hear.",
       ["How did you deliver it?",
        "What changed afterwards - for them and for you?"]),
    _q("meta", "direct_respect",
       "Describe a time you received tough feedback. How did you react?",
       ["What was your first instinct?",
        "What did you actually change?"]),
    _q("meta", "metamates",
       "Tell me about a time you put the team or company ahead of your own credit or interests.",
       ["What did it cost you personally?",
        "Would you do it again?"]),
    _q("meta", "metamates",
       "Describe a time you helped a struggling teammate or another team at cost to your own work.",
       ["How did you balance it with your own deliverables?",
        "What was the outcome for them?"]),
    # ---- Google (4 x 2) ----
    _q("google", "cognitive",
       "Tell me about a time you solved a problem you had never seen before. Walk me through your thinking.",
       ["What was your first hypothesis, and why was it wrong?",
        "How did you break the problem down?"]),
    _q("google", "cognitive",
       "Describe a time you had to make sense of ambiguous or conflicting data.",
       ["What framework did you use to reason through it?",
        "What did you decide, and what would change your mind?"]),
    _q("google", "leadership",
       "Tell me about a time you led without formal authority.",
       ["Why did people follow you?",
        "What was the hardest part of leading peers?"]),
    _q("google", "leadership",
       "Describe a time you took initiative that others didn't want to take.",
       ["What was at stake if nobody acted?",
        "How did you bring skeptics along?"]),
    _q("google", "role_knowledge",
       "Tell me about the hardest technical problem you have solved. What made it hard?",
       ["What did you try that didn't work?",
        "How do you know your solution was the right one?"]),
    _q("google", "role_knowledge",
       "Describe a time your deep expertise changed a team's decision.",
       ["What did the team believe before you weighed in?",
        "How did you communicate the technical nuance?"]),
    _q("google", "googleyness",
       "Tell me about a time you thrived in ambiguity.",
       ["What was unclear, and what did you do first?",
        "How did you create clarity for others?"]),
    _q("google", "googleyness",
       "Describe a time you put the user first even when it made your work harder.",
       ["What was the harder path, concretely?",
        "How did you measure the user benefit?"]),
    # ---- Netflix (8 x 2, core values) ----
    _q("netflix", "judgment",
       "Tell me about a tough call you made with incomplete information.",
       ["What were the competing options?",
        "What did you learn about your own judgment from it?"]),
    _q("netflix", "judgment",
       "Describe a time you identified the real root cause when everyone else was wrong.",
       ["What was the popular (wrong) theory?",
        "How did you prove your version?"]),
    _q("netflix", "communication",
       "Tell me about a time your candor changed an outcome - given or received.",
       ["What made it hard to say (or hear)?",
        "What happened next?"]),
    _q("netflix", "communication",
       "Describe a time you had to deliver bad news to stakeholders.",
       ["How did you frame it?",
        "What did you bring besides the bad news?"]),
    _q("netflix", "curiosity",
       "Tell me about something you learned proactively that later proved valuable.",
       ["What sparked the curiosity?",
        "How did you go deep on it?"]),
    _q("netflix", "curiosity",
       "Describe a time you challenged your own assumptions.",
       ["What was the assumption, and what broke it?",
        "What did you change?"]),
    _q("netflix", "courage",
       "Tell me about a time you said what you thought even though it was unpopular.",
       ["What was the personal risk?",
        "Were you right? How do you know?"]),
    _q("netflix", "courage",
       "Describe a smart risk you took that didn't pay off.",
       ["Why was it smart ex ante?",
        "What did the failure teach you?"]),
    _q("netflix", "innovation",
       "Tell me about a time you reframed a problem to find a better solution.",
       ["What was the original framing, and what was wrong with it?",
        "What unlocked the reframe?"]),
    _q("netflix", "innovation",
       "Describe the most creative solution you have shipped under constraints.",
       ["What were the constraints?",
        "Why was the creative path better than the obvious one?"]),
    _q("netflix", "integrity",
       "Tell me about a time you were honest when it cost you something.",
       ["What did it cost?",
        "What would the easy (dishonest) path have looked like?"]),
    _q("netflix", "integrity",
       "Describe a mistake you owned up to. What happened?",
       ["How quickly did you surface it?",
        "What changed in how you work since?"]),
    _q("netflix", "impact",
       "Tell me about the highest-impact work you have done. Why was it high impact?",
       ["How did you choose it over other options?",
        "Quantify the impact."]),
    _q("netflix", "impact",
       "Describe a time you killed or deprioritized work to focus on what mattered.",
       ["How did you decide what mattered?",
        "How did stakeholders react?"]),
    _q("netflix", "passion",
       "Tell me about a time your enthusiasm lifted a team's performance.",
       ["What was the team feeling before?",
        "What specifically did you do?"]),
    # ---- Microsoft (5 x 2) ----
    _q("microsoft", "growth_mindset",
       "Tell me about a time feedback changed how you work.",
       ["What was the feedback, exactly?",
        "What did you do differently the next time?"]),
    _q("microsoft", "growth_mindset",
       "Describe something you were bad at that you got good at. How?",
       ["What was your learning plan?",
        "How long did it take, and how did you measure progress?"]),
    _q("microsoft", "customer_obsessed",
       "Tell me about a time you deeply understood a customer need others missed.",
       ["How did you learn it - what did you observe?",
        "What did you build from it?"]),
    _q("microsoft", "customer_obsessed",
       "Describe a time you advocated for the customer against internal convenience.",
       ["Who were you arguing against?",
        "What was the outcome for the customer?"]),
    _q("microsoft", "one_microsoft",
       "Tell me about a successful cross-team collaboration you drove.",
       ["What made the teams' incentives misaligned?",
        "How did you align them?"]),
    _q("microsoft", "one_microsoft",
       "Describe a time you helped another team succeed at cost to your own goals.",
       ["How did your manager react?",
        "Was it worth it?"]),
    _q("microsoft", "diverse_inclusive",
       "Tell me about a time you sought out a perspective different from your own.",
       ["Whose perspective, and why theirs?",
        "How did it change the outcome?"]),
    _q("microsoft", "diverse_inclusive",
       "Describe a time you made space for a quieter voice on your team.",
       ["What did you notice?",
        "What did they contribute once heard?"]),
    _q("microsoft", "make_difference",
       "Tell me about work you did whose purpose went beyond your team or company.",
       ["Why did it matter to you personally?",
        "What was the broader effect?"]),
    _q("microsoft", "make_difference",
       "Describe a time you empowered someone else to achieve more.",
       ["What did empowerment look like concretely?",
        "What did they achieve?"]),
    # ---- Apple (5 x 2) ----
    _q("apple", "craft",
       "Tell me about a detail you obsessed over that most people would never notice.",
       ["Why did that detail matter?",
        "How much effort did it take, and was it worth it?"]),
    _q("apple", "craft",
       "Describe a time you kept iterating past 'good enough'. What pushed you?",
       ["How did you know when to stop?",
        "What did the extra iterations buy?"]),
    _q("apple", "deep_expertise",
       "Tell me about an area where you are the go-to expert. How did you get there?",
       ["What do you know that generalists in the area usually miss?",
        "What is a strong technical opinion you hold?"]),
    _q("apple", "deep_expertise",
       "Describe a time your depth caught a flaw in a plan everyone else approved.",
       ["What was the flaw?",
        "How did you explain it so non-experts got it?"]),
    _q("apple", "collaboration",
       "Tell me about a healthy disagreement inside a small, senior team.",
       ["What were the two positions?",
        "How did you reach alignment - and commit?"]),
    _q("apple", "collaboration",
       "Describe a time you depended on deep partnership with another function (design, hardware, etc.).",
       ["Where did the disciplines clash?",
        "What did the partnership produce that neither could alone?"]),
    _q("apple", "user_focus",
       "Tell me about a time you simplified something for the user at real technical cost.",
       ["What was the technical cost?",
        "How did you justify it?"]),
    _q("apple", "user_focus",
       "Describe a decision where you chose the user experience over engineering elegance.",
       ["What did engineering elegance look like here?",
        "What did users feel instead?"]),
    _q("apple", "ownership",
       "Tell me about something you owned end to end. Where did 'your' ownership start and stop?",
       ["What was the hardest part nobody else could do?",
        "What broke that you had to fix?"]),
    # ---- Startup (5 x 2) ----
    _q("startup", "ownership",
       "Tell me about a time you did work far outside your job description because the company needed it.",
       ["What was the job you were hired for vs. what you did?",
        "What was the result?"]),
    _q("startup", "ownership",
       "Describe a time there was no owner for a critical problem and you became the owner.",
       ["How did you know it was critical?",
        "What did owning it entail day to day?"]),
    _q("startup", "velocity",
       "Tell me about the fastest you have gone from idea to shipped. What enabled the speed?",
       ["What corners did you cut deliberately?",
        "What did you learn from users after shipping?"]),
    _q("startup", "velocity",
       "Describe a time you killed your own project fast because the data said so.",
       ["What was the data?",
        "How fast did you kill it, and what did you do next?"]),
    _q("startup", "resourcefulness",
       "Tell me about a time you got something done with basically no resources.",
       ["What did 'no resources' mean concretely?",
        "What was the scrappy solution?"]),
    _q("startup", "resourcefulness",
       "Describe a time you solved a problem without the tool, budget, or hire you wanted.",
       ["What did you want, and what did you use instead?",
        "Would you still want the original now?"]),
    _q("startup", "ambiguity",
       "Tell me about a time you joined or led something with no roadmap.",
       ["What did you do in the first two weeks?",
        "How did you decide what mattered?"]),
    _q("startup", "ambiguity",
       "Describe a time the plan changed completely mid-flight. How did you respond?",
       ["What changed, and why?",
        "What did you salvage?"]),
    _q("startup", "mission",
       "Why this company, and why this problem? Make it personal.",
       ["What experience connects you to this problem?",
        "Why now, and why here instead of a bigger company?"]),
    _q("startup", "mission",
       "Tell me about a time you chose mission over money, comfort, or prestige.",
       ["What did you give up?",
        "Was it the right call?"]),
    # ---- Finance (5 x 2) ----
    _q("finance", "client_trust",
       "Tell me about a time a client trusted you with something sensitive. How did you handle it?",
       ["What made it sensitive?",
        "What did you do to protect that trust?"]),
    _q("finance", "client_trust",
       "Describe a time you had to tell a client something they didn't want to hear.",
       ["How did you deliver it?",
        "What happened to the relationship?"]),
    _q("finance", "risk_awareness",
       "Tell me about a risk you spotted that others missed.",
       ["What was the risk, and how did you see it?",
        "What did you do about it?"]),
    _q("finance", "risk_awareness",
       "Describe a time you weighed risk vs. reward on a real decision.",
       ["How did you quantify the downside?",
        "What was the outcome?"]),
    _q("finance", "integrity",
       "Tell me about a time you chose the compliant path when a shortcut was available.",
       ["What was the shortcut, and what did it promise?",
        "What did the compliant path cost?"]),
    _q("finance", "integrity",
       "Describe a time you raised a concern about something that wasn't clearly wrong but felt off.",
       ["What felt off, specifically?",
        "How was it received?"]),
    _q("finance", "pressure",
       "Tell me about the highest-pressure deadline you have worked. How did you perform?",
       ["What was at stake?",
        "How did you stay sharp?"]),
    _q("finance", "pressure",
       "Describe a time everything went wrong right before a critical delivery.",
       ["What went wrong?",
        "Walk me through the recovery."]),
    _q("finance", "ownership",
       "Tell me about a mistake you caught in your own work. What did you do?",
       ["How did you find it?",
        "How fast did you surface it, and to whom?"]),
    _q("finance", "ownership",
       "Describe a time you owned a workstream end to end under a tight timeline.",
       ["What was the scope?",
        "What would you do differently?"]),
    # ---- Consulting (5 x 2) ----
    _q("consulting", "structured",
       "Tell me about a messy, ambiguous problem you structured. What was your approach?",
       ["What was your starting hypothesis?",
        "How did you break it into pieces?"]),
    _q("consulting", "structured",
       "Describe a time your first hypothesis was wrong. How did you pivot?",
       ["What disproved it?",
        "How fast did you change course?"]),
    _q("consulting", "client_impact",
       "Tell me about a recommendation you made that a client actually implemented.",
       ["How did you get buy-in?",
        "What was the measured impact?"]),
    _q("consulting", "client_impact",
       "Describe a time a client resisted your recommendation. What did you do?",
       ["What was their objection?",
        "Did you persuade them, adapt, or walk away?"]),
    _q("consulting", "teamwork",
       "Tell me about a time you led a team through a difficult stretch.",
       ["What made it difficult?",
        "How did you keep the team together?"]),
    _q("consulting", "teamwork",
       "Describe a time you developed a junior colleague.",
       ["What did they need?",
        "What changed for them?"]),
    _q("consulting", "communication",
       "Tell me about a time you had to explain a complex analysis to a senior executive.",
       ["How did you structure the message?",
        "What did they decide?"]),
    _q("consulting", "communication",
       "Describe a presentation that didn't land. What did you learn?",
       ["Why didn't it land?",
        "What do you do differently now?"]),
    _q("consulting", "drive",
       "Tell me about a time you sustained intensity through a grueling period.",
       ["What kept you going?",
        "What did it cost, and was it worth it?"]),
    _q("consulting", "drive",
       "Describe your biggest professional setback and how you responded.",
       ["What happened?",
        "What did you do in the first week after?"]),
    # ---- Default / generic (6 x 2) ----
    _q("default", "ownership",
       "Tell me about a time you took ownership of a problem end to end.",
       ["What did 'ownership' mean beyond your normal duties?",
        "What was the outcome?"]),
    _q("default", "ownership",
       "Describe a time you fixed something that wasn't your responsibility.",
       ["Why did you step in?",
        "How was it received?"]),
    _q("default", "collaboration",
       "Tell me about a time you made a teammate more effective.",
       ["What did you do, specifically?",
        "How did it affect the team's output?"]),
    _q("default", "collaboration",
       "Describe a difficult working relationship and how you improved it.",
       ["What made it difficult?",
        "What was the turning point?"]),
    _q("default", "communication",
       "Tell me about a time you had to explain something technical to a non-technical audience.",
       ["How did you adapt the message?",
        "How did you know they understood?"]),
    _q("default", "communication",
       "Describe a time miscommunication caused a problem. How did you fix it?",
       ["What went wrong in the communication?",
        "What process did you put in place after?"]),
    _q("default", "learning",
       "Tell me about a time you had to learn something new under a deadline.",
       ["How did you prioritize what to learn?",
        "What did you deliver?"]),
    _q("default", "learning",
       "Describe the most useful feedback you have ever received. What did you change?",
       ["Who gave it, and why did it land?",
        "What is different about you now?"]),
    _q("default", "impact",
       "Tell me about your highest-impact project. Why did it matter?",
       ["How did you pick it over alternatives?",
        "Quantify the impact."]),
    _q("default", "impact",
       "Describe a time you disagreed with a priority and were proven right (or wrong).",
       ["What was the disagreement?",
        "What did you learn about prioritization?"]),
    _q("default", "integrity",
       "Tell me about a time you did the right thing when it was difficult.",
       ["What made it difficult?",
        "What did it cost you?"]),
    _q("default", "integrity",
       "Describe a time you admitted a mistake at work.",
       ["How did you surface it?",
        "What changed afterwards?"]),
]

# ---------------------------------------------------------------------------
# Query API over the bank
# ---------------------------------------------------------------------------

def list_frameworks() -> list[dict]:
    return [{"key": k, "name": v["name"], "source": v["source"],
             "principles": len(v["principles"])} for k, v in FRAMEWORKS.items()]


def lp_questions(company: str = "", framework: str = "",
                 principle: str | None = None) -> list[dict]:
    """Principle-tagged questions for a company (or explicit framework)."""
    fw = framework or framework_for_company(company)
    get_framework(fw)  # validates
    out = [q for q in LP_QUESTIONS if q["framework"] == fw]
    if principle:
        principle_lookup(fw, principle)  # validates
        out = [q for q in out if q["principle"] == principle]
    return out


def principle_slugs(framework: str) -> list[str]:
    return [p["id"] for p in get_framework(framework)["principles"]]


# ---------------------------------------------------------------------------
# Values-alignment prompts ("why us", culture fit)
# ---------------------------------------------------------------------------

_VALUES_PROMPTS: dict[str, list[dict]] = {
    "amazon": [
        {"q": "Why Amazon?",
         "scaffold": "Name a specific Amazon mechanism you admire (working backwards, six-pagers, two-pizza teams) and connect it to how you already work."},
        {"q": "Which Leadership Principle resonates most with you, and why?",
         "scaffold": "Pick ONE, tell a 60-second story that proves it, and say what it changed about you."},
        {"q": "What would you build at Amazon in your first year?",
         "scaffold": "Show customer obsession: start from a customer pain, work backwards to the product."},
    ],
    "meta": [
        {"q": "Why Meta?",
         "scaffold": "Connect to a Meta value (e.g. Live in the Future) with a bet you have made on where tech is going."},
        {"q": "Tell me about a product you love. What would you change?",
         "scaffold": "Build Awesome Things: show taste. Critique precisely, then propose the fix."},
        {"q": "How do you move fast without breaking the team?",
         "scaffold": "Move Fast is 'together, in one direction' - show velocity WITH alignment."},
    ],
    "google": [
        {"q": "Why Google?",
         "scaffold": "Be specific: a product, a research direction, a team. Generic admiration is forgettable."},
        {"q": "What does Googleyness mean to you?",
         "scaffold": "Comfort with ambiguity + bias to action + collaborative + user-first. Give one story touching two."},
        {"q": "What would you work on at Google?",
         "scaffold": "Show you understand Google's scale problems, not just its perks."},
    ],
    "netflix": [
        {"q": "What do you think of the Netflix culture memo?",
         "scaffold": "They WILL ask. Have a real opinion: which value resonates, which worries you, and why."},
        {"q": "Tell me about a time you gave or received radical candor.",
         "scaffold": "Netflix screens for this explicitly. Bring your strongest candor story."},
        {"q": "Why Netflix over a bigger / more stable company?",
         "scaffold": "High performance, high freedom, no safety net - say why that fits YOU."},
    ],
    "microsoft": [
        {"q": "Why Microsoft?",
         "scaffold": "Mission ('empower every person...') + growth mindset. Connect your learning story to their mission."},
        {"q": "Tell me about a time you demonstrated a growth mindset.",
         "scaffold": "Learn-it-all > know-it-all: a belief you changed with evidence."},
        {"q": "How do you collaborate across teams?",
         "scaffold": "One Microsoft: concrete cross-boundary win."},
    ],
    "apple": [
        {"q": "Why Apple?",
         "scaffold": "Craft. Name a product detail you admire and WHY the detail matters to users."},
        {"q": "What does quality mean to you?",
         "scaffold": "Show your bar with a story, not adjectives."},
        {"q": "How do you handle deep debate with smart peers?",
         "scaffold": "Small expert teams debate hard: show you can argue AND align."},
    ],
    "startup": [
        {"q": "Why us, specifically? Why not a bigger company?",
         "scaffold": "Make it personal: the problem, the stage, the team. 'I want startup experience' is not an answer."},
        {"q": "What would you do in your first 30 days?",
         "scaffold": "Ownership + velocity: show you can create your own roadmap."},
        {"q": "Tell me about a time you did something scrappy.",
         "scaffold": "Resourcefulness story with a real constraint."},
    ],
    "finance": [
        {"q": "Why this firm?",
         "scaffold": "Specific: deals, desk, culture, people you met. Never generic prestige talk."},
        {"q": "How do you think about risk?",
         "scaffold": "Show you see downside first. One story where you flagged or managed risk."},
        {"q": "Tell me about a time you worked under extreme pressure.",
         "scaffold": "Deadlines are real here: show calm, accuracy, and ownership."},
    ],
    "consulting": [
        {"q": "Why consulting? Why this firm?",
         "scaffold": "Problem variety + client impact + people. Name what draws you beyond 'smart people'."},
        {"q": "Tell me about a time you influenced someone senior.",
         "scaffold": "Executive communication: crisp, top-down, with the decision it drove."},
        {"q": "How do you handle ambiguity on a new engagement?",
         "scaffold": "Structured problem solving: hypothesis, MECE breakdown, iteration."},
    ],
    "default": [
        {"q": "Why this company?",
         "scaffold": "Three-part: what they do (specific), why it matters to you (personal), why you fit (evidence)."},
        {"q": "Why this role, and why now?",
         "scaffold": "Connect your trajectory: this role is the obvious next step, not a random jump."},
        {"q": "What are you looking for in your next role?",
         "scaffold": "Name 2-3 things this specific role offers. Show you chose them, not just any offer."},
    ],
}


def values_prompts(company: str = "", framework: str = "") -> list[dict]:
    fw = framework or framework_for_company(company)
    get_framework(fw)
    return _VALUES_PROMPTS.get(fw, _VALUES_PROMPTS["default"])


# ---------------------------------------------------------------------------
# Trap / red-flag questions with framing guidance
# ---------------------------------------------------------------------------

TRAP_QUESTIONS: list[dict] = [
    {"q": "What are your salary expectations?",
     "why_asked": "They want to anchor you low or screen you out on comp.",
     "frame": "Deflect with a researched range, never a single number or your current comp. "
              "'Based on the market for this role and level, I'm targeting the X-Y band. What's the approved range for this role?'"},
    {"q": "Why are you leaving your current role?",
     "why_asked": "Screening for bitterness, job-hopping, or being managed out.",
     "frame": "Run TOWARD the new role, never AWAY from the old one. One neutral sentence on the past, three on the future."},
    {"q": "What is your greatest weakness?",
     "why_asked": "Self-awareness check; 'perfectionist' answers fail it.",
     "frame": "Real weakness + what you're actively doing about it + evidence of progress. Never a disguised strength."},
    {"q": "Tell me about a gap in your employment.",
     "why_asked": "Checking for hidden firings or unexplained time.",
     "frame": "Brief, honest, forward-looking. Name what you did with the time (learning, family, health) and why you're ready now."},
    {"q": "Where else are you interviewing? Do you have other offers?",
     "why_asked": "Gauging your market heat and their leverage.",
     "frame": "Be truthful but vague on names unless an offer exists. Real competing offers are leverage - mention timeline, not bluffs."},
    {"q": "Why should we hire you over other candidates?",
     "why_asked": "Can you summarize your value proposition crisply?",
     "frame": "Three proof points mapped to THEIR stated needs, not your resume in order. End with enthusiasm for the role."},
    {"q": "What would your manager say about you - strengths and areas to improve?",
     "why_asked": "Cross-checks self-awareness against references.",
     "frame": "Give the real answer your manager would give. Consistency with references matters more than polish."},
    {"q": "How do you handle conflict with coworkers?",
     "why_asked": "Screening for drama and blame patterns.",
     "frame": "One story: disagreement on the work (never personal), direct conversation, resolution, relationship intact."},
    {"q": "Are you willing to take a pay cut / lower level?",
     "why_asked": "Testing how badly you want it; sometimes a leveling probe.",
     "frame": "Don't answer hypothetically. 'I'd evaluate the full package and growth trajectory - can you share the level and range?'"},
    {"q": "What questions do you have for me?",
     "why_asked": "Curiosity and seriousness signal; 'no questions' is a fail.",
     "frame": "Always ask 2-3: role success criteria, team challenges, interviewer's own experience. Never comp/logistics first."},
]


def trap_questions() -> list[dict]:
    return TRAP_QUESTIONS

# ---------------------------------------------------------------------------
# Stories: extract from profile, score against principles, find gaps
# ---------------------------------------------------------------------------

def stories_from_profile(profile: dict) -> list[dict]:
    """Flatten profile experience bullets into story candidates.

    Returns [{title, company, text}]. Works with candid profile schema
    (experience: [{title, company, dates, bullets}]) and tolerates junk.
    """
    stories: list[dict] = []
    for exp in (profile or {}).get("experience", []) or []:
        if not isinstance(exp, dict):
            continue
        title = str(exp.get("title", "") or "").strip()
        company = str(exp.get("company", "") or "").strip()
        for b in exp.get("bullets", []) or []:
            text = str(b or "").strip()
            if len(text) >= 20:
                stories.append({"title": title, "company": company, "text": text})
    return stories


def score_story_against_principle(story_text: str, principle: dict) -> dict:
    """Heuristic fit score: signal-word hits + concrete-detail bonus.

    Honest heuristic, not an LLM judgment - documented as such wherever shown.
    """
    low = (story_text or "").lower()
    hits = [s for s in principle.get("signals", []) if s.lower() in low]
    # concrete-detail bonus: numbers, percents, dollar signs, timeframes
    detail_bonus = 1 if re.search(r"\d", low) else 0
    score = len(hits) + detail_bonus
    return {"score": score, "hits": hits, "has_metric": bool(detail_bonus)}


def map_stories(profile: dict, company: str = "", framework: str = "") -> dict:
    """Map each story to every principle; report best story per principle.

    Returns {"framework": key, "stories": [...],
             "mapping": {principle_id: {"principle":..., "best": story|None,
                                        "score": int, "hits": [...],
                                        "status": "covered"|"thin"|"missing"}}}
    Status: covered (score>=2), thin (score==1), missing (score==0).
    """
    fw_key = framework or framework_for_company(company)
    fw = get_framework(fw_key)
    stories = stories_from_profile(profile)
    mapping: dict[str, dict] = {}
    for p in fw["principles"]:
        best, best_score, best_hits = None, 0, []
        for s in stories:
            r = score_story_against_principle(s["text"], p)
            if r["score"] > best_score:
                best, best_score, best_hits = s, r["score"], r["hits"]
        status = "covered" if best_score >= 2 else ("thin" if best_score == 1 else "missing")
        mapping[p["id"]] = {"principle": p, "best": best, "score": best_score,
                            "hits": best_hits, "status": status}
    return {"framework": fw_key, "framework_name": fw["name"],
            "stories": stories, "mapping": mapping}


def coverage_report(profile: dict, company: str = "", role: str = "",
                    framework: str = "") -> str:
    """Markdown report: principle coverage, gaps, and a drill plan."""
    m = map_stories(profile, company=company, framework=framework)
    fw_key = m["framework"]
    lines = [
        f"# Behavioral Coverage — {m['framework_name']}",
        f"*Company: {company or 'unspecified'} · Role: {role or 'unspecified'} · "
        f"{date.today().isoformat()} · {len(m['stories'])} stories mapped*",
        "",
        "_Scores are a keyword heuristic over your resume bullets, not a judgment "
        "of your experience. A 'missing' principle means no bullet _signals_ it - "
        "you may well have the story; it just isn't on the page yet._",
        "",
        "## Principle coverage",
        "",
        "| Principle | Status | Best story signal |",
        "|---|---|---|",
    ]
    for pid, entry in m["mapping"].items():
        p = entry["principle"]
        mark = {"covered": "✅ covered", "thin": "⚠️ thin", "missing": "❌ missing"}[entry["status"]]
        if entry["best"]:
            t = entry["best"]["text"]
            sig = (t[:90] + "…") if len(t) > 90 else t
        else:
            sig = "_no story_"
        lines.append(f"| {p['name']} | {mark} | {sig} |")
    missing = [e["principle"]["name"] for e in m["mapping"].values() if e["status"] == "missing"]
    thin = [e["principle"]["name"] for e in m["mapping"].values() if e["status"] == "thin"]
    lines += ["", "## Gaps to close before interview day", ""]
    if missing:
        lines.append(f"- **Write stories for:** {', '.join(missing)}")
    if thin:
        lines.append(f"- **Strengthen with metrics:** {', '.join(thin)}")
    if not missing and not thin:
        lines.append("- No gaps: every principle has a signaling story. Drill the follow-up probes instead.")
    lines += ["",
              "_How to close a gap: pick a real project, draft it in STAR-V (see `candid behavioral drill`), "
              "and add the metric to the resume bullet - the mapping re-scores automatically._",
              "",
              "## Suggested drill plan (30 min)", ""]
    drill_ids = [pid for pid, e in m["mapping"].items() if e["status"] != "covered"][:3]
    if not drill_ids:
        drill_ids = list(m["mapping"])[:3]
    for i, pid in enumerate(drill_ids, 1):
        p = m["mapping"][pid]["principle"]
        lines.append(f"{i}. `{p['name']}` — `python -m candid behavioral drill --company \"{company or 'Acme'}\" --principle {pid}`")
    lines += ["", "---",
              f"_Framework: {m['framework_name']} ({fw_key}). Change company to re-map._"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Drill: one principle-tagged question + interviewer probes
# ---------------------------------------------------------------------------

def drill(company: str = "", framework: str = "", principle: str | None = None,
          seed: int | None = None) -> dict:
    """Pick a principle-tagged question with follow-up probes.

    Returns {"framework", "principle": {...}, "q", "followups"}.
    Deterministic when seed is given (tests); random otherwise.
    """
    fw = framework or framework_for_company(company)
    qs = lp_questions(company=company, framework=fw, principle=principle)
    if not qs:
        raise ValueError(f"No drill questions for framework '{fw}'"
                         + (f" principle '{principle}'" if principle else ""))
    rng = random.Random(seed) if seed is not None else random
    pick = rng.choice(qs)
    return {"framework": fw, "principle": principle_lookup(fw, pick["principle"]),
            "q": pick["q"], "followups": pick["followups"]}


def render_drill(d: dict) -> str:
    p = d["principle"]
    lines = [f"### Drill — {p['name']}", "",
             f"**{d['q']}**", "",
             "_Answer out loud, 2 minutes, STAR-V. Then handle the probes:_", ""]
    for i, f in enumerate(d["followups"], 1):
        lines.append(f"- **Probe {i}:** {f}")
    lines += ["", f"_What they're listening for: {p['listens_for']}_"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Story scaffolds: STAR and its variants
# ---------------------------------------------------------------------------

SCAFFOLDS = {
    "star": ("STAR",
             ["Situation — team, stakes, one line",
              "Task — what YOU personally owned",
              "Action — 2-3 concrete steps you took",
              "Result — the metric, plus what you learned"]),
    "star_v": ("STAR-V (values tie-in)",
               ["Situation — team, stakes, one line",
                "Task — what you personally owned",
                "Action — 2-3 concrete steps you took",
                "Result — the metric, plus what you learned",
                "Values tie — name the principle and say how the story proves it"]),
    "par": ("PAR (problem-action-result)",
            ["Problem — what was broken and why it mattered",
             "Action — what you did, with specifics",
             "Result — quantified outcome"]),
    "soar": ("SOAR",
             ["Situation — context in one line",
              "Obstacle — what made it hard",
              "Action — what you did",
              "Result — outcome and lesson"]),
}


def scaffold_story(story_text: str, variant: str = "star_v",
                   principle: dict | None = None) -> str:
    """Render a story bullet as a fill-in scaffold of the given variant."""
    if variant not in SCAFFOLDS:
        raise KeyError(f"Unknown scaffold '{variant}'. Choose from: {', '.join(sorted(SCAFFOLDS))}")
    name, steps = SCAFFOLDS[variant]
    lines = [f"### {name}", "", f"> Your bullet: \"{story_text}\"", ""]
    for s in steps:
        if s.startswith("Values tie") and principle:
            lines.append(f"- **{s}** → _e.g. \"This is {principle['name']}: ...\"_")
        else:
            lines.append(f"- **{s}**")
    lines += ["",
              "_Rules: 150+ words spoken, 'I' not 'we' for your actions, "
              "one metric minimum, never invent details not in the bullet._"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 90-second pitch builder, mapped to company values
# ---------------------------------------------------------------------------

def pitch(profile: dict, company: str = "", framework: str = "") -> str:
    """Build a 90-second 'tell me about yourself' mapped to company values."""
    fw_key = framework or framework_for_company(company)
    fw = get_framework(fw_key)
    stories = stories_from_profile(profile)
    name = (profile or {}).get("name", "you")
    headline = (profile or {}).get("headline", "") or (profile or {}).get("title", "")
    years = (profile or {}).get("years_experience", "")
    top_vals = [p["name"] for p in fw["principles"][:3]]
    lines = [
        "# 90-Second Pitch",
        f"*Mapped to {fw['name']}: {', '.join(top_vals)}*",
        "",
        "## The structure (present → past → future)",
        "",
        f"**Present (20s):** \"I'm {name}" +
        (f", {headline}" if headline else "") +
        (f" with {years} years of experience" if years else "") + ".\"",
        "  → One line on what you do NOW and the impact you're having.",
        "",
        "**Past (40s):** Pick 2 stories that signal this company's values:",
    ]
    for s in stories[:2]:
        at = f" ({s['title']} @ {s['company']})" if s["title"] or s["company"] else ""
        t = s["text"]
        lines.append(f"  - \"{t[:110]}{'…' if len(t) > 110 else ''}\"{at}")
    if not stories:
        lines.append("  - _No resume bullets found: write 2 STAR stories first, then plug them in here._")
    lines += [
        "",
        "**Future (30s):** \"That's why I'm excited about " +
        (company or "this role") + ":\"",
        f"  → Name ONE value ({top_vals[0] if top_vals else 'ownership'}) and connect it to what you want to do next.",
        "",
        "_Rules: 90 seconds spoken, no life story, end looking forward. "
        "Rehearse it 5x out loud - it opens every behavioral loop._",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prep-pack integration section
# ---------------------------------------------------------------------------

def pack_section(profile: dict, company: str, role: str) -> str:
    """Markdown section for the interview prep pack (wired into prep.build_pack)."""
    fw_key = framework_for_company(company)
    fw = get_framework(fw_key)
    m = map_stories(profile, company=company, framework=fw_key)
    missing = sum(1 for e in m["mapping"].values() if e["status"] == "missing")
    thin = sum(1 for e in m["mapping"].values() if e["status"] == "thin")
    lines = [
        "Leadership principles & values alignment",
        "",
        f"_This company interviews against **{fw['name']}**. Interviewers score your "
        "stories against these principles - often more than your answers' polish. "
        "Source: " + fw["source"] + "_",
        "",
        f"**Your coverage:** {len(m['mapping']) - missing - thin}/{len(m['mapping'])} principles "
        f"have a signaling story ({missing} missing, {thin} thin).",
        "",
        "### The principles (what they listen for)",
        "",
    ]
    for p in fw["principles"]:
        st = m["mapping"][p["id"]]["status"]
        mark = {"covered": "✅", "thin": "⚠️", "missing": "❌"}[st]
        lines.append(f"- {mark} **{p['name']}** — {p['desc']}")
        lines.append(f"  - _Listens for:_ {p['listens_for']}")
    lines += [
        "",
        "### Values-alignment prompts to rehearse",
        "",
    ]
    for vp in values_prompts(company=company, framework=fw_key)[:3]:
        lines += [f"- **{vp['q']}**", f"  - _Scaffold:_ {vp['scaffold']}", ""]
    d = drill(company=company, framework=fw_key, seed=7)
    lines += [
        "### One drill to run today",
        "",
        f"**{d['q']}** ({d['principle']['name']})",
    ]
    for i, f in enumerate(d["followups"], 1):
        lines.append(f"- Probe {i}: {f}")
    lines += [
        "",
        "_Full tools: `python -m candid behavioral drill`, `... story-map`, "
        "`... coverage`, `... traps`, `... pitch`. See docs/behavioral.md._",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Adapter for mock.py: principle slugs as behavioral themes
# ---------------------------------------------------------------------------

def mock_question(theme: str, seed: int | None = None) -> dict | None:
    """Return a mock-compatible question dict for a principle slug, or None.

    Lets `candid mock behavioral --theme <principle>` drill leadership
    principles without touching behavioral.json.
    """
    for fw_key, fw in FRAMEWORKS.items():
        ids = {p["id"] for p in fw["principles"]}
        if theme in ids:
            qs = [q for q in LP_QUESTIONS
                  if q["framework"] == fw_key and q["principle"] == theme]
            if not qs:
                return None
            rng = random.Random(seed) if seed is not None else random
            pick = rng.choice(qs)
            p = principle_lookup(fw_key, theme)
            return {"id": f"lp-{fw_key}-{theme}",
                    "theme": f"{fw['name']}: {p['name']}",
                    "question": pick["q"],
                    "followups": pick["followups"]}
    return None

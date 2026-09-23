"""PM interview question bank for the product-manager track.

Every question was found through public web research (interview guides,
candidate-reported question banks, hiring-manager write-ups). Each entry
carries its source and, where known, when it was reported, so prep packs
never invent "recently asked at X" claims.

Companies are keyed by a normalized lowercase name. Entries under
"general" are explicitly general preparation - NOT verified as asked at
any specific company.
"""

from __future__ import annotations

import argparse
import json


class PMError(Exception):
    """Raised for invalid PM question-bank requests."""


# ---------------------------------------------------------------------------
# Categories used across the PM bank
# ---------------------------------------------------------------------------

CATEGORIES = [
    "product_sense",
    "metrics",
    "execution",
    "estimation",
    "behavioral",
    "strategy",
    "ai_pm",
]

#: Friendly aliases -> canonical company key
_COMPANY_ALIASES = {
    "facebook": "meta",
    "fb": "meta",
    "goog": "google",
    "amzn": "amazon",
    "msft": "microsoft",
}


def normalize_company(company: str) -> str:
    """Normalize a company name to a question-bank key."""
    key = (company or "").strip().lower().replace(" ", "").replace(".", "")
    return _COMPANY_ALIASES.get(key, key)


# ---------------------------------------------------------------------------
# PM_QUESTIONS_DB: company -> list of entries.
# Fields: q, category, company (normalized lowercase), source, url, reported
# ---------------------------------------------------------------------------

_EXPONENT_2026 = "Exponent (Aced) - '52 Real Product Manager Interview Questions (2026 Guide)'"
_EXPONENT_2026_URL = "https://www.tryexponent.com/blog/top-product-manager-interview-questions?ref=exponent-blog.ghost.io"
_IG_METRICS = "IGotAnOffer - 'How to crack product metrics questions in PM interviews' (metric-change questions compiled from Glassdoor and PM Exercises candidate reports)"
_IG_METRICS_URL = "https://igotanoffer.com/blogs/product-manager/product-metric-interview-questions"
_IG_BEHAVIORAL = "IGotAnOffer - '8 Most-Asked Product Manager Behavioral Interview Questions' (company-specific examples)"
_IG_BEHAVIORAL_URL = "https://igotanoffer.com/en/advice/product-manager-behavioral-interview-questions"
_IG_TYPES = "IGotAnOffer - 'The 8 types of PM Interview Questions' (examples reported by candidates on Glassdoor)"
_IG_TYPES_URL = "https://igotanoffer.com/blogs/product-manager/product-manager-interview-questions"
_EXPONENT_OPENAI = "Exponent (Aced) - 'OpenAI Product Manager Interview Questions (Updated 2026)' question bank"
_EXPONENT_OPENAI_URL = "https://www.tryexponent.com/questions?company=openai&role=pm"
_INTERNSHALA_MS = "Internshala - 'Top 60 Microsoft Program Manager Interview Questions & Answers'"
_INTERNSHALA_MS_URL = "https://internshala.com/blog/microsoft-program-manager-interview-questions/"
_MS_80Q = "Microsoft Program Manager Interview - '80 Sample Questions' (candidate-reported bank)"
_MS_80Q_URL = "https://global-uploads.webflow.com/5d0dc87aac109e1ffdbe379c/61c170e55268e1c2fde55368_Microsoft%20Program%20Manager%20Interview%20Questions.pdf"
_MS_STAR_GUIDE = "leetcode.study archive - 'Product Manager Interview Questions: Microsoft' (STAR-method guide)"
_MS_STAR_GUIDE_URL = "https://leetcode.study/archive-ga-23-48/product-manager-interview-questions-microsoft.pdf"
_STRIPE_MEDIUM = "Medium (Sanjay Kumar PhD) - 'Top 10 Stripe Product Manager Interview Questions and Answers'"
_STRIPE_MEDIUM_URL = "https://skphd.medium.com/top-10-stripe-product-manager-interview-questions-and-answers-7ed75603329f"


def _entry(q: str, category: str, company: str, source: str,
           url: str, reported: str) -> dict:
    return {
        "q": q,
        "category": category,
        "company": company,
        "source": source,
        "url": url,
        "reported": reported,
    }


PM_QUESTIONS_DB: dict[str, list[dict]] = {
    "google": [
        _entry("Improve YouTube's recommendation algorithm.",
               "product_sense", "google", _EXPONENT_2026,
               _EXPONENT_2026_URL, "2026 (guide)"),
        _entry("Design a time machine.",
               "product_sense", "google", _EXPONENT_2026,
               _EXPONENT_2026_URL, "2026 (guide)"),
        _entry("You are looking at YouTube's Daily Active User data worldwide "
               "and notice a 10% jump compared to yesterday in Indonesia - "
               "what happened?",
               "metrics", "google", _IG_METRICS, _IG_METRICS_URL,
               "2026 (guide; candidate reports)"),
        _entry("Engagement is going down by 10% month on month for your "
               "product. What data / metrics would you look at?",
               "execution", "google", _IG_METRICS, _IG_METRICS_URL,
               "2026 (guide; candidate reports)"),
        _entry("How would you increase the number of YouTube users?",
               "strategy", "google", _EXPONENT_2026, _EXPONENT_2026_URL,
               "2026 (guide)"),
        _entry("How would you react to a product competing with Gmail?",
               "strategy", "google", _EXPONENT_2026, _EXPONENT_2026_URL,
               "2026 (guide)"),
        _entry("Devise an A/B test to improve Google Maps.",
               "metrics", "google", _EXPONENT_2026, _EXPONENT_2026_URL,
               "2026 (guide)"),
        _entry("YouTube comments are up, but watch time is down. "
               "What do you do?",
               "execution", "google", _EXPONENT_2026, _EXPONENT_2026_URL,
               "2026 (guide)"),
        _entry("Estimate the number of videos watched on YouTube per day.",
               "estimation", "google", _EXPONENT_2026, _EXPONENT_2026_URL,
               "2026 (guide)"),
        _entry("What is one accomplishment you're most proud of, at work or "
               "outside of work?",
               "behavioral", "google", _IG_BEHAVIORAL, _IG_BEHAVIORAL_URL,
               "2026 (guide; company-specific examples)"),
        _entry("Describe a project you managed from start to finish, "
               "including any project management tools you used.",
               "behavioral", "google", _IG_BEHAVIORAL, _IG_BEHAVIORAL_URL,
               "2026 (guide; company-specific examples)"),
        _entry("How do you resolve conflicting product requirements?",
               "behavioral", "google", _IG_BEHAVIORAL, _IG_BEHAVIORAL_URL,
               "2026 (guide; company-specific examples)"),
        _entry("Your largest customer is loudly advocating for a new feature "
               "that isn't on your roadmap. Sales has gone straight to "
               "Engineering. What do you do?",
               "behavioral", "google", _IG_BEHAVIORAL, _IG_BEHAVIORAL_URL,
               "2026 (guide; company-specific examples)"),
    ],
    "meta": [
        _entry("Design a product for borrowing and lending money.",
               "product_sense", "meta", _EXPONENT_2026,
               _EXPONENT_2026_URL, "2026 (guide)"),
        _entry("Design a fitness app for Meta.",
               "product_sense", "meta", _IG_TYPES, _IG_TYPES_URL,
               "2026 (guide; candidate reports)"),
        _entry("There's been a 15% drop in usage of Facebook Groups - "
               "how do you fix it?",
               "execution", "meta", _IG_METRICS, _IG_METRICS_URL,
               "2026 (guide; candidate reports)"),
        _entry("The usage of Facebook Event's 'Yes I'm going' dropped 30% "
               "overnight - which data would you look at to try to isolate "
               "the issue?",
               "execution", "meta", _IG_METRICS, _IG_METRICS_URL,
               "2026 (guide; candidate reports)"),
        _entry("You are the PM of Facebook 3rd Party Login, and you see your "
               "numbers are declining 2% week-on-week - what do you do?",
               "execution", "meta", _IG_METRICS, _IG_METRICS_URL,
               "2026 (guide; candidate reports)"),
        _entry("How would you determine success for Instagram Reels?",
               "metrics", "meta", _EXPONENT_2026, _EXPONENT_2026_URL,
               "2026 (guide)"),
        _entry("How do you measure success after launching a product?",
               "metrics", "meta", _IG_BEHAVIORAL, _IG_BEHAVIORAL_URL,
               "2026 (guide; company-specific examples)"),
        _entry("How do you earn the trust of your team?",
               "behavioral", "meta", _IG_BEHAVIORAL, _IG_BEHAVIORAL_URL,
               "2026 (guide; company-specific examples)"),
        _entry("Tell me about a time you successfully navigated competing "
               "leadership priorities.",
               "behavioral", "meta", _IG_BEHAVIORAL, _IG_BEHAVIORAL_URL,
               "2026 (guide; company-specific examples)"),
    ],
    "amazon": [
        _entry("Tell me about a time you made short-term sacrifices for "
               "long-term gains.",
               "behavioral", "amazon", _EXPONENT_2026, _EXPONENT_2026_URL,
               "2026 (guide; classic Amazon LP question)"),
        _entry("How would you change the Amazon Fresh experience and how "
               "would you measure it?",
               "product_sense", "amazon", _IG_METRICS, _IG_METRICS_URL,
               "2026 (guide; candidate reports)"),
        _entry("Imagine that in your daily routine of checking conversion "
               "funnels, you realized a 20% drop in the checkout funnel. "
               "What would you do?",
               "execution", "amazon", _IG_METRICS, _IG_METRICS_URL,
               "2026 (guide; candidate reports)"),
        _entry("Around 40% of reviews on Amazon are fake. As an Amazon PM, "
               "how will you tackle the problem?",
               "execution", "amazon", _IG_METRICS, _IG_METRICS_URL,
               "2026 (guide; candidate reports)"),
        _entry("How have you measured customer satisfaction in the past?",
               "metrics", "amazon", _IG_BEHAVIORAL, _IG_BEHAVIORAL_URL,
               "2026 (guide; company-specific examples)"),
        _entry("How do you decide which customer requests make it into the "
               "roadmap?",
               "behavioral", "amazon", _IG_BEHAVIORAL, _IG_BEHAVIORAL_URL,
               "2026 (guide; company-specific examples)"),
        _entry("Tell me about a time when you tried to convince your manager "
               "of a product direction and were unsuccessful.",
               "behavioral", "amazon", _IG_BEHAVIORAL, _IG_BEHAVIORAL_URL,
               "2026 (guide; company-specific examples)"),
    ],
    "microsoft": [
        _entry("How would you improve Microsoft Outlook?",
               "product_sense", "microsoft", _MS_80Q, _MS_80Q_URL,
               "question bank (ongoing)"),
        _entry("Design a mobile app for Microsoft Teams.",
               "product_sense", "microsoft", _MS_80Q, _MS_80Q_URL,
               "question bank (ongoing)"),
        _entry("How would you improve an existing Microsoft product?",
               "product_sense", "microsoft", _INTERNSHALA_MS,
               _INTERNSHALA_MS_URL, "question bank (ongoing)"),
        _entry("Give an example of a time you had to pivot your strategy "
               "based on user feedback. What did you learn?",
               "behavioral", "microsoft", _MS_STAR_GUIDE, _MS_STAR_GUIDE_URL,
               "guide (ongoing)"),
    ],
    "apple": [
        _entry("What's your favorite product and why?",
               "product_sense", "apple", _EXPONENT_2026, _EXPONENT_2026_URL,
               "2026 (guide)"),
        _entry("You're an Apple product manager for Apple Maps. What will "
               "you do to regain market share?",
               "strategy", "apple", _IG_METRICS, _IG_METRICS_URL,
               "2026 (guide; candidate reports)"),
    ],
    "stripe": [
        _entry("Design WhatsApp for students.",
               "product_sense", "stripe", _EXPONENT_2026, _EXPONENT_2026_URL,
               "2026 (guide)"),
        _entry("Merchants say billing details add friction to Checkout and "
               "hurt conversion. What would you do?",
               "execution", "stripe", _STRIPE_MEDIUM, _STRIPE_MEDIUM_URL,
               "Sep 2026"),
    ],
    "openai": [
        _entry("How would you launch a new ChatGPT model?",
               "strategy", "openai", _EXPONENT_2026, _EXPONENT_2026_URL,
               "2026 (guide)"),
        _entry("You have invented a memory machine. Go to market.",
               "strategy", "openai", _EXPONENT_OPENAI, _EXPONENT_OPENAI_URL,
               "2026 (question bank)"),
        _entry("How would you handle hallucinations in a generative AI model "
               "deployed to users?",
               "ai_pm", "openai", _EXPONENT_OPENAI, _EXPONENT_OPENAI_URL,
               "2026 (question bank)"),
    ],
    "general": [
        _entry("What's your favorite product and why? How would you improve "
               "it?",
               "product_sense", "general", _EXPONENT_2026,
               _EXPONENT_2026_URL, "2026 (guide; general preparation)"),
        _entry("Estimate the number of Uber drivers in San Francisco.",
               "estimation", "general", _EXPONENT_2026, _EXPONENT_2026_URL,
               "2026 (guide; general preparation)"),
        _entry("How much revenue does YouTube generate per day?",
               "estimation", "general", _IG_TYPES, _IG_TYPES_URL,
               "2026 (guide; general preparation, reported on Glassdoor)"),
        _entry("What's your 10-year strategy for Uber?",
               "strategy", "general", _IG_TYPES, _IG_TYPES_URL,
               "2026 (guide; general preparation, reported on Glassdoor)"),
        _entry("Instagram feed engagement drops 10% - what do you do?",
               "execution", "general", _IG_TYPES, _IG_TYPES_URL,
               "2026 (guide; general preparation, reported on Glassdoor)"),
        _entry("How would you prioritize 3 features?",
               "execution", "general", _IG_TYPES, _IG_TYPES_URL,
               "2026 (guide; general preparation, reported on Glassdoor)"),
        _entry("Set goals and success metrics for an AI-only social network.",
               "metrics", "general", _IG_TYPES, _IG_TYPES_URL,
               "2026 (guide; general preparation, reported on Glassdoor)"),
        _entry("What should Airbnb's north star metric be?",
               "metrics", "general", _EXPONENT_2026, _EXPONENT_2026_URL,
               "2026 (guide; general preparation)"),
        _entry("How do you determine success for a product?",
               "metrics", "general", _EXPONENT_2026, _EXPONENT_2026_URL,
               "2026 (guide; general preparation)"),
        _entry("Daily active users have gone down on our application. How "
               "would you find the root cause?",
               "execution", "general", _EXPONENT_2026, _EXPONENT_2026_URL,
               "2026 (guide; general preparation)"),
        _entry("How would you reduce fake news on social media?",
               "execution", "general", _EXPONENT_2026, _EXPONENT_2026_URL,
               "2026 (guide; general preparation)"),
        _entry("Legal has concerns about your feature. Walk me through your "
               "approach.",
               "execution", "general", _EXPONENT_2026, _EXPONENT_2026_URL,
               "2026 (guide; general preparation)"),
        _entry("Tell me about a time you dealt with conflict at work.",
               "behavioral", "general", _IG_TYPES, _IG_TYPES_URL,
               "2026 (guide; general preparation, reported on Glassdoor)"),
        _entry("Tell me about a time you handled a difficult stakeholder.",
               "behavioral", "general", _EXPONENT_2026, _EXPONENT_2026_URL,
               "2026 (guide; general preparation)"),
        _entry("Tell me about a time one of your products failed.",
               "behavioral", "general", _EXPONENT_2026, _EXPONENT_2026_URL,
               "2026 (guide; general preparation)"),
        _entry("Tell me about a time you applied judgment to a decision when "
               "data was not available.",
               "behavioral", "general", _IG_TYPES, _IG_TYPES_URL,
               "2026 (guide; general preparation, reported on Glassdoor)"),
        _entry("What's the biggest threat to YouTube?",
               "strategy", "general", _EXPONENT_2026, _EXPONENT_2026_URL,
               "2026 (guide; general preparation)"),
        _entry("How do you approach AI safety in a consumer product?",
               "ai_pm", "general", _EXPONENT_2026, _EXPONENT_2026_URL,
               "2026 (guide; general preparation)"),
        _entry("Should Samsung build a video game console?",
               "strategy", "general", _EXPONENT_2026, _EXPONENT_2026_URL,
               "2026 (guide; general preparation)"),
    ],
}


# ---------------------------------------------------------------------------
# Query API
# ---------------------------------------------------------------------------

def companies() -> list[str]:
    """Sorted list of company keys in the bank (including 'general')."""
    return sorted(PM_QUESTIONS_DB)


def _all() -> list[dict]:
    out: list[dict] = []
    for entries in PM_QUESTIONS_DB.values():
        out.extend(entries)
    return out


def list_questions(category: str | None = None,
                   company: str | None = None) -> list[dict]:
    """Return bank entries, optionally filtered by category and/or company.

    Filters are case-insensitive; unknown category/company yields an
    empty list rather than an error.
    """
    entries = _all()
    if category:
        cat = category.strip().lower().replace(" ", "_").replace("-", "_")
        entries = [e for e in entries if e["category"] == cat]
    if company:
        key = normalize_company(company)
        entries = [e for e in entries if e["company"] == key]
    return entries


def search_questions(query: str) -> list[dict]:
    """Case-insensitive free-text search over question, category, company,
    and source."""
    q = (query or "").strip().lower()
    if not q:
        return []
    hits = []
    for e in _all():
        hay = " ".join([e["q"], e["category"], e["company"], e["source"]]).lower()
        if q in hay:
            hits.append(e)
    return hits


# ---------------------------------------------------------------------------
# Prep-pack integration hook (dependency-free)
# ---------------------------------------------------------------------------

_MUST_KNOW_CATEGORIES = ["product_sense", "metrics", "execution", "estimation",
                         "behavioral"]


def build_pm_bank_section(company: str, role: str) -> dict:
    """Build the PM question-bank section for an interview prep pack.

    Returns a plain dict the coordinator can embed directly: company-tagged
    questions first, then a curated set of general must-knows (one per core
    category). Never fabricates company-tagged questions: if the company is
    unknown, company_questions is empty and the pack falls back to generals.
    """
    key = normalize_company(company)
    company_qs = [e for e in PM_QUESTIONS_DB.get(key, [])
                  if e["company"] == key]
    must_knows: list[dict] = []
    for cat in _MUST_KNOW_CATEGORIES:
        for e in PM_QUESTIONS_DB["general"]:
            if e["category"] == cat:
                must_knows.append(e)
                break
    covered = sorted({e["category"] for e in company_qs + must_knows})
    return {
        "company": key,
        "role": role or "",
        "company_questions": company_qs,
        "general_must_knows": must_knows,
        "categories_covered": covered,
        "note": ("Company-tagged questions were reported by candidates and "
                 "carry their sources. 'general' questions are general "
                 "preparation, not verified as asked at this company."),
    }


# ---------------------------------------------------------------------------
# CLI wiring (attaches under a future `pm` parent parser)
# ---------------------------------------------------------------------------

def _render_text(questions: list[dict]) -> str:
    if not questions:
        return "No PM questions match. Try without filters."
    lines = []
    for i, e in enumerate(questions, 1):
        lines.append(f"{i}. [{e['company']} | {e['category']}] {e['q']}")
        lines.append(f"   source: {e['source']} ({e['reported']})")
        lines.append(f"   {e['url']}")
    return "\n".join(lines)


def _cmd_questions(args: argparse.Namespace) -> None:
    if args.query:
        results = search_questions(args.query)
    else:
        results = list_questions(category=args.category, company=args.company)
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(_render_text(results))


def register_pm(pm_subparsers) -> None:
    """Add the `questions` subcommand to a `pm` parent parser."""
    s = pm_subparsers.add_parser(
        "questions",
        help="Search the PM interview question bank.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("examples:\n"
                "  python -m candid pm questions --company google\n"
                "  python -m candid pm questions --category metrics --company meta\n"
                "  python -m candid pm questions --query \"A/B test\" --json"),
    )
    s.add_argument("--category", default=None,
                   help=f"Filter by category: {', '.join(CATEGORIES)}")
    s.add_argument("--company", default=None,
                   help="Filter by company (e.g. google, meta, amazon) or 'general'")
    s.add_argument("--query", default=None,
                   help="Free-text search over questions and sources")
    s.add_argument("--json", action="store_true",
                   help="Print matching questions as JSON")
    s.set_defaults(func=_cmd_questions)

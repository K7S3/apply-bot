"""PM-track interview prep packs: ``python -m candid pm prep``.

Builds a Markdown prep pack for a product-manager interview:

  1. Company-specific PM questions — pulled from the batch-93 question bank
     (``candid.pm_questions.list_questions``) via a *lazy* import, so this
     module keeps working when that sibling module is not merged yet. When
     the bank is missing, the pack says so and falls back to a generic PM
     checklist (clearly labeled as generic, never presented as verified).
  2. Role-relevant metrics to know — metric families a PM of this type is
     usually probed on (suggestions, not claimed as the company's actual
     metrics).
  3. A company-specific product teardown assignment.
  4. PM-flavored STAR story reminders.
  5. A day-before checklist.

The pack is rendered as Markdown and saved to
``DATA_DIR/pm_prep_<company>.md``. No network, no fabricated product facts.

Usage:
    python -m candid pm prep --company "Figma" --role "Growth PM" [--json]
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from candid import config as C


class PMPrepError(Exception):
    """Raised when a PM prep pack cannot be built."""


# ---------------------------------------------------------------------------
# Generic PM question checklist.
#
# Used only as a fallback when the ``candid.pm_questions`` bank module is not
# available (e.g. not yet merged) or has nothing for the company. Every pack
# labels these as generic prep, never as verified company questions.
# ---------------------------------------------------------------------------

_GENERIC_PM_QUESTIONS: list[tuple[str, str]] = [
    ("product_sense",
     "Pick a product you use daily. What is its north-star metric, and what "
     "would you change to move it 10% in a quarter?"),
    ("product_sense",
     "Design a feature that helps new users reach the 'aha' moment faster. "
     "How do you define the aha moment, and how do you know the feature worked?"),
    ("metrics",
     "The core metric dropped 15% week-over-week. Walk me through your "
     "debugging before you touch any code."),
    ("metrics",
     "How do you pick a north-star metric for a two-sided marketplace? "
     "What guardrails would you set?"),
    ("execution",
     "You have 4 engineers for 6 weeks. Walk me through how you scope and "
     "prioritize a roadmap for a v1 launch."),
    ("execution",
     "Engineering says your top feature will take 3x longer than planned. "
     "What do you do?"),
    ("behavioral",
     "Tell me about a time you influenced a team without authority. "
     "Who resisted, and what moved them?"),
    ("behavioral",
     "Tell me about a product decision you got wrong. What did the data "
     "tell you afterward, and what changed in how you work?"),
    ("strategy",
     "Should this company build, buy, or partner for [adjacent capability]? "
     "How do you frame the decision?"),
    ("estimation",
     "How many daily active users does [product] have? Talk through your "
     "assumptions out loud."),
]


def _company_questions(company: str) -> tuple[list[dict], str]:
    """Company PM questions + a source label.

    Lazily imports ``candid.pm_questions`` (signature
    ``list_questions(category=None, company=None)``) so this module works
    even if the sibling bank is not yet merged. Returns ``(questions,
    source_label)``; falls back to the generic PM checklist on ImportError.
    """
    try:
        # Prefer an already-loaded module (also honors test doubles injected
        # into sys.modules); fall back to a real import.
        _pq = sys.modules.get("candid.pm_questions")
        if _pq is None:
            from candid import pm_questions as _pq  # noqa: PLC0415 - lazy
        list_questions = _pq.list_questions
    except (ImportError, AttributeError):
        return ([{"category": cat, "q": q} for cat, q in _GENERIC_PM_QUESTIONS],
                "generic PM checklist (question bank not available)")
    try:
        raw = list_questions(company=company) or []
        if not raw:
            raw = list_questions(category="product") or []
    except TypeError:
        # Bank has a different call shape; use its company-agnostic default.
        try:
            raw = list_questions() or []
        except Exception:
            raw = []
    except Exception:
        raw = []
    questions: list[dict] = []
    for q in raw:
        if isinstance(q, dict) and q.get("q"):
            questions.append({"category": q.get("category", "product"),
                              "q": str(q["q"])})
        elif q:
            questions.append({"category": "product", "q": str(q)})
    if not questions:
        return ([{"category": cat, "q": q} for cat, q in _GENERIC_PM_QUESTIONS],
                "generic PM checklist (no company questions found in bank)")
    return questions, "candid.pm_questions bank"


# ---------------------------------------------------------------------------
# Metrics to know — role-relevant metric families (suggestions, never
# presented as the company's actual metrics).
# ---------------------------------------------------------------------------

_ROLE_METRICS: list[tuple[tuple[str, ...], list[str]]] = [
    (("growth", "acquisition", "activation", "marketing"),
     ["Acquisition: CAC, signups, install-to-signup conversion",
      "Activation: % completing the key action in first session / first week",
      "Retention: D1/D7/D30 cohorts and retention curves",
      "Referral: K-factor, invites sent vs. accepted",
      "Funnel: stage-by-stage conversion and the biggest drop-off"]),
    (("monetiz", "ads", "revenue", "pricing"),
     ["Revenue: total, ARPU, revenue per session",
      "Ads: CTR, CPC/CPM, fill rate, advertiser retention",
      "Subscriptions: MRR/ARR, paid conversion, churn",
      "Guardrails: satisfaction, opt-outs, complaint rate"]),
    (("search", "discovery", "recommend", "ranking", "feed", "personaliz"),
     ["CTR and long-CTR (clicks that lead to real engagement)",
      "Dwell time / time spent per session",
      "Abandonment and query-reformulation rate",
      "Diversity and novelty of results",
      "North star tied to user success, not raw clicks"]),
    (("marketplace", "supply", "demand", "two-sided", "logistics"),
     ["GMV and take rate",
      "Liquidity: % of searches with results, match rate",
      "Supply growth and activation; demand-side cohorts",
      "Cross-side network effects — which side constrains growth"]),
    (("b2b", "saas", "enterprise"),
     ["MRR/ARR, NRR and GRR",
      "Churn: logo churn and revenue churn",
      "Expansion: seat growth, upsell conversion",
      "Time-to-value and onboarding completion"]),
    (("consumer", "social", "core", "mobile"),
     ["DAU/MAU stickiness",
      "Session frequency and length",
      "Retention cohorts by acquisition channel",
      "Feature adoption and power-user behavior"]),
]

_DEFAULT_METRICS = [
    "North-star metric for the product area — and why you chose it",
    "Input metrics you could realistically move in a week",
    "AARRR: acquisition, activation, retention, referral, revenue",
    "Guardrail / counter metrics that keep you honest",
    "One metric you would instrument on day one, and why",
]


def metrics_for_role(role: str) -> list[str]:
    """Metric suggestions matched to the PM role type by keyword."""
    low = (role or "").lower()
    for keywords, metrics in _ROLE_METRICS:
        if any(k in low for k in keywords):
            return list(metrics)
    return list(_DEFAULT_METRICS)


_STAR_STORY_REMINDERS = [
    "**Product sense** — a time you picked the *right problem*, not just the "
    "right solution. What user insight or data made you choose it?",
    "**Execution under constraint** — shipped with too little time or too few "
    "people. What did you cut, and how did you defend the cut?",
    "**Influence without authority** — got eng, design, or data aligned when "
    "no one reported to you. Who resisted, and what moved them?",
    "**Metrics that mattered** — moved a metric that actually mattered. Name "
    "the metric, the baseline, the delta, and your personal contribution.",
    "**A launch that flopped** — what the data told you afterward, and what "
    "changed in how you work because of it.",
    "**Customer obsession** — a user insight (from research, support tickets, "
    "or a session replay) that changed the roadmap.",
]

_DAY_BEFORE_CHECKLIST = [
    "Finish the teardown assignment in this pack — or do one more 30-minute pass on your draft.",
    "Say your 6 STAR stories out loud, 2 minutes each, no notes. Time them.",
    "Rehearse your metrics answers: north star -> input metrics -> one experiment you designed.",
    "Skim the company's latest launch or blog post; prepare 2 sharp questions for your interviewers.",
    "Lock in your 'why this company, why PM' answer — 60 seconds, specific, no buzzwords.",
    "Logistics: outfit ready, route mapped, interviewers' names noted, laptop charged, water nearby.",
]


def teardown_prompt(company: str) -> str:
    """Company-specific product teardown assignment (no fabricated facts)."""
    co = company or "the company"
    return (
        f"**Teardown assignment — {co}.** Pick one {co} product you use at "
        "least weekly. Spend 60 minutes inside it as a detective: map the "
        "onboarding funnel, write down three moments of friction, name the "
        "metric you would move first and the experiment you would run. Bring "
        "one page of notes to the interview — or scaffold it with "
        f"`python -m candid pm teardown new --company \"{co}\" "
        "--product \"<product>\"`. Interviewers would rather debate a real "
        "opinion than a framework recital."
    )


def _safe_slug(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in text)[:60]


def build_pm_prep(company: str, role: str) -> dict:
    """Build the PM prep pack dict and save its Markdown rendering.

    Returns the pack dict, which also carries ``saved_path``.
    """
    if not (company or "").strip():
        raise PMPrepError("company is required")
    if not (role or "").strip():
        raise PMPrepError("role is required")
    company = company.strip()
    role = role.strip()

    questions, source = _company_questions(company)
    pack = {
        "company": company,
        "role": role,
        "generated": date.today().isoformat(),
        "company_pm_questions": questions,
        "question_source": source,
        "metrics_to_know": metrics_for_role(role),
        "teardown_prompt": teardown_prompt(company),
        "star_story_reminders": list(_STAR_STORY_REMINDERS),
        "day_before_checklist": list(_DAY_BEFORE_CHECKLIST),
    }
    markdown = render_pm_prep(pack)
    pack["saved_path"] = str(save_pm_prep(company, markdown))
    return pack


def render_pm_prep(pack: dict) -> str:
    """Render a pack dict as Markdown."""
    lines = [
        f"# PM Interview Prep — {pack['role']} @ {pack['company']}",
        f"*Generated {pack['generated']}*",
        "",
        "## 1. Company PM questions",
        "",
        f"_Source: {pack['question_source']}._",
        "",
    ]
    cur_cat = None
    for q in pack["company_pm_questions"]:
        cat = q.get("category", "product")
        if cat != cur_cat:
            cur_cat = cat
            lines += [f"### {cat.replace('_', ' ').title()}", ""]
        lines.append(f"- {q['q']}")
    lines += ["", "## 2. Metrics to know", ""]
    lines += [f"- {m}" for m in pack["metrics_to_know"]]
    lines += [
        "",
        "_These are the metric families interviewers usually probe for this "
        "PM type — suggestions, not the company's actual metrics._",
        "",
        "## 3. Teardown assignment",
        "",
        pack["teardown_prompt"],
        "",
        "## 4. STAR story reminders",
        "",
        "_Draft each as Situation → Task → Action → Result, 150+ words, "
        "said out loud — never invent details._",
        "",
    ]
    lines += [f"- {s}" for s in pack["star_story_reminders"]]
    lines += ["", "## 5. Day-before checklist", ""]
    lines += [f"- [ ] {item}" for item in pack["day_before_checklist"]]
    lines += [
        "",
        "---",
        "_PM track: question bank lives in `candid/pm_questions.py`; "
        "teardown templates via `python -m candid pm teardown new`._",
    ]
    return "\n".join(lines)


def save_pm_prep(company: str, markdown: str) -> Path:
    """Write the pack Markdown to ``DATA_DIR/pm_prep_<company>.md``."""
    C.ensure_data_dirs()
    out = C.DATA_DIR / f"pm_prep_{_safe_slug(company)}.md"
    out.write_text(markdown, encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# CLI registration (wired by the coordinator under ``python -m candid pm``).
# ---------------------------------------------------------------------------

def _cmd_prep(args) -> int:
    try:
        pack = build_pm_prep(args.company, args.role)
    except PMPrepError as e:
        print(f"error: {e}")
        return 1
    if args.json:
        print(json.dumps({k: v for k, v in pack.items()}, indent=2,
                         default=str))
    else:
        md_path = Path(pack["saved_path"])
        print(md_path.read_text(encoding="utf-8"))
        print(f"\nSaved to {pack['saved_path']}")
    return 0


def register_pm(pm_subparsers) -> None:
    """Register the ``prep`` subcommand on the ``pm`` parser."""
    p = pm_subparsers.add_parser(
        "prep",
        help="Build a PM interview prep pack (questions, metrics, teardown, STAR).",
        epilog="examples:\n"
               "  python -m candid pm prep --company Google --role \"Product Manager\"\n"
               "  python -m candid pm prep --company Stripe --role \"Growth PM\" --json\n")
    p.add_argument("--company", required=True, help="Company name")
    p.add_argument("--role", required=True, help="PM role title (e.g. 'Growth PM')")
    p.add_argument("--json", action="store_true",
                   help="Print the pack as JSON instead of Markdown")
    p.set_defaults(func=_cmd_prep)

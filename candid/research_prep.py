"""Research-taste interview prep and advisor/committee hard-Q&A.

Fully offline: stdlib only, no network, no APIs, no scraping.

Honesty rules for this module (non-negotiable):
- The research-question bank is curated and fully generic. No question is
  attributed to a real person, paper, venue, or company, and none is
  presented as "recently asked".
- "Model answers" are never written here. Self-review guidance is always a
  checklist of points a strong answer should cover, never a fabricated
  ideal answer.
- Hard questions generated from the user's project text reuse the user's
  own words as fill-in context; they never invent prior work, results, or
  baselines the user did not name.
"""

from __future__ import annotations

import json
import random
import re
from datetime import datetime, timezone

from candid import config as C

# --- storage (own dir under the shared data dir; convention from config.py) ---
RESEARCH_PREP_DIR = C.DATA_DIR / "research_prep"
HISTORY_FILE = "history.json"


def _sessions_dir():
    d = RESEARCH_PREP_DIR / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _history_path():
    RESEARCH_PREP_DIR.mkdir(parents=True, exist_ok=True)
    return RESEARCH_PREP_DIR / HISTORY_FILE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Feature 1: research-taste question bank
# ---------------------------------------------------------------------------
# Curated generic questions. Fields: q (question), hint (what it probes).
# No attributions anywhere — these are practice prompts, not reported asks.

RESEARCH_CATEGORIES = [
    "research_taste",
    "technical_depth",
    "failed_experiments",
    "collaboration",
    "research_vision",
]

RESEARCH_QUESTIONS: dict[str, list[dict[str, str]]] = {
    "research_taste": [
        {"q": "How do you pick research problems?", "hint": "Probes taste: problem selection heuristics, not just execution."},
        {"q": "Walk me through a paper you read recently and what you would do differently.", "hint": "Probes critical reading: can you spot weaknesses and propose a better angle?"},
        {"q": "What is a research result you found surprising, and why did it change your mind?", "hint": "Probes intellectual honesty and updating on evidence."},
        {"q": "How do you decide when a research direction is dead versus just hard?", "hint": "Probes judgment about sunk cost and negative results."},
        {"q": "What open problem in your area do you think is overrated, and why?", "hint": "Probes independent taste and willingness to disagree."},
        {"q": "Describe a time you chose a simpler approach over a fancier one. What tipped the decision?", "hint": "Probes simplicity bias and pragmatic trade-offs."},
    ],
    "technical_depth": [
        {"q": "Go as deep as you can on the core method of your best project: what are the key equations or algorithmic steps?", "hint": "Probes real ownership versus surface familiarity."},
        {"q": "What assumptions does your approach rely on, and which one is most fragile?", "hint": "Probes understanding of failure conditions, not just the happy path."},
        {"q": "If you had to re-derive your main result from scratch on a whiteboard, could you?", "hint": "Probes internalized understanding versus memorized slides."},
        {"q": "What is the computational bottleneck in your method, and what would you try first to remove it?", "hint": "Probes systems thinking and complexity awareness."},
        {"q": "How sensitive are your results to hyperparameters or data preprocessing choices?", "hint": "Probes experimental rigor and robustness checks."},
        {"q": "Explain the closest competing approach and steelman why someone would prefer it over yours.", "hint": "Probes breadth and fairness to alternatives."},
    ],
    "failed_experiments": [
        {"q": "Tell me about an experiment that failed and what you learned.", "hint": "Probes resilience and whether failure produced insight."},
        {"q": "Describe a hypothesis you were confident about that turned out wrong.", "hint": "Probes calibration: how you handle being wrong."},
        {"q": "What is the longest you chased a dead end, and what finally made you stop?", "hint": "Probes stop-loss discipline in research."},
        {"q": "Tell me about a bug or methodological mistake that invalidated results. How did you catch it?", "hint": "Probes validation habits and honesty about errors."},
        {"q": "Have you ever had to retract or walk back a claim? What happened?", "hint": "Probes integrity under pressure."},
    ],
    "collaboration": [
        {"q": "Tell me about a disagreement with a collaborator or advisor on research direction. How was it resolved?", "hint": "Probes conflict handling in intellectual work."},
        {"q": "How do you divide credit and authorship on joint projects?", "hint": "Probes fairness norms and communication."},
        {"q": "Describe mentoring or being mentored on a research project. What made it work?", "hint": "Probes ability to both teach and learn."},
        {"q": "How do you give critical feedback on someone else's draft or idea?", "hint": "Probes candor balanced with collegiality."},
        {"q": "Tell me about a project where you were not the expert in the room. How did you contribute?", "hint": "Probes humility and cross-disciplinary collaboration."},
    ],
    "research_vision": [
        {"q": "Where do you see your research area in five years, and what is your bet?", "hint": "Probes forward-looking taste and conviction."},
        {"q": "If you joined us, what would you work on in your first year and why?", "hint": "Probes fit: can you map your agenda to the team's?"},
        {"q": "What would a breakthrough in your area unlock for the field or for practice?", "hint": "Probes sense of impact beyond publications."},
        {"q": "What is a risky bet you would take if funding were not a constraint?", "hint": "Probes ambition and imagination."},
        {"q": "How do you balance short-term publishable work against long-term ambitious work?", "hint": "Probes portfolio thinking about a research career."},
    ],
}


def _qid(category: str, idx: int) -> str:
    return f"{category}-{idx + 1:02d}"


def list_questions(category: str | None = None) -> list[dict]:
    """Return the curated bank, optionally filtered to one category.

    Each entry: {"qid", "q", "category", "hint"}. Raises ValueError on an
    unknown category.
    """
    cats = [category] if category else RESEARCH_CATEGORIES
    if category and category not in RESEARCH_CATEGORIES:
        raise ValueError(f"Unknown category {category!r}. Choose from: {', '.join(RESEARCH_CATEGORIES)}")
    out = []
    for cat in cats:
        for i, item in enumerate(RESEARCH_QUESTIONS[cat]):
            out.append({"qid": _qid(cat, i), "q": item["q"], "category": cat, "hint": item["hint"]})
    return out


def _question_by_id(qid: str) -> dict | None:
    for q in list_questions():
        if q["qid"] == qid:
            return q
    return None


def build_session(questions: list[dict]) -> dict:
    """Create a fresh (unscored) practice session dict for the given questions."""
    return {
        "id": "rs-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
        "started_at": _now_iso(),
        "questions": [{"qid": q["qid"], "q": q["q"], "category": q["category"]} for q in questions],
        "scores": [],
    }


def _save_session(session: dict) -> None:
    path = _sessions_dir() / f"{session['id']}.json"
    path.write_text(json.dumps(session, indent=2))


def _append_history(record: dict) -> None:
    path = _history_path()
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"records": []}
    data["records"].append(record)
    path.write_text(json.dumps(data, indent=2))


def record_score(session: dict, qid: str, score: int) -> dict:
    """Record a 1-5 self-score for one question in a session.

    Mutates the session, persists it, and appends to the global history.
    Raises ValueError for an out-of-range score or an unknown qid.
    """
    if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
        raise ValueError(f"Score must be an integer 1-5, got {score!r}")
    question = next((q for q in session["questions"] if q["qid"] == qid), None)
    if question is None:
        raise ValueError(f"Unknown question id {qid!r} for this session")
    # Replace any earlier score for the same question (re-drills allowed).
    session["scores"] = [s for s in session["scores"] if s["qid"] != qid]
    session["scores"].append({"qid": qid, "category": question["category"], "score": score})
    _save_session(session)
    _append_history({
        "at": _now_iso(),
        "session": session["id"],
        "kind": "research_taste",
        "qid": qid,
        "category": question["category"],
        "score": score,
    })
    return session


def _read_history() -> list[dict]:
    try:
        return json.loads(_history_path().read_text())["records"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return []


def category_stats() -> dict[str, dict]:
    """Per-category aggregates across all recorded research-taste sessions.

    Returns {category: {"n": count, "avg": mean score}}. Categories with no
    recorded scores are omitted.
    """
    totals: dict[str, list[int]] = {}
    for rec in _read_history():
        if rec.get("kind") != "research_taste":
            continue
        totals.setdefault(rec["category"], []).append(rec["score"])
    return {
        cat: {"n": len(scores), "avg": round(sum(scores) / len(scores), 2)}
        for cat, scores in totals.items()
    }


def drill_next(limit: int = 3) -> list[dict]:
    """Weakest categories first — what to drill next.

    Returns up to `limit` entries {"category", "n", "avg"} sorted by ascending
    average score.
    """
    stats = category_stats()
    ranked = sorted(stats.items(), key=lambda kv: kv[1]["avg"])
    return [{"category": cat, **vals} for cat, vals in ranked[:limit]]


def practice_session(n: int = 5, categories: list[str] | None = None, seed: int | None = None) -> dict:
    """Interactive practice: present N questions one at a time, self-score 1-5.

    Questions are sampled across the requested categories (round-robin so each
    category is represented). Type a score 1-5, or "skip" to move on. At the
    end, prints per-category averages and "drill next" suggestions.
    """
    if n < 1:
        raise ValueError("n must be at least 1")
    cats = list(categories) if categories else list(RESEARCH_CATEGORIES)
    for cat in cats:
        if cat not in RESEARCH_CATEGORIES:
            raise ValueError(f"Unknown category {cat!r}. Choose from: {', '.join(RESEARCH_CATEGORIES)}")

    rng = random.Random(seed)
    pools = {cat: list_questions(cat) for cat in cats}
    picked: list[dict] = []
    # Round-robin so every requested category shows up before repeats.
    while len(picked) < n and any(pools.values()):
        for cat in cats:
            if len(picked) >= n or not pools[cat]:
                continue
            picked.append(pools[cat].pop(rng.randrange(len(pools[cat]))))

    session = build_session(picked)
    print(f"\nResearch-taste practice: {len(picked)} questions. Score yourself 1-5 after each.\n")
    try:
        for i, q in enumerate(session["questions"], 1):
            print(f"[{i}/{len(picked)}] ({q['category']})")
            print(f"  Q: {q['q']}")
            while True:
                raw = input("  Your score 1-5 (or 'skip'): ").strip().lower()
                if raw in ("skip", "s", ""):
                    break
                if raw.isdigit() and 1 <= int(raw) <= 5:
                    record_score(session, q["qid"], int(raw))
                    break
                print("  Please enter 1-5 or 'skip'.")
            print()
    except (EOFError, KeyboardInterrupt):
        print("\nSession interrupted — progress so far is saved.")

    stats = category_stats()
    if stats:
        print("Per-category averages (all sessions):")
        for cat, vals in sorted(stats.items(), key=lambda kv: kv[1]["avg"]):
            print(f"  {cat}: {vals['avg']} over {vals['n']} scored")
        print("\nDrill next (weakest first):")
        for d in drill_next():
            print(f"  - {d['category']} (avg {d['avg']}, n={d['n']})")
    else:
        print("No scores recorded yet.")
    return session


# ---------------------------------------------------------------------------
# Feature 2: advisor/committee hard-Q&A from the user's project text
# ---------------------------------------------------------------------------

PRIOR_WORK_RE = re.compile(
    r"\b(prior work|previous work|compared to|compared with|versus|\bvs\.?|\bbaseline\b|"
    r"state[- ]of[- ]the[- ]art|\bsota\b|existing (method|approach|work))\b",
    re.IGNORECASE,
)
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_RE.split(text.strip()) if s.strip()]


def _prior_work_snippet(text: str) -> str:
    """Best-effort quote of the closest prior work the user themselves named.

    Returns "" when the user named none — templates then fall back to a
    generic phrasing rather than inventing one.
    """
    for s in _sentences(text):
        if PRIOR_WORK_RE.search(s):
            return s[:160]
    return ""


def _topic_hint(text: str) -> str:
    """A short neutral label for the project, built only from the user's words."""
    first = _sentences(text)[0] if _sentences(text) else ""
    words = first.split()
    return " ".join(words[:8]) + ("..." if len(words) > 8 else "")


def generate_hard_questions(project_text: str) -> list[dict]:
    """Generate tough PI/committee questions from the user's project text.

    Returns a list of {"question", "checklist"} where the checklist is a
    generic list of points a strong answer should cover — never fabricated
    content. Raises ValueError on empty input.
    """
    text = (project_text or "").strip()
    if not text:
        raise ValueError("project_text must not be empty")
    prior = _prior_work_snippet(text)
    prior_ref = f'the "{prior}" you described' if prior else "the prior work you build on"
    topic = _topic_hint(text)

    templates: list[tuple[str, list[str]]] = [
        (
            f"What is actually new here versus {prior_ref}?",
            [
                "State the single-sentence delta: what changes, concretely",
                "Separate problem novelty from method novelty — which is it?",
                "Name the specific limitation of prior work that you remove",
                "Rule out 'just more tuning / more compute' as the explanation",
                "Say what evidence would falsify your novelty claim",
            ],
        ),
        (
            "Are your baselines strong enough, or did you choose weak ones to look good?",
            [
                "Name the strongest relevant baseline for each sub-claim",
                "Give baselines a fair budget: same data, comparable compute, tuned settings",
                "Report what happens with default versus tuned baselines",
                "Ablate your own method against each baseline component",
                "Acknowledge any baseline you could not run and why",
            ],
        ),
        (
            "Which part of your method actually matters? Walk me through the ablation.",
            [
                "Remove one component at a time and report the metric delta",
                "Rank components by contribution, with numbers",
                "Include the ablation you expected to matter but did not",
                "Report the cost (compute, complexity) each component adds",
                "Say which component you would drop first under a deadline",
            ],
        ),
        (
            "Where does this break? Give me concrete failure cases.",
            [
                "Show 2-3 specific inputs or regimes where it fails",
                "Characterize the failure boundary, not just anecdotes",
                "Quantify how often it fails on realistic data",
                "Say whether failures are silent or detectable at runtime",
                "Explain what you tried that did not fix them",
            ],
        ),
        (
            "What are the honest limits of this work — what did you choose not to claim?",
            [
                "List the key assumptions baked into the setup",
                "State the data and domain limits explicitly",
                "Describe what a negative or null result would look like",
                "Name the most likely objection from a skeptical reviewer",
                "Draw the line: what this work does NOT show",
            ],
        ),
        (
            f"Why should anyone care about {topic if topic else 'this work'}? Who is blocked without it?",
            [
                "Name who benefits, concretely — not 'the community' in the abstract",
                "Describe what is impossible or expensive to do today",
                "Translate the improvement into practical terms (time, cost, capability)",
                "Give the downstream use that motivates the problem choice",
                "Steel-man the 'so what' objection in one sentence, then answer it",
            ],
        ),
        (
            "If you had six more months, what is the single most important next experiment?",
            [
                "Pick one crisp next question, not a laundry list",
                "Explain why it outranks the alternatives",
                "Say what it would change about your current conclusions",
                "Name what you would stop doing to make room for it",
                "Connect it back to the core claim, not a side quest",
            ],
        ),
    ]
    return [
        {"qid": f"hard-{i:02d}", "question": q, "checklist": c}
        for i, (q, c) in enumerate(templates)
    ]


def practice_hard_qa(questions: list[dict]) -> list[dict]:
    """Interactive hard-Q&A: answer each question, review the checklist, self-score.

    Returns the list of {"qid", "question", "score" | None} records; scores are
    appended to the global history for qa_stats().
    """
    if not questions:
        raise ValueError("questions must not be empty")
    results: list[dict] = []
    print(f"\nHard-Q&A practice: {len(questions)} questions. Answer, review the checklist, then self-score 1-5.\n")
    try:
        for i, item in enumerate(questions, 1):
            print(f"[{i}/{len(questions)}]")
            print(f"  Q: {item['question']}")
            input("  Press Enter when you have your answer ready... ")
            print("  Checklist — a strong answer covers:")
            for point in item["checklist"]:
                print(f"    - {point}")
            while True:
                raw = input("  Your score 1-5 (or 'skip'): ").strip().lower()
                if raw in ("skip", "s", ""):
                    score = None
                    break
                if raw.isdigit() and 1 <= int(raw) <= 5:
                    score = int(raw)
                    break
                print("  Please enter 1-5 or 'skip'.")
            print()
            results.append({"qid": item.get("qid", f"hard-{i - 1:02d}"),
                            "question": item["question"], "score": score})
            if score is not None:
                _append_history({
                    "at": _now_iso(),
                    "session": "hardqa-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
                    "kind": "hard_qa",
                    "qid": results[-1]["qid"],
                    "question": item["question"],
                    "score": score,
                })
    except (EOFError, KeyboardInterrupt):
        print("\nPractice interrupted — progress so far is saved.")
    return results


def qa_stats() -> list[dict]:
    """Per-question aggregates across all hard-Q&A practice runs.

    Returns [{"qid", "question", "n", "avg"}] sorted by ascending average
    (weakest first). Empty list when nothing is recorded yet.
    """
    totals: dict[str, dict] = {}
    for rec in _read_history():
        if rec.get("kind") != "hard_qa":
            continue
        entry = totals.setdefault(rec["qid"], {"question": rec.get("question", rec["qid"]),
                                               "scores": []})
        entry["scores"].append(rec["score"])
    out = [
        {"qid": qid, "question": e["question"], "n": len(e["scores"]),
         "avg": round(sum(e["scores"]) / len(e["scores"]), 2)}
        for qid, e in totals.items()
    ]
    return sorted(out, key=lambda d: d["avg"])

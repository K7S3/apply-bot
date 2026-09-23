"""Interactive security-engineer mock interview with rubric scoring.

Flow:
  1. run_mock() pulls questions from candid.security_questions. That module is
     written by a parallel worker, so it is imported lazily (only when a
     session runs, never at import time) and a clear error is raised if it is
     still missing.
  2. Each question is asked on stdin; answers are multi-line, finished by a
     single "." line.
  3. score_answer() grades each answer against RUBRIC with deterministic
     heuristics: completeness, threat-coverage, tradeoffs, clarity.
  4. summarize_session() aggregates the per-answer scores into a session
     report.

CLI:
    python -m candid.security_mock [n] [--category web]
"""

from __future__ import annotations

import importlib
import random
import re
import sys

RUBRIC = [
    {
        "id": "completeness",
        "name": "Completeness",
        "description": "Did the answer address the question? Measured as the "
                       "fraction of expected_points covered.",
    },
    {
        "id": "threat-coverage",
        "name": "Threat coverage",
        "description": "Did the answer name concrete threats and attack "
                       "vectors? Measured by security keyword hits.",
    },
    {
        "id": "tradeoffs",
        "name": "Tradeoffs",
        "description": "Did the answer acknowledge constraints, costs, or "
                       "competing goals? Measured by tradeoff language.",
    },
    {
        "id": "clarity",
        "name": "Clarity",
        "description": "Was the answer structured? Measured by structure "
                       "signals such as bullets, numbering, and sequencing words.",
    },
]

_TOKEN_RE = re.compile(r"[a-z0-9+#]+")
_BULLET_RE = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)]|\([a-z0-9]+\))\s+")

_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "been", "by", "it", "its", "as",
    "at", "this", "that", "these", "those", "from", "into", "you", "your",
    "we", "our", "they", "their", "them", "he", "she", "his", "her",
    "not", "no", "do", "does", "did", "can", "could", "should", "would",
    "will", "have", "has", "had", "than", "then", "so", "such", "if",
    "but", "all", "any", "each", "more", "most", "other", "some", "only",
    "also", "very", "just", "over", "under", "up", "out", "about",
    "between", "through", "when", "where", "which", "who", "what", "how",
    "there", "here", "both", "own", "same", "once", "being",
})

THREAT_KEYWORDS = [
    # attack classes
    "attack", "attacker", "threat", "exploit", "vulnerability",
    "vulnerabilities", "vulnerable", "cve", "bypass", "injection", "xss",
    "ssrf", "sqli", "csrf", "rce", "xxe", "lfi", "rfi", "phishing",
    "spearphishing", "whaling", "mitm", "eavesdropping", "replay",
    "brute force", "credential stuffing", "password spraying",
    "session hijacking", "clickjacking", "deserialization",
    "race condition", "buffer overflow", "privilege escalation",
    "directory traversal", "command injection", "supply chain",
    "zero-day", "zeroday",
    # malware / payloads
    "malware", "ransomware", "rootkit", "trojan", "backdoor", "worm",
    "payload", "shellcode", "dropper",
    # controls / crypto / identity
    "encryption", "decrypt", "tls", "https", "hsts", "mfa", "2fa",
    "otp", "auth", "authentication", "authorization", "oauth", "oidc",
    "saml", "jwt", "rbac", "acl", "least privilege", "zero trust",
    "defense in depth", "hardening", "sandbox", "firewall", "waf", "ids",
    "ips", "siem", "honeypot", "patch", "patching",
    # data / appsec
    "sanitize", "sanitization", "validate", "validation", "encode",
    "encoding", "csp", "cors", "cookie", "session", "token", "secret",
    "secrets", "credential", "key management", "hashing", "salting",
    # process
    "threat model", "threat modeling", "stride", "attack surface",
    "pen test", "pentest", "red team", "incident response", "forensics",
    "logging", "audit", "monitoring", "anomaly",
]

TRADEOFF_MARKERS = [
    "tradeoff", "trade-off", "trade off", "on the other hand", "cost",
    "costs", "costly", "expensive", "latency", "overhead", "usability",
    "usable", "depends", "depending", "however", "whereas", "although",
    "though", "pros and cons", "downside", "upside", "tension",
    "in exchange", "at the expense", "sacrifice", "balancing",
    "acceptable risk", "risk appetite", "it depends",
]

_SEQ_WORDS = ("first", "second", "third", "then", "finally", "lastly", "next")


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall((text or "").lower())
            if t not in _STOPWORDS and len(t) > 1]


def _count_hits(answer: str, keywords: list[str]) -> int:
    """Count distinct keyword hits: single words match tokens, phrases match substrings."""
    lowered = (answer or "").lower()
    tokens = set(_TOKEN_RE.findall(lowered))
    hits = 0
    for kw in keywords:
        if " " in kw:
            if kw in lowered:
                hits += 1
        elif kw in tokens:
            hits += 1
    return hits


def score_answer(question: dict, answer: str) -> dict:
    """Score a free-text answer against the rubric.

    Returns {"scores": {dim: 0-5 int}, "matched_points": [...],
    "missed_points": [...], "feedback": [human-readable strings]}.
    """
    answer = answer or ""
    points = list(question.get("expected_points") or [])
    answer_tokens = set(_tokens(answer))

    matched, missed = [], []
    for point in points:
        point_tokens = set(_tokens(point))
        if not point_tokens:
            continue
        overlap = len(point_tokens & answer_tokens) / len(point_tokens)
        (matched if overlap >= 0.3 else missed).append(point)

    if points:
        completeness = int(round(5 * len(matched) / len(points)))
    else:
        n = len(answer.strip())
        completeness = 1 if n < 30 else (3 if n < 120 else 4)

    threat_hits = _count_hits(answer, THREAT_KEYWORDS)
    threat = min(5, threat_hits)

    tradeoff_hits = _count_hits(answer, TRADEOFF_MARKERS)
    tradeoffs = min(5, tradeoff_hits)

    bullet_lines = len(_BULLET_RE.findall(answer))
    seq_hits = sum(1 for w in _SEQ_WORDS if w in answer_tokens)
    paragraphs = [p for p in re.split(r"\n\s*\n", answer.strip()) if p.strip()]
    short_paras = (len(paragraphs) >= 2
                   and sum(len(p) for p in paragraphs) / len(paragraphs) < 500)
    signals = (2 if bullet_lines >= 2 else bullet_lines) \
        + min(2, seq_hits) + (1 if short_paras else 0)
    clarity = min(5, signals)

    scores = {
        "completeness": completeness,
        "threat-coverage": threat,
        "tradeoffs": tradeoffs,
        "clarity": clarity,
    }

    feedback = []
    if points:
        feedback.append(
            f"Completeness {completeness}/5: covered {len(matched)} of "
            f"{len(points)} expected points.")
    else:
        feedback.append(
            f"Completeness {completeness}/5: scored on answer length (this "
            "question lists no expected points).")
    if matched:
        feedback.append("Covered: " + "; ".join(matched))
    if missed:
        feedback.append("Missed: " + "; ".join(missed))
    feedback.append(
        f"Threat coverage {threat}/5: {threat_hits} security terms spotted. "
        "Name concrete attacks and controls to raise this.")
    feedback.append(
        f"Tradeoffs {tradeoffs}/5: {tradeoff_hits} tradeoff phrases spotted. "
        "Call out costs, latency, or usability tensions explicitly.")
    if bullet_lines >= 2:
        feedback.append(
            f"Clarity {clarity}/5: good structure with {bullet_lines} "
            "bulleted/numbered steps.")
    else:
        feedback.append(
            f"Clarity {clarity}/5: use bullets or numbered steps and "
            "sequencing words (first, second, finally).")

    return {
        "scores": scores,
        "matched_points": matched,
        "missed_points": missed,
        "feedback": feedback,
    }


def _load_bank() -> list[dict]:
    """Load the question bank from candid.security_questions (lazy import).

    Raises a clear RuntimeError if the module is missing or exposes no
    usable question list. Never imported at module import time.
    """
    try:
        sq = importlib.import_module("candid.security_questions")
    except ImportError as exc:
        raise RuntimeError(
            "candid.security_questions is not available yet. It is being "
            "written by a parallel worker; a mock session cannot run until "
            "it lands in the candid package."
        ) from exc
    for attr in ("QUESTIONS", "QUESTION_BANK", "BANK", "SECURITY_QUESTIONS"):
        bank = getattr(sq, attr, None)
        if bank:
            return [_normalize_question(q) for q in bank]
    for attr in ("get_questions", "all_questions", "list_questions", "get_bank"):
        fn = getattr(sq, attr, None)
        if callable(fn):
            return [_normalize_question(q) for q in fn()]
    raise RuntimeError(
        "candid.security_questions loaded but exposes no question list "
        "(looked for QUESTIONS / QUESTION_BANK / BANK / SECURITY_QUESTIONS "
        "attributes or a get_questions-style function).")


def _normalize_question(entry: dict) -> dict:
    if not isinstance(entry, dict):
        raise RuntimeError("security_questions bank entries must be dicts")
    text = (entry.get("q") or entry.get("question") or entry.get("text")
            or entry.get("prompt") or "")
    return {
        "id": entry.get("id", ""),
        "question": entry.get("question", text),
        "text": text,
        "category": str(entry.get("category", "general")),
        "expected_points": list(entry.get("expected_points") or []),
    }


def _format_result(result: dict) -> str:
    lines = ["Scores:"]
    for dim in RUBRIC:
        lines.append(f"  {dim['name']}: {result['scores'][dim['id']]}/5")
    lines.extend("  " + f for f in result["feedback"])
    return "\n".join(lines)


def run_mock(n: int = 5, category: str | None = None) -> list[dict]:
    """Run an interactive mock session: ask n questions, score each answer.

    Answers are read from stdin, one multi-line answer per question, ended by
    a single "." line. Prints per-question scores and the session summary;
    returns the list of per-question result dicts.
    """
    bank = _load_bank()
    if category:
        bank = [q for q in bank if q["category"].lower() == category.lower()]
        if not bank:
            print(f"No security questions found for category '{category}'.")
            return []
    chosen = random.sample(bank, min(n, len(bank)))
    results = []
    for i, q in enumerate(chosen, 1):
        print(f"\nQuestion {i}/{len(chosen)} [{q['category']}]:")
        print(q["text"] or q["question"])
        print("Answer below (multi-line). End with a single '.' on its own line:")
        lines = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line.strip() == ".":
                break
            lines.append(line)
        result = score_answer(q, "\n".join(lines))
        result["question_id"] = q.get("id", "")
        results.append(result)
        print(_format_result(result))
    summary = summarize_session(results)
    print("\nSession summary:")
    print(summary)
    return results


def summarize_session(results: list[dict]) -> dict:
    """Aggregate per-question score dicts into a session report.

    Returns {"per_dimension_avg": {dim: float}, "overall": float,
    "strongest": dim id, "weakest": dim id}.
    """
    dims = [d["id"] for d in RUBRIC]
    per_dimension_avg = {}
    for dim in dims:
        vals = [r.get("scores", {}).get(dim, 0) for r in results]
        per_dimension_avg[dim] = round(sum(vals) / len(vals), 2) if vals else 0.0
    overall = (round(sum(per_dimension_avg.values()) / len(per_dimension_avg), 2)
               if per_dimension_avg else 0.0)
    has_results = bool(results)
    return {
        "per_dimension_avg": per_dimension_avg,
        "overall": overall,
        "strongest": max(per_dimension_avg, key=per_dimension_avg.get) if has_results else None,
        "weakest": min(per_dimension_avg, key=per_dimension_avg.get) if has_results else None,
    }


def _cli(argv: list[str]) -> None:
    n = 5
    category = None
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--category" and args:
            category = args.pop(0)
        elif a.lstrip("-").isdigit():
            n = int(a.lstrip("-"))
    run_mock(n=n, category=category)


if __name__ == "__main__":
    _cli(sys.argv[1:])

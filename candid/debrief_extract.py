"""Extract debrief signals from an interview transcript.

Transcript format: a list of turn dicts, each with ``prompt`` (what the
interviewer asked), ``answer`` (your response), and optionally ``ts``
(timestamp, ISO or free text). A ``debrief_voice`` transcript dict with a
``turns`` key is also accepted (turns are read from it directly).

Two tiers:

1. ``extract(transcript)`` - deterministic heuristic extractor. Fully
   offline: regex/cue-phrase matching plus simple sentence scoring.
   Returns::

       {
           "key_questions": [...],   # interviewer prompts, deduped, in order
           "key_answers": [...],    # condensed answers, aligned with questions
           "weak_spots": [...],     # phrases/sentences signaling struggle
           "action_items": [...],   # follow-ups / things to study
           "one_paragraph_summary": "...",
           "enhanced": False,       # the LLM tier upgrades this
       }

2. ``extract_enhanced(transcript)`` - tries the local-LLM tier: sends the
   transcript plus the heuristic output to an Ollama model on
   localhost:11434 and merges any returned improvements. Only ever uses a
   LOCAL model (env overrides ``CANDID_OLLAMA_URL`` / ``CANDID_OLLAMA_MODEL``);
   never touches a paid API. On ANY failure (no server, timeout, bad
   response) it silently falls back to the heuristic result with
   ``enhanced=False``. ``extract`` alone is enough for the debrief store.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime

# ---------------------------------------------------------------------------
# cue lexicons (case-insensitive)
# ---------------------------------------------------------------------------

# Strong signals of struggle: one hit is enough to flag the answer.
# Each entry is (human label, regex pattern).
_STRONG_WEAK = [
    ("stumped", r"stumped"), ("blanked", r"blanked"),
    ("fumbled", r"fumbled"), ("stumbled", r"stumbled"),
    ("didn't know", r"didn'?t know"), ("don't know", r"don'?t know"),
    ("never learned", r"never learned"),
    ("no idea", r"no idea"), ("couldn't answer", r"couldn'?t answer"),
    ("struggled", r"struggled (with|on|to)"),
    ("totally lost", r"totally (lost|blank)"),
    ("out of my depth", r"out of my depth"),
]
# Softer signals: hedging, fillers, explicit pauses.
_SOFT_WEAK = [
    r"not sure", r"unsure", r"shaky", r"rough patch",
    r"not confident", r"not (really|very) confident",
    r"\bhmm+\b", r"\buh+\b", r"\bum+\b", r"\berr+\b",
    r"let me think", r"give me a (second|moment|minute)",
    r"\[pause\]|\(pause\)", r"\b\.\.\.\s",
    r"\bi guess\b", r"sort of", r"kind of", r"maybe\b.*\bor\b.*\bmaybe\b",
    r"i (may be|might be) wrong",
]

_ACTION_CUES = [
    r"follow[- ]up", r"\bi should\b", r"\bi'?ll\b", r"\bi will\b",
    r"need to", r"have to", r"must ", r"todo", r"action item",
    r"\bstudy\b", r"\breview\b", r"learn (more|about)", r"read up",
    r"\bpractice\b", r"prepare", r"look into", r"dig into",
    r"work on", r"brush up", r"revisit",
]

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _compile(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_STRONG_WEAK_RE = [(label, re.compile(p, re.IGNORECASE))
                  for label, p in _STRONG_WEAK]
_SOFT_WEAK_RE = _compile(_SOFT_WEAK)
_ACTION_RE = _compile(_ACTION_CUES)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text or "") if s.strip()]


def _shorten(text: str, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit)
    return text[: cut if cut > 40 else limit].rstrip(",;:") + "..."


def _key_questions(transcript: list[dict]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for t in transcript:
        q = re.sub(r"\s+", " ", str(t.get("prompt") or "")).strip()
        if q and q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out


def _key_answers(transcript: list[dict], max_n: int = 8) -> list[str]:
    """Condense each answer to its leading sentence(s), aligned with questions."""
    out: list[str] = []
    for t in transcript:
        if not str(t.get("prompt") or "").strip():
            continue
        sents = _sentences(str(t.get("answer") or ""))
        lead = " ".join(sents[:2]) if sents else ""
        out.append(_shorten(lead or "(no answer recorded)"))
        if len(out) >= max_n:
            break
    return out


def _weak_spots(transcript: list[dict]) -> list[str]:
    out: list[str] = []
    for t in transcript:
        answer = str(t.get("answer") or "")
        if len(answer.strip()) < 3:
            continue
        question = _shorten(str(t.get("prompt") or "the question"), 80)
        strong_hits = {label for label, p in _STRONG_WEAK_RE if p.search(answer)}
        soft_hits = sum(len(p.findall(answer)) for p in _SOFT_WEAK_RE)
        if not strong_hits and soft_hits < 3:
            continue
        # evidence: the most incriminating sentence in the answer
        sents = _sentences(answer)
        def _score(s: str) -> int:
            return (5 * sum(1 for _, p in _STRONG_WEAK_RE if p.search(s))
                    + sum(1 for p in _SOFT_WEAK_RE if p.search(s)))
        evidence = max(sents, key=_score) if sents else _shorten(answer, 100)
        label = ", ".join(sorted(strong_hits)) or "heavy hedging / long pauses"
        out.append(f"On '{question}': {_shorten(evidence, 120)} [{label}]")
    return out


def _action_items(transcript: list[dict]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for t in transcript:
        for s in _sentences(str(t.get("answer") or "")):
            if any(p.search(s) for p in _ACTION_RE):
                item = _shorten(s, 140)
                if item.lower() not in seen:
                    seen.add(item.lower())
                    out.append(item)
    return out


def _one_paragraph_summary(questions: list[str], spots: list[str],
                           actions: list[str]) -> str:
    def _tidy(seg: str) -> str:
        return _shorten(seg, 60).rstrip(".")
    topics = "; ".join(_tidy(q) for q in questions[:3]) or "general discussion"
    parts = [f"The interview covered {len(questions)} question(s), "
             f"centered on: {topics}."]
    if spots:
        parts.append(f"Watch out for: {'; '.join(_tidy(s) for s in spots[:2])}.")
    else:
        parts.append("No clear weak spots surfaced.")
    if actions:
        parts.append(f"Next: {'; '.join(_tidy(a) for a in actions[:2])}.")
    return " ".join(parts)


def _normalize_transcript(transcript) -> list[dict]:
    """Accept the canonical turn list, or a debrief_voice-style transcript
    dict with a ``turns`` key (each turn carries prompt/answer)."""
    if isinstance(transcript, dict) and isinstance(transcript.get("turns"), list):
        turns = []
        for t in transcript["turns"]:
            if not isinstance(t, dict):
                continue
            turns.append({
                "prompt": t.get("prompt"),
                "answer": t.get("answer"),
                "ts": t.get("ts") or t.get("answered_at"),
            })
        return turns
    return transcript


def extract(transcript) -> dict:
    """Deterministic heuristic extraction from a transcript. Fully offline.

    ``transcript`` is a list of {prompt, answer, ts} turn dicts, or a
    transcript dict with a ``turns`` key (see ``candid.debrief_voice``).
    Raises ValueError if the transcript is empty or malformed.
    """
    transcript = _normalize_transcript(transcript)
    if not isinstance(transcript, list) or not transcript:
        raise ValueError("transcript must be a non-empty list of turn dicts.")
    if not all(isinstance(t, dict) for t in transcript):
        raise ValueError("transcript must be a list of turn dicts.")
    questions = _key_questions(transcript)
    answers = _key_answers(transcript)
    spots = _weak_spots(transcript)
    actions = _action_items(transcript)
    return {
        "key_questions": questions,
        "key_answers": answers,
        "weak_spots": spots,
        "action_items": actions,
        "one_paragraph_summary": _one_paragraph_summary(questions, spots, actions),
        "enhanced": False,
    }


# ---------------------------------------------------------------------------
# local-LLM tier (Ollama only; degrades cleanly)
# ---------------------------------------------------------------------------

_OLLAMA_URL = os.environ.get("CANDID_OLLAMA_URL", "http://localhost:11434")
_OLLAMA_MODEL = os.environ.get("CANDID_OLLAMA_MODEL", "deepseek-r1:8b")
_OLLAMA_TIMEOUT_S = float(os.environ.get("CANDID_OLLAMA_TIMEOUT", "8"))


def _ollama_available() -> bool:
    """Fast reachability check against the local Ollama server."""
    try:
        req = urllib.request.Request(f"{_OLLAMA_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3):
            return True
    except Exception:
        return False


def _ollama_generate(prompt: str) -> str | None:
    """One non-streaming Ollama call. Returns the text or None on any failure."""
    payload = json.dumps({
        "model": _OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 800},
    }).encode()
    try:
        req = urllib.request.Request(
            f"{_OLLAMA_URL}/api/generate", data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=_OLLAMA_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return (data.get("response") or "").strip() or None
    except Exception:
        return None


def _parse_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _dedupe(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in seq:
        k = str(s).strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(str(s))
    return out


def _merge_heuristic(base: dict, llm: dict) -> dict:
    """Blend LLM output over the heuristic base; heuristic wins on empties."""
    merged = dict(base)
    for key in ("key_questions", "key_answers", "weak_spots", "action_items"):
        vals = llm.get(key)
        if isinstance(vals, list) and any(str(v).strip() for v in vals):
            merged[key] = _dedupe([*base[key], *[str(v).strip() for v in vals if str(v).strip()]])
    summary = llm.get("one_paragraph_summary")
    if isinstance(summary, str) and summary.strip():
        merged["one_paragraph_summary"] = summary.strip()
    merged["enhanced"] = True
    return merged


def extract_enhanced(transcript: list[dict]) -> dict:
    """Try the local-LLM tier, fall back to the heuristic on any failure.

    Never raises for LLM reasons; never uses a paid API or the network
    beyond the local Ollama endpoint.
    """
    base = extract(transcript)
    if not _ollama_available():
        return base
    turns = []
    for i, t in enumerate(_normalize_transcript(transcript), 1):
        turns.append(f"--- Turn {i} ---\n"
                     f"INTERVIEWER: {t.get('prompt', '')}\n"
                     f"CANDIDATE: {t.get('answer', '')}")
    prompt = (
        "You are debriefing a job interview. Below is the transcript, plus a "
        "heuristic extraction already made from it. Improve it: tighten the "
        "key questions and answers, spot any additional weak spots where the "
        "candidate struggled (hedging, pauses, wrong turns), and list concrete "
        "action items (what to study or follow up on).\n\n"
        "TRANSCRIPT:\n" + "\n".join(turns) + "\n\n"
        "HEURISTIC EXTRACTION:\n" + json.dumps(base, indent=2) + "\n\n"
        "Reply with ONLY a JSON object with keys: key_questions (list of str), "
        "key_answers (list of str), weak_spots (list of str), action_items "
        "(list of str), one_paragraph_summary (str)."
    )
    text = _ollama_generate(prompt)
    parsed = _parse_json(text) if text else None
    if not parsed:
        return base
    return _merge_heuristic(base, parsed)


def transcript_from_pairs(pairs: list[tuple[str, str]]) -> list[dict]:
    """Build a transcript from (prompt, answer) pairs. Timestamps optional."""
    now = datetime.now().isoformat(timespec="seconds")
    return [{"prompt": q, "answer": a, "ts": now} for q, a in pairs]

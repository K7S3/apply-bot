"""Career story builder: narrative arc + multi-length "tell me about yourself" pitches.

The arc turns resume bullets into a past -> present -> future story:

- past:    earliest roles + education
- present: current role + top skills
- future:  the user's stated target role(s), or an honest placeholder

Every arc segment records ``sources``: the profile bullet ids
(``exp{i}-b{j}``) and education ids (``edu{i}``) it was built from.

Pitches (30s / 2min / 5min, composed at ~140 wpm) are assembled from the
arc: resume bullets are quoted verbatim, never paraphrased, and thin
profiles are padded with honest ``[fill in: ...]`` placeholders instead
of invented facts.

Everything here is deterministic and template-based: no network, no
LLMs, no invented metrics, companies, dates, or achievements.

State lives in DATA_DIR/"narrative.json" under the top-level keys
"arc" and "pitches" only. The file is always read defensively and
sibling keys owned by other workers are preserved on write.
"""

from __future__ import annotations

import json
from pathlib import Path

from candid import config as C
from candid import profile as P


class NarrativeError(Exception):
    """Raised for narrative-arc / pitch problems."""


# pitch length -> (min words, max words); composed at ~140 wpm
PITCH_LENGTHS: dict[str, tuple[int, int]] = {
    "30s": (60, 75),
    "2min": (260, 300),
    "5min": (650, 700),
}
_WPM = 140

_length_ALIASES = {
    "30s": "30s", "30sec": "30s", "30": "30s",
    "2min": "2min", "2m": "2min", "2": "2min",
    "5min": "5min", "5m": "5min", "5": "5min",
}

_QUOTE_INTROS = ["For example", "Another example", "As another example", "One more example"]


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------

def _narrative_path() -> Path:
    return C.DATA_DIR / "narrative.json"


def _load_state() -> dict:
    p = _narrative_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NarrativeError(f"Narrative file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise NarrativeError(f"Narrative file {p} should contain a JSON object.")
    return data


def _save_state(state: dict) -> Path:
    p = _narrative_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return p


def _get_profile(profile: dict | None) -> dict:
    if profile is not None:
        return profile
    try:
        return P.load_profile()
    except P.OnboardError as exc:
        raise NarrativeError(
            "No profile found. Run onboarding first:\n"
            "    python -m candid onboard --resume your_resume.pdf"
        ) from exc


# ---------------------------------------------------------------------------
# profile helpers
# ---------------------------------------------------------------------------

def _bullet_index(profile: dict) -> dict[str, str]:
    """Map stable bullet ids (exp{i}-b{j}) to verbatim bullet text."""
    index: dict[str, str] = {}
    for i, entry in enumerate(profile.get("experience") or []):
        if not isinstance(entry, dict):
            continue
        for j, bullet in enumerate(entry.get("bullets") or []):
            if bullet and str(bullet).strip():
                index[f"exp{i}-b{j}"] = str(bullet).strip()
    return index


def _dated(dates: str) -> str:
    return f" ({dates})" if dates else ""


def _past_roles(experience: list[dict]) -> list[tuple[int, dict]]:
    """Oldest-first (index, entry) pairs for the past segment.

    The current role (experience[0]) is excluded when earlier roles exist,
    so the past does not restate the present; a single-role profile keeps
    its one role as the past.
    """
    if len(experience) > 1:
        pool = [(i, e) for i, e in enumerate(experience) if i != 0]
    else:
        pool = list(enumerate(experience))
    pool.sort(key=lambda t: t[0], reverse=True)
    return pool[:2]


def _education_sentence(edu: dict) -> str:
    school = (edu.get("school") or "").strip()
    degree = (edu.get("degree") or "").strip()
    dates = (edu.get("dates") or "").strip()
    if degree and school:
        s = f"I earned my {degree} from {school}"
    elif school:
        s = f"I went to {school}"
    elif degree:
        s = f"I studied {degree}"
    else:
        return ""
    return s + _dated(dates) + "."


def _early_sentence(entry: dict, first: bool = True) -> str:
    title = (entry.get("title") or "").strip()
    company = (entry.get("company") or "").strip()
    dates = (entry.get("dates") or "").strip()
    if first:
        if title and company:
            return f"I started out as {title} at {company}{_dated(dates)}."
        if title:
            return f"I started out as {title}{_dated(dates)}."
        if company:
            return f"I started out at {company}{_dated(dates)}."
    else:
        if title and company:
            return f"From there, I became {title} at {company}{_dated(dates)}."
        if title:
            return f"From there, I became {title}{_dated(dates)}."
        if company:
            return f"From there, I joined {company}{_dated(dates)}."
    return ""


def _current_sentence(entry: dict) -> str:
    title = (entry.get("title") or "").strip()
    company = (entry.get("company") or "").strip()
    dates = (entry.get("dates") or "").strip()
    if title and company:
        return f"Today, I'm {title} at {company}{_dated(dates)}."
    if title:
        return f"Today, I work as {title}{_dated(dates)}."
    if company:
        return f"Today, I work at {company}{_dated(dates)}."
    return ""


def _role_sentence(entry: dict) -> str:
    title = (entry.get("title") or "").strip()
    company = (entry.get("company") or "").strip()
    who = title if title else "an engineer"
    where = f" at {company}" if company else ""
    return f"My work as {who}{where} included:"


def _role_of(bid: str) -> int:
    """Role index from a bullet id like 'exp2-b0'."""
    return int(bid[3:bid.index("-b")])


def _target_text(profile: dict) -> str:
    target = profile.get("target_roles") or profile.get("targets") or profile.get("target") or ""
    if isinstance(target, (list, tuple)):
        target = ", ".join(str(t).strip() for t in target if str(t).strip())
    return str(target).strip()


# ---------------------------------------------------------------------------
# narrative arc
# ---------------------------------------------------------------------------

def build_arc(profile: dict | None = None) -> dict:
    """Build the past -> present -> future story arc from the profile.

    Returns {"past": {"text", "sources"}, "present": {...}, "future": {...}}.
    Every segment records "sources": the profile bullet ids (exp{i}-b{j})
    and education ids (edu{i}) it was built from.
    """
    prof = _get_profile(profile)
    experience = [e for e in (prof.get("experience") or []) if isinstance(e, dict)]
    education = [e for e in (prof.get("education") or []) if isinstance(e, dict)]
    skills = [s for s in (prof.get("skills") or []) if s]

    # ---- past: earliest roles + education --------------------------------
    past_sources: list[str] = []
    past_parts: list[str] = []
    for k, edu in enumerate(education):
        s = _education_sentence(edu)
        if s:
            past_parts.append(s)
            past_sources.append(f"edu{k}")
    past_entries = _past_roles(experience)
    for k, (_, entry) in enumerate(past_entries):
        s = _early_sentence(entry, first=(k == 0))
        if s:
            past_parts.append(s)
    if past_entries:
        oldest_idx = past_entries[0][0]
        oldest_bullets = experience[oldest_idx].get("bullets") or []
        intros = ["One early example of my work", "Another early example"]
        for j, bullet in enumerate(oldest_bullets[:2]):
            if bullet and str(bullet).strip():
                intro = intros[j] if j < len(intros) else "One more early example"
                past_parts.append(f'{intro}: "{str(bullet).strip()}".')
                past_sources.append(f"exp{oldest_idx}-b{j}")
    if not past_parts:
        past_parts.append("[fill in: where you started: your education or first role]")

    # ---- present: current role + top skills -------------------------------
    present_sources: list[str] = []
    present_parts: list[str] = []
    if experience:
        cur = experience[0]
        s = _current_sentence(cur)
        if s:
            present_parts.append(s)
        top = skills[:5]
        if top:
            present_parts.append(f"My core strengths are {', '.join(top)}.")
        intros = ["For example", "For instance", "As another example"]
        for j, bullet in enumerate((cur.get("bullets") or [])[:3]):
            if bullet and str(bullet).strip():
                intro = intros[j] if j < len(intros) else "One more example"
                present_parts.append(f'{intro}: "{str(bullet).strip()}".')
                present_sources.append(f"exp0-b{j}")
    else:
        present_parts.append("[fill in: your current role and what you focus on]")

    # ---- future: stated target, never invented -----------------------------
    target = _target_text(prof)
    if target:
        future_text = f"Looking ahead, I'm aiming for {target}."
    else:
        future_text = "Looking ahead, I'm headed toward [fill in: where you're headed]."

    return {
        "past": {"text": " ".join(past_parts), "sources": past_sources},
        "present": {"text": " ".join(present_parts), "sources": present_sources},
        "future": {"text": future_text, "sources": []},
    }


def save_arc(arc: dict | None = None, profile: dict | None = None) -> dict:
    """Build (if needed) and persist the arc under the "arc" key. Returns it."""
    arc = arc if arc is not None else build_arc(profile)
    state = _load_state()
    state["arc"] = arc
    _save_state(state)
    return arc


def get_arc() -> dict | None:
    """Return the stored arc, or None if none has been built yet."""
    state = _load_state()
    arc = state.get("arc")
    return arc if isinstance(arc, dict) else None


# ---------------------------------------------------------------------------
# pitches
# ---------------------------------------------------------------------------

def _normalize_length(length: str) -> str:
    key = (length or "").strip().lower()
    if key in _length_ALIASES:
        return _length_ALIASES[key]
    raise NarrativeError(
        f"Unknown pitch length '{length}'. Choose from: 30s, 2min, 5min."
    )


def _pad_pool(prof: dict, target: str) -> list[str]:
    exp = [e for e in (prof.get("experience") or []) if isinstance(e, dict)]
    cur = exp[0] if exp else {}
    company = (cur.get("company") or "").strip() or "a past employer"
    title = (cur.get("title") or "").strip() or "your role"
    skills = [s for s in (prof.get("skills") or []) if s]
    skill = skills[0] if skills else "strongest"
    tgt = target or "your next role"
    return [
        f"[fill in: a specific result you are proud of from your time at {company}]",
        f"[fill in: a hard problem you solved as {title}]",
        f"[fill in: what draws you toward {tgt}]",
        f"[fill in: a project that shows your {skill} skills in action]",
        "[fill in: how your work affected users or the business]",
        "[fill in: a time you influenced a decision without formal authority]",
        "[fill in: the tools or methods you reach for first, and why]",
        "[fill in: something you would do differently on a past project]",
        "[fill in: a strength your teammates would name first]",
        "[fill in: where you want your career to be in two years]",
        "[fill in: a question you would ask an interviewer about the team]",
        "[fill in: your proudest collaboration story]",
    ]


def _compose_pitch(length: str, arc: dict, prof: dict) -> dict:
    lo, hi = PITCH_LENGTHS[length]
    bullets = _bullet_index(prof)
    name = (prof.get("name") or "").strip()
    headline = (prof.get("headline") or "").strip()
    location = (prof.get("location") or "").strip()
    skills = [s for s in (prof.get("skills") or []) if s]
    experience = [e for e in (prof.get("experience") or []) if isinstance(e, dict)]
    education = [e for e in (prof.get("education") or []) if isinstance(e, dict)]
    target = _target_text(prof)

    # parts: (text, kind) where kind is core/context/quote/pad
    opening: list[tuple[str, str]] = []
    if name:
        opening.append((f"I'm {name}.", "core"))
    else:
        opening.append(("Here's a quick tour of my background so far.", "core"))
    if headline:
        art = "an" if headline[0].lower() in "aeiou" else "a"
        loc = f" based in {location}" if location else ""
        opening.append((f"I'm {art} {headline}{loc}.", "core"))
    elif skills:
        opening.append((f"I work mostly in {', '.join(skills[:3])}.", "core"))
    else:
        opening.append(("[fill in: your one-line professional headline]", "core"))

    past_ctx: list[tuple[str, str]] = []
    for edu in education:
        s = _education_sentence(edu)
        if s:
            past_ctx.append((s, "context"))
    if length != "5min":
        # 5min covers each role in its own block below; shorter pitches summarize
        past_entries = _past_roles(experience)
        if length == "30s":
            past_entries = past_entries[:1]
        for k, (_, entry) in enumerate(past_entries):
            s = _early_sentence(entry, first=(k == 0))
            if s:
                past_ctx.append((s, "context"))
    if not past_ctx:
        past_ctx.append(("[fill in: where you started: your education or first role]", "core"))

    present_ctx: list[tuple[str, str]] = []
    if experience:
        s = _current_sentence(experience[0])
        if s:
            present_ctx.append((s, "context"))
        if skills and length != "30s":
            # 30s stays tight: the current-role sentence carries it
            present_ctx.append((f"My core strengths are {', '.join(skills[:5])}.", "context"))
    else:
        present_ctx.append(("[fill in: your current role and what you focus on]", "core"))

    future = [(arc.get("future", {}).get("text") or _future_fallback(target), "core")]

    closings = {
        "30s": "That's me in thirty seconds.",
        "2min": "That's the short version of my story, and I'm happy to go deeper on any of it.",
        "5min": "That's the fuller arc of my career so far. I'm happy to dig into any chapter of it, or talk about where it's headed next.",
    }
    closing = [(closings[length], "core")]

    # ---- quote selection (verbatim, from arc sources first) -----------------
    present_ids = [s for s in (arc.get("present") or {}).get("sources", []) if s in bullets]
    past_ids = [s for s in (arc.get("past") or {}).get("sources", [])
                if s in bullets and s.startswith("exp")]
    past_id_set = set(past_ids)
    if length == "30s":
        present_ids = sorted(present_ids, key=lambda i: len(bullets[i].split()))
        past_ids = sorted(past_ids, key=lambda i: len(bullets[i].split()))

    def words(parts: list[tuple[str, str]]) -> int:
        return sum(len(t.split()) for t, _ in parts)

    quoted: list[str] = []  # bullet ids, in quote order
    past_quotes: list[tuple[str, str]] = []
    present_quotes: list[tuple[str, str]] = []
    blocks: list[tuple[str, str]] = []  # 5min only: per-role sections

    def _skeleton() -> list[tuple[str, str]]:
        return opening + past_ctx + past_quotes + present_ctx + present_quotes + blocks + future + closing

    def _quote_text(bid: str, n: int) -> str:
        return f'{_QUOTE_INTROS[n % len(_QUOTE_INTROS)]}: "{bullets[bid]}".'

    if length == "5min":
        # per-role blocks, newest role first: role sentence, then its quotes
        n = 0
        for i, entry in enumerate(experience):
            role_ids = [bid for bid in bullets if _role_of(bid) == i]
            if not role_ids:
                continue
            first_q = _quote_text(role_ids[0], n)
            if words(_skeleton()) + len(first_q.split()) > hi - 4:
                break  # words only grow from here; later roles cannot fit either
            blocks.append((_role_sentence(entry), "context"))
            for bid in role_ids:
                q = _quote_text(bid, n)
                if words(_skeleton()) + len(q.split()) > hi - 4:
                    break
                blocks.append((q, "quote"))
                blocks.append(
                    ("[fill in: the story behind this result: what was hard, what you tried, what landed]", "pad")
                )
                quoted.append(bid)
                n += 1
    else:
        candidates = present_ids + past_ids
        caps = {"30s": 2, "2min": 6}
        fixed = _skeleton()
        budget = hi - words(fixed) - 8
        n = 0
        for bid in candidates:
            if n >= caps[length]:
                break
            q = _quote_text(bid, n)
            if quoted and words(fixed + past_quotes + present_quotes) + len(q.split()) > budget:
                break
            if words(fixed + past_quotes + present_quotes) + len(q.split()) > hi - 4:
                break
            entry = (q, "quote")
            if bid in past_id_set:
                past_quotes.append(entry)
            else:
                present_quotes.append(entry)
            quoted.append(bid)
            n += 1

        # Guarantee: when the profile has bullets, the pitch quotes at least one.
        # Make room by displacing trailing context sentences (never the skeleton:
        # opening, future, closing, and at least one context sentence survive).
        if candidates and not quoted:
            shortest = min(candidates, key=lambda b: len(bullets[b].split()))
            q = _quote_text(shortest, 0)
            qw = len(q.split())
            while words(_skeleton()) + qw > hi - 4:
                removed = False
                for sec in (past_ctx, present_ctx):
                    ctx_here = [i for i, (_, k) in enumerate(sec) if k == "context"]
                    # keep at least one context sentence in a section that has any
                    if len(ctx_here) > 1 or (len(ctx_here) == 1 and len(sec) > 1):
                        del sec[ctx_here[-1]]
                        removed = True
                        break
                if not removed:
                    break
            if words(_skeleton()) + qw <= hi - 4:
                entry = (q, "quote")
                if shortest in past_id_set:
                    past_quotes.append(entry)
                else:
                    present_quotes.append(entry)
                quoted.append(shortest)

    # ---- assemble, pad up to the minimum, trim to the maximum --------------
    parts = opening + past_ctx + past_quotes + present_ctx + present_quotes + blocks + future
    pool = _pad_pool(prof, target)
    pi = 0
    while words(parts) + words(closing) < lo:
        parts.append((pool[pi % len(pool)], "pad"))
        pi += 1
    parts = parts + closing
    while words(parts) > hi:
        for i in range(len(parts) - 1, -1, -1):
            if parts[i][1] in ("pad", "quote"):
                del parts[i]
                break
        else:
            break

    text = " ".join(t for t, _ in parts)
    return {
        "length": length,
        "wpm": _WPM,
        "word_range": [lo, hi],
        "word_count": words(parts),
        "sources": quoted,
        "text": text,
    }


def _future_fallback(target: str) -> str:
    if target:
        return f"Looking ahead, I'm aiming for {target}."
    return "Looking ahead, I'm headed toward [fill in: where you're headed]."


def generate_pitch(length: str = "2min", profile: dict | None = None,
                   regenerate: bool = False) -> dict:
    """Build (or return the saved draft of) a pitch of the given length.

    Drafts are saved under the "pitches" key in narrative.json. A saved
    draft is returned as-is unless ``regenerate`` is True, which rebuilds
    it deterministically from the current profile.
    """
    length = _normalize_length(length)
    state = _load_state()
    pitches = state.get("pitches")
    if not isinstance(pitches, dict):
        pitches = {}
    if not regenerate and isinstance(pitches.get(length), dict):
        return pitches[length]
    prof = _get_profile(profile)
    arc = build_arc(prof)
    pitch = _compose_pitch(length, arc, prof)
    pitches[length] = pitch
    state["pitches"] = pitches
    _save_state(state)
    return pitch


def get_pitch(length: str = "2min") -> dict | None:
    """Return the saved draft for a pitch length, or None if none exists."""
    length = _normalize_length(length)
    pitches = _load_state().get("pitches")
    if isinstance(pitches, dict) and isinstance(pitches.get(length), dict):
        return pitches[length]
    return None

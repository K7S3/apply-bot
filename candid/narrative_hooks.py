"""Career story builder: hook library and role transition lines.

Helps a user answer "tell me about yourself" with evidence from their own
profile instead of invented fluff.

Hook library: ``suggest_hooks(n=5)`` ranks every achievement bullet in the
profile with a deterministic impact scorer (points for numeric tokens,
scope words, seniority signals; ties break in profile order) and turns the
top picks into memorable opening lines. Every line quotes the source
bullet verbatim (word-boundary truncated), so no metric can be invented.

Transition lines: ``build_transitions()`` walks the profile's work history
chronologically and generates a bridge sentence between each consecutive
role pair. The motivation is always the literal placeholder
"[fill in: why you made the move]" because profiles carry no motivation
data; the user edits it with ``update_transition``.

Stored as JSON at candid_data/narrative.json (git-ignored), under the
top-level keys "hooks" and "transitions" only. Sibling keys from other
features are preserved on every write.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from candid import config as C
from candid import profile as P
from candid.profile import OnboardError

MAX_QUOTE_WORDS = 40
MOTIVATION_PLACEHOLDER = "[fill in: why you made the move]"


class NarrativeError(Exception):
    """Raised for invalid narrative operations or a missing profile."""


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------

def _narrative_path() -> Path:
    return C.DATA_DIR / "narrative.json"


def _load_state() -> dict:
    p = _narrative_path()
    if not p.exists():
        return {"hooks": [], "transitions": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NarrativeError(f"Narrative file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise NarrativeError(f"Narrative file {p} should contain a JSON object.")
    data.setdefault("hooks", [])
    data.setdefault("transitions", [])
    return data


def _save_state(data: dict) -> None:
    """Write back the whole file, preserving keys owned by other features."""
    p = _narrative_path()
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_profile() -> dict:
    try:
        return P.load_profile()
    except OnboardError as exc:
        raise NarrativeError(
            "No profile found. Run onboarding first:\n"
            "    candid onboard --resume your_resume.pdf"
        ) from exc


# ---------------------------------------------------------------------------
# impact scorer (deterministic, no network, no LLMs)
# ---------------------------------------------------------------------------

_NUMERIC_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|percent|x|k|m|b|million|billion|thousand)?|"
    r"\$\s?\d+(?:\.\d+)?\s*(?:k|m|b|million|billion)?",
    re.IGNORECASE,
)
_SCOPE_WORDS = (
    "led", "team", "teams", "million", "billion", "launched", "launch",
    "scaled", "scale", "drove", "grew", "revenue", "users", "customers",
    "reduced", "cut", "saved", "shipped",
)
_SENIORITY_WORDS = (
    "senior", "staff", "principal", "lead", "manager", "director",
    "vp", "architect", "head", "owner", "founding",
)


def _impact_score(bullet: str) -> tuple[int, bool, bool, bool]:
    """Score a bullet. Returns (score, has_metric, has_scope, has_seniority)."""
    text = bullet or ""
    lowered = text.lower()
    words = set(re.findall(r"[a-z]+", lowered))

    numeric_hits = len(_NUMERIC_RE.findall(text))
    scope_hits = sum(1 for w in _SCOPE_WORDS if w in words)
    seniority_hits = sum(1 for w in _SENIORITY_WORDS if w in words)

    score = numeric_hits * 3 + scope_hits * 2 + seniority_hits
    return score, numeric_hits > 0, scope_hits > 0, seniority_hits > 0


def _truncate_words(text: str, max_words: int = MAX_QUOTE_WORDS) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "..."


def _hook_template(has_metric: bool, has_scope: bool, has_seniority: bool) -> str:
    if has_metric:
        return "A result that captures what I bring: "
    if has_scope:
        return "The scale of my work is best shown by: "
    if has_seniority:
        return "Where my leadership shows most clearly: "
    return "A story I like to tell about my work: "


def _hook_id(bullet: str) -> str:
    return "hook-" + hashlib.md5(bullet.encode("utf-8")).hexdigest()[:10]


def _iter_bullets(prof: dict):
    """Yield (entry_index, bullet_index, role, bullet) in profile order."""
    for ei, role in enumerate(prof.get("experience", []) or []):
        role = role if isinstance(role, dict) else {}
        for bi, bullet in enumerate(role.get("bullets", []) or []):
            if bullet and isinstance(bullet, str) and bullet.strip():
                yield ei, bi, role, bullet


def suggest_hooks(n: int = 5) -> list[dict]:
    """Suggest the n strongest achievement-based hook lines.

    Returns the hook records in ranked order. Previously saved hooks keep
    their ``saved`` flag across re-suggestions.
    """
    if n is None or not isinstance(n, int) or n <= 0:
        raise NarrativeError("n must be a positive integer.")
    prof = _load_profile()
    state = _load_state()
    saved_ids = {h.get("id") for h in state.get("hooks", []) if h.get("saved")}

    ranked = []
    for ei, bi, role, bullet in _iter_bullets(prof):
        score, has_metric, has_scope, has_seniority = _impact_score(bullet)
        ranked.append((score, ei, bi, role, bullet,
                       (has_metric, has_scope, has_seniority)))
    # score desc, ties break in profile order (entry then bullet index)
    ranked.sort(key=lambda r: (-r[0], r[1], r[2]))

    hooks = []
    for score, _ei, _bi, role, bullet, signals in ranked[:n]:
        hid = _hook_id(bullet)
        template = _hook_template(*signals)
        quote = _truncate_words(bullet.strip())
        title = (role.get("title") or "").strip()
        company = (role.get("company") or "").strip()
        source = f"{title} at {company}".strip()
        source = source if source != "at" else ""
        hooks.append({
            "id": hid,
            "text": template + '"' + quote + '"',
            "source": source,
            "bullet": bullet,
            "saved": hid in saved_ids,
        })
    return hooks


def _get_hook_or_raise(hook_id: str) -> tuple[dict, dict]:
    state = _load_state()
    for h in state.get("hooks", []):
        if h.get("id") == hook_id:
            return state, h
    raise NarrativeError(f"Unknown hook id '{hook_id}'. Run suggest_hooks first.")


def save_hook(hook_id: str) -> dict:
    """Save a suggested hook to the library. Returns the hook record."""
    if not hook_id:
        raise NarrativeError("hook_id is required.")
    state, hook = _get_hook_or_raise(hook_id)
    hook["saved"] = True
    _save_state(state)
    return hook


def delete_hook(hook_id: str) -> dict:
    """Delete a hook from the library. Returns the deleted record."""
    if not hook_id:
        raise NarrativeError("hook_id is required.")
    state, hook = _get_hook_or_raise(hook_id)
    state["hooks"] = [h for h in state["hooks"] if h.get("id") != hook_id]
    _save_state(state)
    return hook


def list_hooks() -> list[dict]:
    """List saved hooks only."""
    return [h for h in _load_state().get("hooks", []) if h.get("saved")]


def store_suggestions(hooks: list[dict]) -> list[dict]:
    """Persist suggested hooks so they can be saved/deleted later.

    Merges with existing records: saved flags are preserved.
    """
    if hooks is None:
        raise NarrativeError("hooks is required.")
    state = _load_state()
    existing = {h.get("id"): h for h in state.get("hooks", [])}
    merged = []
    for h in hooks:
        if not isinstance(h, dict) or not h.get("id"):
            raise NarrativeError("Each hook must be a record with an id.")
        old = existing.get(h["id"])
        rec = dict(h)
        if old is not None and old.get("saved"):
            rec["saved"] = True
        merged.append(rec)
    state["hooks"] = merged
    _save_state(state)
    return merged


# ---------------------------------------------------------------------------
# role transition lines
# ---------------------------------------------------------------------------

_START_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _start_year(role: dict) -> int | None:
    m = _START_YEAR_RE.search(str(role.get("dates") or ""))
    return int(m.group(0)) if m else None


def _chronological_roles(prof: dict) -> list[dict]:
    """Oldest first. Profile lists most-recent-first, so reverse it; then
    stable-sort the dated roles by start year, keeping dateless roles where
    they were listed."""
    roles = [r for r in (prof.get("experience", []) or []) if isinstance(r, dict)]
    roles = list(reversed(roles))
    dated = [(i, r, y) for i, r in enumerate(roles) if (y := _start_year(r)) is not None]
    dated.sort(key=lambda t: (t[2], t[0]))
    out = list(roles)
    dated_positions = [i for i, _r, _y in dated]
    dated_roles = [r for _i, r, _y in dated]
    for pos, role in zip(dated_positions, dated_roles):
        out[pos] = role
    return out


def _role_key(role: dict) -> dict:
    return {"title": role.get("title") or "", "company": role.get("company") or ""}


def _transition_text(from_role: dict, to_role: dict) -> str:
    frm = _role_key(from_role)
    to = _role_key(to_role)
    return (
        f"After {frm['title']} at {frm['company']}, "
        f"I moved to {to['company']} as {to['title']}. "
        f"{MOTIVATION_PLACEHOLDER}"
    )


def build_transitions() -> list[dict]:
    """Build a bridge sentence between each consecutive role pair.

    Records: {from_role, to_role, text, edited}. Rebuilds preserve
    user-edited texts, matched by title+company pair.
    """
    prof = _load_profile()
    state = _load_state()
    old_texts = {}
    for t in state.get("transitions", []):
        if t.get("edited") and isinstance(t.get("from_role"), dict) and isinstance(t.get("to_role"), dict):
            key = (
                t["from_role"].get("title"), t["from_role"].get("company"),
                t["to_role"].get("title"), t["to_role"].get("company"),
            )
            old_texts[key] = t.get("text")

    roles = _chronological_roles(prof)
    transitions = []
    for prev, nxt in zip(roles, roles[1:]):
        frm = _role_key(prev)
        to = _role_key(nxt)
        key = (frm["title"], frm["company"], to["title"], to["company"])
        if key in old_texts:
            transitions.append({
                "from_role": frm, "to_role": to,
                "text": old_texts[key], "edited": True,
            })
        else:
            transitions.append({
                "from_role": frm, "to_role": to,
                "text": _transition_text(prev, nxt), "edited": False,
            })
    state["transitions"] = transitions
    _save_state(state)
    return transitions


def list_transitions() -> list[dict]:
    """List stored transition lines (chronological order)."""
    return _load_state().get("transitions", [])


def update_transition(index: int, text: str) -> dict:
    """Replace a transition's text with the user's own words.

    Marks the record edited so rebuilds preserve it.
    """
    if not isinstance(index, int) or isinstance(index, bool):
        raise NarrativeError("index must be an integer.")
    if not text or not str(text).strip():
        raise NarrativeError("text must not be empty.")
    state = _load_state()
    transitions = state.get("transitions", [])
    if not 0 <= index < len(transitions):
        raise NarrativeError(
            f"Transition index {index} is out of range "
            f"(0 to {len(transitions) - 1})."
        )
    transitions[index]["text"] = text.strip()
    transitions[index]["edited"] = True
    _save_state(state)
    return transitions[index]

"""Failure/weakness story scaffolds + narrative one-pager export for interview prep.

Two features, deterministic and offline:

1. Setback story scaffolds: ``build_setback_stories()`` builds
   "tell me about a failure / mistake / weakness" scaffolds from real
   source material (candid's debrief store and rejections records when
   they exist), falling back to generic [TEMPLATE] writing aids when
   there is no data. Never invents failures: every data-driven scaffold
   cites its source, and templates are clearly labeled as writing aids,
   not claims.

2. Narrative one-pager: ``export_onepager()`` / ``write_onepager()``
   assemble an interview-prep one-pager (header, Career Arc, 2-Minute
   Pitch, Hooks, Transitions, Why Us) with per-section word counts and
   speaking-time estimates at 140 wpm.

State lives in ``DATA_DIR/"narrative.json"``. This module owns only the
"setbacks" and "exports" top-level keys; every write loads the whole
file, updates those keys, and writes back so sibling keys (e.g. "arc",
"pitches", "hooks", "transitions", "why_us") are preserved.

Missing profile: one-pager raises a friendly NarrativeError; setback
scaffolds still build from whatever data exists.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from candid import config as C
from candid import profile as P


class NarrativeError(Exception):
    """Raised for invalid narrative/setback operations."""


# ---------------------------------------------------------------------------
# state helpers (paths computed lazily so tests can rebind C.DATA_DIR)
# ---------------------------------------------------------------------------

NARRATIVE_FILE = "narrative.json"
WPM = 140
FILL_IN = "[fill in: your story]"


def _narrative_path() -> Path:
    return C.DATA_DIR / NARRATIVE_FILE


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


def _words(text: str) -> int:
    return len(text.split())


def _seconds(words: int) -> int:
    return max(1, round(words * 60 / WPM)) if words else 0


# ---------------------------------------------------------------------------
# source probing: debriefs + rejections (fully defensive)
# ---------------------------------------------------------------------------

def _as_list(raw) -> list[dict]:
    """Normalize a store payload into a list of dict entries."""
    if isinstance(raw, dict):
        for key in ("entries", "items", "debriefs", "rejections", "records"):
            if isinstance(raw.get(key), list):
                return [e for e in raw[key] if isinstance(e, dict)]
        return []
    if isinstance(raw, list):
        return [e for e in raw if isinstance(e, dict)]
    return []


def _try_module_entries(module_name: str, func_names: list[str]) -> list[dict]:
    """Best-effort read of entries from an optional candid module."""
    try:
        mod = __import__(f"candid.{module_name}", fromlist=["*"])
    except Exception:
        return []
    for name in func_names:
        fn = getattr(mod, name, None)
        if not callable(fn):
            continue
        try:
            return _as_list(fn())
        except Exception:
            continue
    return []


def _read_plain_json(*names: str) -> list[dict]:
    for name in names:
        p = C.DATA_DIR / name
        if not p.exists():
            continue
        try:
            return _as_list(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, ValueError):
            continue
    return []


def _load_debrief_entries() -> list[dict]:
    entries = _try_module_entries(
        "debrief", ["list_debriefs", "load_debriefs", "read_debriefs", "all_debriefs"]
    )
    if entries:
        return entries
    return _read_plain_json("debriefs.json", "debrief.json")


def _load_rejection_entries() -> list[dict]:
    entries = _try_module_entries(
        "rejections", ["list_rejections", "load_rejections", "all_rejections"]
    )
    if entries:
        return entries
    return _read_plain_json("rejections.json", "rejection.json")


# Debrief field -> scaffold kind.
_SIGNAL_FIELDS: dict[str, str] = {
    "what_went_wrong": "failure",
    "went_wrong": "failure",
    "failure": "failure",
    "mistake": "mistake",
    "mistakes": "mistake",
    "weakness": "weakness",
    "weaknesses": "weakness",
    "area_to_improve": "weakness",
    "improvement": "weakness",
}

_PROMPTS: dict[str, str] = {
    "failure": "Tell me about a time you failed, or a project that didn't go as planned.",
    "mistake": "Tell me about a mistake you made at work and how you handled it.",
    "weakness": "What would you say is your greatest weakness, or an area you are actively improving?",
}


def _entry_label(entry: dict, prefix: str) -> str:
    bits = [str(entry.get(k)) for k in ("company", "role") if entry.get(k)]
    when = entry.get("date") or entry.get("when") or ""
    ident = entry.get("id", "")
    label = f"{prefix} {ident}".strip() if ident != "" else prefix
    if bits:
        label += f" ({' - '.join(bits)}"
        label += f", {when})" if when else ")"
    return label


def _scaffold(scaffold_id: str, kind: str, prompt: str, citation: str,
              excerpt: str = "", is_template: bool = False) -> dict:
    frame = {
        "situation": FILL_IN,
        "what_went_wrong": FILL_IN,
        "lesson": FILL_IN,
        "what_changed": FILL_IN,
    }
    sc = {
        "id": scaffold_id,
        "kind": kind,
        "prompt": prompt,
        "source_citation": citation,
        "is_template": is_template,
        "frame": frame,
        "user_text": "",
    }
    if excerpt:
        sc["source_excerpt"] = excerpt
    if is_template:
        sc["note"] = (
            "[TEMPLATE] Generic writing aid. Fill in your own real story; "
            "this is not a claim about your history."
        )
    return sc


def _generic_templates() -> list[dict]:
    return [
        _scaffold("setback-failure-template", "failure", _PROMPTS["failure"],
                  "[TEMPLATE]", is_template=True),
        _scaffold("setback-mistake-template", "mistake", _PROMPTS["mistake"],
                  "[TEMPLATE]", is_template=True),
        _scaffold("setback-weakness-template", "weakness", _PROMPTS["weakness"],
                  "[TEMPLATE]", is_template=True),
    ]


def _scaffold_from_debrief(entry: dict, index: int) -> list[dict]:
    out = []
    for field, kind in _SIGNAL_FIELDS.items():
        text = entry.get(field)
        if not isinstance(text, str) or not text.strip():
            continue
        citation = f"{_entry_label(entry, 'debrief')}: {field}"
        out.append(_scaffold(
            f"setback-{kind}-{index}-{field.replace('_', '-')}",
            kind, _PROMPTS[kind], citation, excerpt=text.strip(),
        ))
    return out


def _scaffold_from_rejection(entry: dict, index: int) -> list[dict]:
    # A rejection is real source material only when it carries feedback;
    # never invent a failure story from a bare rejection record.
    text = entry.get("reason") or entry.get("feedback") or ""
    if not isinstance(text, str) or not text.strip():
        return []
    citation = f"{_entry_label(entry, 'rejection')}: {('reason' if entry.get('reason') else 'feedback')}"
    prompt = (
        "Tell me about a time you faced a professional setback (for example, "
        "an interview process that didn't work out). What did you take away?"
    )
    return [_scaffold(f"setback-failure-rej-{index}", "failure", prompt,
                      citation, excerpt=text.strip())]


def build_setback_stories() -> list[dict]:
    """Build failure/mistake/weakness story scaffolds.

    Sources are probed defensively: the optional ``candid.debrief`` and
    ``candid.rejections`` modules (try/except import + getattr probing),
    falling back to plain JSON at ``DATA_DIR/debriefs.json`` and
    ``DATA_DIR/rejections.json``. No data -> generic [TEMPLATE] prompts.

    Saved user text from previous builds is preserved by scaffold id.
    The result is stored under the "setbacks" key of narrative.json.
    """
    state = _load_state()
    prev = {s.get("id"): s for s in state.get("setbacks", {}).get("stories", [])
            if isinstance(s, dict)}

    scaffolds: list[dict] = []
    for i, entry in enumerate(_load_debrief_entries(), start=1):
        scaffolds.extend(_scaffold_from_debrief(entry, i))
    for i, entry in enumerate(_load_rejection_entries(), start=1):
        scaffolds.extend(_scaffold_from_rejection(entry, i))
    scaffolds.extend(_generic_templates())

    for sc in scaffolds:
        old = prev.get(sc["id"])
        if old and old.get("user_text"):
            sc["user_text"] = old["user_text"]

    state["setbacks"] = {"stories": scaffolds, "updated_at": _now_iso()}
    _save_state(state)
    return scaffolds


def list_setback_stories() -> list[dict]:
    """Return the saved scaffold list (builds it first if never built)."""
    state = _load_state()
    stories = state.get("setbacks", {}).get("stories")
    if not stories:
        return build_setback_stories()
    return stories


def update_setback_story(story_id: str, text: str) -> dict:
    """Save the user's written version of a scaffold. Returns the scaffold."""
    stories = list_setback_stories()
    for sc in stories:
        if sc.get("id") == story_id:
            sc["user_text"] = text
            state = _load_state()
            state.setdefault("setbacks", {})["stories"] = stories
            state["setbacks"]["updated_at"] = _now_iso()
            _save_state(state)
            return sc
    raise NarrativeError(f"No setback story with id '{story_id}'. "
                        "Run build_setback_stories() to see valid ids.")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# narrative one-pager
# ---------------------------------------------------------------------------

def _load_profile() -> dict:
    """Load the user profile; raise a friendly NarrativeError if missing."""
    try:
        return P.load_profile(path=C.DATA_DIR / "profile.json")
    except Exception as exc:
        raise NarrativeError(
            "No profile found. The one-pager needs your profile header.\n"
            "Run onboarding first:\n"
            "    python -m candid onboard --resume your_resume.pdf\n"
            f"({exc})"
        ) from exc


def _resolve_narrative(narrative: dict | None) -> dict:
    """Optional arg -> narrative.json keys -> {}; all defensive .get()."""
    if narrative is not None:
        if not isinstance(narrative, dict):
            raise NarrativeError("narrative must be a dict of narrative sections.")
        return narrative
    state = _load_state()
    return {
        "arc": state.get("arc"),
        "pitches": state.get("pitches"),
        "hooks": state.get("hooks"),
        "transitions": state.get("transitions"),
        "why_us": state.get("why_us"),
    }


def _as_lines(value) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _normalize_pitch(pitches) -> tuple[str, bool]:
    """Return (text, approved) for the 2-minute pitch. Defensive."""
    if isinstance(pitches, str):
        return pitches.strip(), False
    if isinstance(pitches, list):
        for item in pitches:
            if isinstance(item, dict) and item.get("kind") in (None, "2min", "two_min", "pitch"):
                return _normalize_pitch(item)
        return "", False
    if isinstance(pitches, dict):
        if "2min" in pitches:
            return _normalize_pitch(pitches["2min"])
        for key in ("two_min", "pitch", "text"):
            if key in pitches:
                return _normalize_pitch(pitches[key])
        return "", False
    if pitches is None:
        return "", False
    return str(pitches).strip(), False


def _pitch_text_approved(pitch: dict) -> bool:
    return bool(pitch.get("approved") or pitch.get("is_approved")) if isinstance(pitch, dict) else False


def _pitch_section(narrative: dict, profile: dict) -> tuple[str, bool]:
    """Return (pitch text, is_draft)."""
    pitches = narrative.get("pitches")
    text, _ = _normalize_pitch(pitches)
    approved = False
    if isinstance(pitches, dict):
        approved = _pitch_text_approved(pitches.get("2min") or pitches)
    elif isinstance(pitches, list):
        for item in pitches:
            if isinstance(item, dict) and item.get("text") == text:
                approved = _pitch_text_approved(item)
                break
    if not text:
        text = (
            "[TEMPLATE] Draft your 2-minute pitch here: "
            f"{profile.get('name') or '[your name]'}, "
            f"{profile.get('headline') or '[your headline]'}. "
            "Cover where you started, what you do best now, and what you want next."
        )
        return text, True
    return text, not approved


def _arc_section(narrative: dict, profile: dict) -> str:
    arc = narrative.get("arc")
    if isinstance(arc, str) and arc.strip():
        return arc.strip()
    if isinstance(arc, dict) and arc.get("text"):
        return str(arc["text"]).strip()
    # Worker A shape: {"past": {"text", "sources"}, "present": {...}, "future": {...}}
    if isinstance(arc, dict) and any(
        isinstance(arc.get(seg), dict) and arc[seg].get("text")
        for seg in ("past", "present", "future")
    ):
        parts = []
        for seg in ("past", "present", "future"):
            text = arc.get(seg, {}).get("text", "")
            if text:
                parts.append(text.strip())
        if parts:
            return "\n\n".join(parts)
    exp = profile.get("experience", []) or []
    if exp:
        parts = []
        for e in exp[:4]:
            title = e.get("title", "").strip()
            company = e.get("company", "").strip()
            dates = e.get("dates", "").strip()
            if title and company:
                parts.append(f"{title} at {company}" + (f" ({dates})" if dates else ""))
        thread = "; ".join(parts)
        return (
            "[TEMPLATE] Your career arc in 3-4 sentences: how you got into "
            f"this field, and the thread connecting {thread}. "
            "End with where you want to go next."
        )
    return (
        "[TEMPLATE] Your career arc in 3-4 sentences: how you got into this "
        "field, the thread connecting your roles, and where you want to go next."
    )


def _hooks_section(narrative: dict) -> str:
    hooks = _as_lines(narrative.get("hooks"))
    if hooks:
        return "\n".join(f"- {h}" for h in hooks)
    return (
        "[TEMPLATE] Add 2-3 hooks: memorable results or stories that make "
        "an interviewer want to ask follow-ups (e.g. shipped X, saved Y, grew Z)."
    )


def _transitions_section(narrative: dict) -> str:
    transitions = _as_lines(narrative.get("transitions"))
    if transitions:
        return "\n".join(f"- {t}" for t in transitions)
    return (
        "[TEMPLATE] Add a one-liner for each job change: why you moved, framed "
        "as running toward something (growth, scope, mission), not away."
    )


def _why_us_section(narrative: dict) -> str:
    why = narrative.get("why_us")
    if isinstance(why, str) and why.strip():
        return why.strip()
    lines = _as_lines(why)
    if lines:
        return "\n".join(f"- {w}" for w in lines)
    return (
        "[TEMPLATE] Why this company, specifically: connect 1-2 of their real "
        "problems to your track record. Customize per target before each interview."
    )


def _section_stats(sections: list[tuple[str, str]]) -> tuple[dict, dict]:
    words = {name: _words(body) for name, body in sections}
    secs = {name: _seconds(w) for name, w in words.items()}
    return words, secs


def _build_sections(profile: dict, narr: dict) -> tuple[list[tuple[str, str]], bool]:
    """Return ([(name, body), ...], pitch_is_draft)."""
    pitch_text, is_draft = _pitch_section(narr, profile)
    return [
        ("Career Arc", _arc_section(narr, profile)),
        ("2-Minute Pitch", pitch_text),
        ("Hooks", _hooks_section(narr)),
        ("Transitions", _transitions_section(narr)),
        ("Why Us", _why_us_section(narr)),
    ], is_draft


def export_onepager(format: str = "markdown", narrative: dict | None = None) -> str:
    """Assemble the interview-prep one-pager; return as a string.

    ``format`` is "markdown" or "text". ``narrative`` optionally overrides
    narrative.json (keys: arc/pitches/hooks/transitions/why_us, all read
    defensively). The 2-minute pitch uses approved text when present,
    otherwise shows a draft with a "DRAFT - not yet approved" banner.
    Per-section word counts and 140-wpm speaking-time estimates are
    appended for every section.
    """
    fmt = format.lower()
    if fmt not in ("markdown", "text"):
        raise NarrativeError(f"Unknown one-pager format '{format}'. Use 'markdown' or 'text'.")
    profile = _load_profile()
    narr = _resolve_narrative(narrative)

    header_lines = [
        profile.get("name") or "[TEMPLATE: your name]",
        profile.get("headline") or "[TEMPLATE: your headline]",
        profile.get("location") or "[TEMPLATE: your location]",
    ]

    sections, is_draft = _build_sections(profile, narr)
    word_counts, seconds = _section_stats(sections)
    total_words = sum(word_counts.values())
    total_seconds = sum(seconds.values())

    def stat_line(name: str) -> str:
        return f"[{word_counts[name]} words, ~{seconds[name]}s at 140 wpm]"

    out: list[str] = []
    if fmt == "markdown":
        out.append("# Interview Narrative One-Pager")
        out.append("")
        out.append(f"**{header_lines[0]}**")
        out.append(f"{header_lines[1]}")
        out.append(f"{header_lines[2]}")
        out.append("")
        for name, body in sections:
            out.append(f"## {name} {stat_line(name)}")
            out.append("")
            if name == "2-Minute Pitch" and is_draft:
                out.append("> DRAFT - not yet approved")
                out.append("")
            out.append(body)
            out.append("")
        out.append("---")
        out.append(f"Total: {total_words} words, ~{total_seconds}s "
                  f"({total_seconds // 60}m {total_seconds % 60}s) at 140 wpm")
    else:
        out.append("INTERVIEW NARRATIVE ONE-PAGER")
        out.append("=" * 32)
        out.extend(header_lines)
        out.append("")
        for name, body in sections:
            out.append(f"{name.upper()} {stat_line(name)}")
            out.append("-" * 32)
            if name == "2-Minute Pitch" and is_draft:
                out.append("DRAFT - not yet approved")
            out.append(body)
            out.append("")
        out.append(f"Total: {total_words} words, ~{total_seconds}s at 140 wpm")

    return "\n".join(out).rstrip() + "\n"


def write_onepager(path: str | Path, format: str = "markdown") -> dict:
    """Write the one-pager to ``path`` and record it under the "exports" key.

    Returns the ``last_export`` record: path, format, per-section word
    counts and seconds, totals, and timestamp.
    """
    text = export_onepager(format=format)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")

    profile = _load_profile()
    sections, _ = _build_sections(profile, _resolve_narrative(None))
    word_counts, seconds = _section_stats(sections)

    record = {
        "path": str(p),
        "format": format.lower(),
        "word_counts": word_counts,
        "seconds": seconds,
        "total_words": sum(word_counts.values()),
        "total_seconds": sum(seconds.values()),
        "created_at": _now_iso(),
    }
    state = _load_state()
    state["exports"] = {"last_export": record}
    _save_state(state)
    return record

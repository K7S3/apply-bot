"""Guided voice debrief session engine (worker A).

After an interview, run ``python -m candid debrief start --app <id>`` for a
guided voice session: the engine walks through a set of prompts
("What were you asked?", "What stumped you?", "What went well?",
"Next steps?"), adapts follow-up questions from the running transcript,
captures answers (voice via worker B's ``candid.voice_io``, with a typed
fallback), timestamps every turn, and persists the transcript to a JSON
file in the user's data dir.

Voice IO contract (owned by worker B, ``candid/voice_io.py``):
    - ``speak(text: str) -> None``       speak a prompt out loud
    - ``listen(prompt_text: str) -> str``  speak the prompt, then capture and
      transcribe the user's reply (falls back to typed input when no mic/STT
      engine is available — it never raises for audio reasons)

Both are imported lazily so this module (and its tests) work with a stub
or no voice_io at all. For tests, inject any object with ``speak``/``listen``
via ``DebriefSession(..., voice_io=stub)``; stubs may accept or omit the
``prompt_text`` argument on ``listen``. Pass ``force_typed=True`` to skip
voice entirely and use the built-in typed fallback.

Store integration (owned by worker C, ``candid/debrief.py``): the transcript
is self-contained on disk, and we *additionally* register it with the
store via ``record_debrief(app_id, company, role, transcript_path,
summary_dict)`` when that module is present. Everything optional-dep is
wrapped in try/except so the session never breaks if another worker's
module isn't there yet.
"""

from __future__ import annotations

import inspect
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from candid import config as C

#: Where one transcript JSON file lives per debrief session.
DEBRIEFS_DIR = C.DATA_DIR / "debriefs"


class DebriefError(Exception):
    """Raised for invalid debrief operations."""


# ---------------------------------------------------------------------------
# guided prompts + adaptive follow-ups
# ---------------------------------------------------------------------------

#: Base guided prompts, asked in order. Each gets exactly one turn.
PROMPTS: list[dict] = [
    {
        "id": "walkthrough",
        "text": ("Walk me through the interview from the start. "
                 "What format was it — phone screen, panel, coding, onsite — "
                 "and who did you speak with?"),
    },
    {
        "id": "asked",
        "text": "What were you asked? List the main questions or topics they covered.",
    },
    {
        "id": "stumped",
        "text": "What stumped you, if anything? Where did you get stuck or feel unsure?",
    },
    {
        "id": "went_well",
        "text": "What went well? What are you most proud of in this one?",
    },
    {
        "id": "next_steps",
        "text": "What are the next steps — theirs and yours?",
    },
    {
        "id": "takeaways",
        "text": "Anything else you want to remember for the next round, or for next time?",
    },
]

#: (prompt_id, keyword regexes, follow-up) — adaptive follow-ups are chosen
#: from the running transcript: if the answer mentions being stumped, we ask
#: what specifically; if it mentions something going well, we ask what made it
#: work, and so on. At most one follow-up is inserted per turn.
_FOLLOW_UPS: list[tuple[str, list[str], str]] = [
    ("asked", [r"\bstump", r"\bstuck", r"\bdidn'?t know", r"\bno idea",
               r"\bcouldn'?t", r"\blank"],
     "Which question tripped you up the most, and what would you say now if you could redo it?"),
    ("asked", [r"\bnailed", r"\beasy", r"\bsmooth", r"\bconfident", r"\bkilled it"],
     "What made that one easy — was it preparation, or just a strong topic for you?"),
    ("stumped", [r"\bstump", r"\bstuck", r"\bdidn'?t know", r"\bno idea",
                 r"\bcouldn'?t", r"\bhard", r"\btough", r"\bdifficult", r"\bblank"],
     "What specifically about it got you — the question itself, the follow-ups, or the format?"),
    ("went_well", [r"\bwell\b", r"\bnailed", r"\bgreat", r"\bconfident", r"\bsmooth",
                   r"\beasy", r"\bstrong", r"\bproud"],
     "What made that go well — and how do you repeat it next time?"),
    ("next_steps", [r"\bfollow", r"\bemail", r"\bthank", r"\bsecond round",
                    r"\bonsite", r"\brecruiter", r"\bget back"],
     "What's your concrete plan — what exactly will you send or do, and when?"),
    ("takeaways", [r"\bprepare", r"\bstudy", r"\bpractice", r"\blearn", r"\breview"],
     "How will you prep that — what specifically, and by when?"),
]


def _find_follow_up(prompt_id: str, answer: str) -> str | None:
    """Pick an adaptive follow-up for an answer, or None.

    The first rule that matches (in rule order) wins; keyword regexes are
    case-insensitive.
    """
    for pid, patterns, follow_up in _FOLLOW_UPS:
        if pid != prompt_id:
            continue
        if any(re.search(pat, answer, re.IGNORECASE) for pat in patterns):
            return follow_up
    return None


# ---------------------------------------------------------------------------
# voice IO (lazy) and typed fallback
# ---------------------------------------------------------------------------


def load_voice_io():
    """Import worker B's ``candid.voice_io`` lazily; return None if absent."""
    try:
        from candid import voice_io  # noqa: F401
    except ImportError:
        return None
    return voice_io


class VoiceIOError(DebriefError):
    """Voice input/output failed (captured so the session can fall back)."""


def _listen_accepts_prompt(listen_fn) -> bool:
    """True when ``listen`` takes a prompt argument (worker B's real API)."""
    try:
        params = inspect.signature(listen_fn).parameters
    except (TypeError, ValueError):
        return False
    for p in params.values():
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                      inspect.Parameter.POSITIONAL_ONLY):
            return True
        if p.kind == inspect.Parameter.VAR_POSITIONAL:
            return True
    return False


class DebriefSession:
    """One guided debrief session.

    ``start_session(app_id, company, role)`` is the entry point; call
    ``run()`` to drive the interactive loop. ``voice_io`` may be injected
    (tests/stubs); otherwise it's loaded lazily, with a typed fallback.
    """

    def __init__(self, app_id: int | None, company: str, role: str,
                 *, voice_io=None, force_typed: bool = False,
                 output: Callable[[str], None] = print,
                 input_fn: Callable[[str], str] = input):
        self.app_id = app_id
        self.company = company or ""
        self.role = role or ""
        self.turns: list[dict] = []
        self._voice_io = voice_io
        self.force_typed = force_typed
        self._io_tried = False
        self._output = output
        self._input_fn = input_fn
        self.started_at: str = ""
        self.ended_at: str = ""
        self.debrief_id: str = ""
        self.transcript_path: Path | None = None

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def start_session(cls, app_id: int | None, company: str, role: str,
                      **kwargs) -> "DebriefSession":
        """Begin a new session. ``run()`` drives the interactive loop."""
        session = cls(app_id, company, role, **kwargs)
        session.started_at = datetime.now(timezone.utc).isoformat()
        session.debrief_id = session._make_id()
        return session

    def _make_id(self) -> str:
        return "deb-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    # -- voice IO ------------------------------------------------------------

    def _io(self):
        """Resolve the voice backend once; None means typed fallback."""
        if self.force_typed:
            return None
        if not self._io_tried:
            self._io_tried = True
            if self._voice_io is None:
                self._voice_io = load_voice_io()
        return self._voice_io

    def _disable_voice(self):
        """Permanently drop to typed mode for the rest of this session."""
        self._voice_io = None
        self._io_tried = True

    def ask(self, prompt: str) -> str:
        """Speak/display the prompt and capture the answer (voice, typed fallback).

        Returns ``"DONE"`` when the user ends the session early
        (voice and typed paths both normalize to it).
        """
        self._output(f"\n🗣️  {prompt}")
        io = self._io()
        if io is not None:
            try:
                if _listen_accepts_prompt(io.listen):
                    answer = io.listen(prompt) or ""
                else:
                    io.speak(prompt)
                    answer = io.listen() or ""
            except Exception as exc:
                raise VoiceIOError(str(exc)) from exc
        else:
            self._output("(typed mode — speak aloud or type; enter a blank line to finish, "
                         "'done' to end the session)")
            lines: list[str] = []
            while True:
                try:
                    line = self._input_fn("> ")
                except EOFError:
                    break
                if line.strip() == "" and lines:
                    break
                if line.strip().lower() in ("done", "quit", "exit", "stop"):
                    return "DONE"
                lines.append(line)
                if line.strip() == "":
                    break
            answer = "\n".join(lines).strip()
        if answer.strip().lower() in ("done", "quit", "exit", "stop"):
            return "DONE"
        return answer.strip()

    # -- the guided loop -------------------------------------------------------

    def run(self) -> dict:
        """Drive the guided loop; returns the finished session record dict."""
        company_line = f" — {self.company} ({self.role})" if self.company or self.role else ""
        self._output(f"=== Interview debrief{company_line} ===")
        self._output("Answer each question; type 'done' any time to finish early.\n")
        try:
            for prompt in PROMPTS:
                answer = self.ask(prompt["text"])
                if answer == "DONE":
                    break
                self._record_turn(prompt["id"], prompt["text"], answer)
                follow_up = _find_follow_up(prompt["id"], answer)
                if follow_up:
                    follow_answer = self.ask(follow_up)
                    if follow_answer == "DONE":
                        break
                    self._record_turn(prompt["id"] + ":followup", follow_up, follow_answer)
        except VoiceIOError as exc:
            self._output(f"\n⚠️  Voice input failed ({exc}) — continuing in typed mode.")
            self._disable_voice()
            # resume the loop in typed mode
            self._resume_typed()
        self.ended_at = datetime.now(timezone.utc).isoformat()
        return self.finish()

    def _resume_typed(self) -> None:
        """After a voice failure, re-run the remaining base prompts in typed mode."""
        done_ids = {t["prompt_id"].split(":")[0] for t in self.turns if t.get("answer")}
        for prompt in PROMPTS:
            if prompt["id"] in done_ids:
                continue
            answer = self.ask(prompt["text"])
            if answer == "DONE":
                break
            self._record_turn(prompt["id"], prompt["text"], answer)

    def _record_turn(self, prompt_id: str, prompt: str, answer: str) -> None:
        self.turns.append({
            "n": len(self.turns) + 1,
            "prompt_id": prompt_id,
            "prompt": prompt,
            "answer": answer,
            "answered_at": datetime.now(timezone.utc).isoformat(),
        })

    # -- persistence ------------------------------------------------------------

    def transcript_dict(self) -> dict:
        answers = {t["prompt_id"]: t["answer"] for t in self.turns}
        return {
            "id": self.debrief_id,
            "app_id": self.app_id,
            "company": self.company,
            "role": self.role,
            "started_at": self.started_at,
            "ended_at": self.ended_at or datetime.now(timezone.utc).isoformat(),
            "mode": "voice" if self._io() is not None else "typed",
            "turns": self.turns,
            "summary": _local_summary(self.debrief_id, self.app_id, self.company,
                                     self.role, answers, self.turns),
            "extraction": {},
        }

    def save_transcript(self) -> Path:
        """Write one JSON file per debrief under debriefs/<id>.json."""
        DEBRIEFS_DIR.mkdir(parents=True, exist_ok=True)
        path = DEBRIEFS_DIR / f"{self.debrief_id}.json"
        path.write_text(json.dumps(self.transcript_dict(), indent=2),
                        encoding="utf-8")
        self.transcript_path = path
        return path

    def register(self, summary: dict | None = None) -> bool:
        """Register with worker C's store. Returns True if the store ran.

        ``summary`` is the extracted result when available; otherwise the
        local offline summary is registered.
        """
        try:
            from candid import debrief as D  # worker C's store module
        except ImportError:
            return False
        record = getattr(D, "record_debrief", None)
        if not callable(record):
            return False
        summary = summary if isinstance(summary, dict) else {}
        if not summary:
            summary = self.transcript_dict().get("summary", {})
        try:
            record(
                self.app_id, self.company, self.role,
                str(self.transcript_path or ""),
                summary,
            )
        except Exception:
            return False
        return True

    def extract(self) -> dict:
        """Run worker C's extraction on the turns; stores results on the record."""
        try:
            from candid import debrief_extract as E  # worker C's extraction module
        except ImportError:
            return {}
        extractor = getattr(E, "extract", None)
        if not callable(extractor):
            return {}
        try:
            result = extractor(self.turns) or {}
        except Exception:
            return {}
        if isinstance(result, dict):
            return result
        return {"result": result}

    def finish(self) -> dict:
        """End the session: persist transcript, run extraction, register, report."""
        path = self.save_transcript()
        extraction = self.extract()
        if extraction:
            record = self.transcript_dict()
            record["extraction"] = extraction
            path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        registered = self.register(extraction)
        summary = self.transcript_dict()["summary"]
        self._output(f"\n✅ Debrief saved to {path} ({len(self.turns)} turns).")
        self._output(f"   Company: {self.company or '-'} · Role: {self.role or '-'}"
                     + (f" · App #{self.app_id}" if self.app_id else ""))
        if registered:
            self._output("   Registered with the debrief store.")
        return {
            "id": self.debrief_id,
            "transcript_path": str(path),
            "num_turns": len(self.turns),
            "registered": registered,
            "summary": summary,
            "extraction": extraction,
        }


def _local_summary(debrief_id: str, app_id: int | None, company: str, role: str,
                   answers: dict, turns: list[dict]) -> dict:
    """Cheap offline summary of the session — the store record, and the
    fallback if worker C's extraction is unavailable."""
    return {
        "debrief_id": debrief_id,
        "app_id": app_id,
        "company": company,
        "role": role,
        "num_turns": len(turns),
        "asked_about": answers.get("asked", ""),
        "stumped_on": answers.get("stumped", ""),
        "went_well": answers.get("went_well", ""),
        "next_steps": answers.get("next_steps", ""),
    }


# ---------------------------------------------------------------------------
# reading transcripts back (show / list / export)
# ---------------------------------------------------------------------------


def _all_transcript_files() -> list[Path]:
    if not DEBRIEFS_DIR.exists():
        return []
    return sorted(DEBRIEFS_DIR.glob("deb-*.json"), reverse=True)


def load_transcript(debrief_id: str) -> dict:
    """Load a transcript file by id (accepts with or without the deb- prefix)."""
    name = debrief_id if debrief_id.endswith(".json") else debrief_id + ".json"
    path = DEBRIEFS_DIR / name
    if not path.exists():
        # allow partial id match
        candidates = [p for p in _all_transcript_files()
                      if p.name.startswith(debrief_id)]
        if not candidates:
            raise DebriefError(
                f"No debrief found for id {debrief_id!r}. "
                "Run `python -m candid debrief list` to see ids.")
        path = candidates[0]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DebriefError(f"Debrief file {path} is not valid JSON: {exc}") from exc
    return data


def list_transcripts(app_id: int | None = None) -> list[dict]:
    """List transcript summaries, newest first; optionally filtered by app id."""
    out = []
    for path in _all_transcript_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if app_id is not None and data.get("app_id") != app_id:
            continue
        out.append({
            "id": data.get("id", path.stem),
            "app_id": data.get("app_id"),
            "company": data.get("company", ""),
            "role": data.get("role", ""),
            "ended_at": data.get("ended_at", ""),
            "num_turns": len(data.get("turns", [])),
            "path": str(path),
        })
    return out


def render_transcript(data: dict) -> str:
    """Human-readable rendering of a transcript for `debrief show`."""
    lines = [
        f"Debrief {data.get('id', '')}",
        f"Company: {data.get('company') or '-'}   Role: {data.get('role') or '-'}"
        + (f"   App #{data['app_id']}" if data.get("app_id") else ""),
        f"Started: {data.get('started_at', '-')}   Ended: {data.get('ended_at', '-')}",
        f"Turns: {len(data.get('turns', []))}",
        "",
    ]
    for t in data.get("turns", []):
        lines.append(f"Q{t['n']}: {t['prompt']}")
        lines.append(f"A{t['n']}: {t['answer']}\n")
    ext = data.get("extraction") or {}
    if ext:
        lines.append("--- extraction ---")
        lines.append(json.dumps(ext, indent=2))
    return "\n".join(lines).rstrip()


def export_transcript(data: dict, fmt: str, dest: str | Path | None = None) -> Path:
    """Export a transcript to markdown or txt; returns the output path."""
    fmt = fmt.lower()
    if fmt not in ("md", "txt"):
        raise DebriefError(f"Unknown export format {fmt!r} — choose md or txt.")
    out_path = Path(dest) if dest else (
        C.DATA_DIR / f"{data.get('id', 'debrief')}_debrief.{fmt}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "md":
        lines = [
            f"# Interview debrief — {data.get('company') or 'unknown company'}"
            f" ({data.get('role') or 'unknown role'})",
            "",
            f"- Debrief id: `{data.get('id', '')}`",
            f"- App id: {data.get('app_id') or '-'}",
            f"- Date: {data.get('ended_at', '-')}",
            f"- Turns: {len(data.get('turns', []))}",
            "",
        ]
        for t in data.get("turns", []):
            lines.append(f"## Q{t['n']}: {t['prompt']}")
            lines.append("")
            lines.append(t.get("answer", ""))
            lines.append("")
        if data.get("extraction"):
            lines.append("## Extraction")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(data["extraction"], indent=2))
            lines.append("```")
    else:
        lines = [
            f"Interview debrief — {data.get('company') or 'unknown company'}"
            f" ({data.get('role') or 'unknown role'})",
            f"Debrief id: {data.get('id', '')} · App id: {data.get('app_id') or '-'}",
            f"Date: {data.get('ended_at', '-')}",
            "=" * 60,
            "",
        ]
        for t in data.get("turns", []):
            lines.append(f"Q{t['n']}: {t['prompt']}")
            lines.append(f"A{t['n']}: {t.get('answer', '')}")
            lines.append("")
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# one-shot session driver used by the CLI
# ---------------------------------------------------------------------------


def start_session(app_id: int | None, company: str, role: str,
                  *, typed: bool = False) -> dict:
    """Begin an interactive debrief session (CLI entry point)."""
    session = DebriefSession.start_session(
        app_id, company, role, force_typed=typed,
    )
    if typed:
        session._output("Typed mode: type your answers (blank line to finish, 'done' to end).")
    elif session._io() is None:
        session._output("⚠️  Voice IO not available — falling back to typed mode.")
    return session.run()


def resolve_company_role(app_id: int | None, company: str, role: str) -> tuple[int | None, str, str]:
    """Fill company/role from the tracker when --app is given."""
    if app_id is not None:
        from candid import tracker as T
        rec = next((x for x in T.list_apps() if x["id"] == app_id), None)
        if rec is None:
            raise DebriefError(
                f"No tracked application with id {app_id}. "
                "Run `python -m candid track list` to see ids.")
        company = company or rec["company"]
        role = role or rec["role"]
    return app_id, company, role

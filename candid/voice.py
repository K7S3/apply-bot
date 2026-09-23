"""Voice layer for mock interviews: optional TTS + pluggable STT, text fallback.

Fully optional and offline-first. TTS uses only system engines found on
PATH (macOS ``say``, Linux ``espeak`` / ``spd-say``) via subprocess — no
new dependencies. If no engine is found, questions are printed as text and
the session continues normally.

STT backends are pluggable through :class:`STTBackend`. The built-in
``typed`` backend (multi-line typed input) is always available and is the
offline default; heavier backends (Vosk, SpeechRecognition) are registered
automatically when their packages import, and any requested-but-unavailable
backend degrades back to ``typed`` with a notice. No audio is recorded or
saved — only the final transcript text lands in the session report.

Transcript scoring is a plain keyword/point-coverage heuristic in the same
honest spirit as ``mock.score_star``: it reports covered vs missed points,
never a fabricated grade.
"""

from __future__ import annotations

import abc
import os
import re
import shutil
import subprocess

# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------

class VoiceError(Exception):
    """Raised for voice-mode usage errors (unknown backend, etc.)."""


# ---------------------------------------------------------------------------
# TTS: system engines only, graceful fallback
# ---------------------------------------------------------------------------

#: engine name -> argv prefix. First match on PATH wins.
_TTS_ENGINES = (
    ("say", ["say"]),            # macOS
    ("espeak", ["espeak"]),      # Linux
    ("spd-say", ["spd-say"]),    # Linux (speech-dispatcher)
)


def find_tts() -> tuple[str, list[str]] | None:
    """Return (engine_name, argv_prefix) for the first TTS engine on PATH."""
    for name, argv in _TTS_ENGINES:
        if shutil.which(argv[0]):
            return name, argv
    return None


def tts_available() -> bool:
    return find_tts() is not None


def speak(text: str, timeout_s: int = 180) -> str:
    """Speak `text` via a system TTS engine. Returns "tts" or "text".

    Returns "text" when no engine is available or speaking fails — the
    caller should print the question as text in that case.
    """
    engine = find_tts()
    if engine is None:
        return "text"
    name, argv = engine
    try:
        subprocess.run(argv + [text], timeout=timeout_s, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (subprocess.SubprocessError, OSError):
        return "text"
    return "tts"


# ---------------------------------------------------------------------------
# STT: pluggable backends
# ---------------------------------------------------------------------------

class STTBackend(abc.ABC):
    """Interface for speech-to-text answer capture."""

    name = "base"

    @classmethod
    def is_available(cls) -> bool:
        """True if this backend can be used in this environment."""
        return False

    @classmethod
    def why_unavailable(cls) -> str:
        return "not implemented"

    @abc.abstractmethod
    def capture(self, prompt: str = "") -> str:
        """Capture one spoken answer and return it as text."""


class TypedSTT(STTBackend):
    """Offline default: type the answer (multi-line, end with EOF line)."""

    name = "typed"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def capture(self, prompt: str = "") -> str:
        if prompt:
            print(prompt)
        print("Type your answer below (end with a line containing only EOF, or press Ctrl-D).")
        lines: list[str] = []
        try:
            while True:
                line = input()
                if line.strip() == "EOF":
                    break
                lines.append(line)
        except EOFError:
            pass
        return "\n".join(lines)


class VoskSTT(STTBackend):
    """Offline Vosk model backend. Registered only if `vosk` imports."""

    name = "vosk"

    @classmethod
    def is_available(cls) -> bool:
        try:
            import vosk  # noqa: F401
        except ImportError:
            return False
        return True

    @classmethod
    def why_unavailable(cls) -> str:
        return "the `vosk` package is not installed (pip install vosk) and a Vosk model is required"

    def capture(self, prompt: str = "") -> str:
        raise VoiceError(
            "VoskSTT.capture is a stub: wire your model path and microphone in "
            "candid/voice.py. Falling back to typed input.\n"
            "Next: run `python -m candid mock voice --help`.")


class SpeechRecognitionSTT(STTBackend):
    """SpeechRecognition library backend. Registered only if it imports."""

    name = "speech_recognition"

    @classmethod
    def is_available(cls) -> bool:
        try:
            import speech_recognition  # noqa: F401
        except ImportError:
            return False
        return True

    @classmethod
    def why_unavailable(cls) -> str:
        return "the `speech_recognition` package is not installed (pip install SpeechRecognition)"

    def capture(self, prompt: str = "") -> str:
        raise VoiceError(
            "SpeechRecognitionSTT.capture is a stub: wire your microphone engine in "
            "candid/voice.py. Falling back to typed input.\n"
            "Next: run `python -m candid mock voice --help`.")


_BACKENDS: dict[str, type[STTBackend]] = {}


def register_backend(cls: type[STTBackend]) -> type[STTBackend]:
    """Register an STT backend class. Returns the class (usable as decorator)."""
    _BACKENDS[cls.name] = cls
    return cls


register_backend(TypedSTT)
register_backend(VoskSTT)
register_backend(SpeechRecognitionSTT)


def known_backends() -> list[str]:
    return sorted(_BACKENDS)


def select_stt(name: str | None = None) -> STTBackend:
    """Pick an STT backend. Unknown names raise VoiceError; unavailable
    backends degrade to the `typed` backend with a notice."""
    name = (name or os.environ.get("CANDID_STT_BACKEND") or "typed").strip().lower()
    cls = _BACKENDS.get(name)
    if cls is None:
        raise VoiceError(
            f"Unknown STT backend '{name}'. Known: {', '.join(known_backends())}.\n"
            "Next: run `python -m candid mock voice --help`.")
    if not cls.is_available():
        print(f"STT backend '{name}' is not available ({cls.why_unavailable()}) — "
              "using typed input instead.")
        return TypedSTT()
    return cls()


# ---------------------------------------------------------------------------
# transcript scoring: honest keyword/point coverage
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset("""
a an and are as at be but by for from has have in is it its of on or that the
to was were will with you your this they their them what how when where which
who why can could should would do does did not no yes so if then than such
very just about into over after before between through during each other some
any all both few more most own same too per out up down
""".split())


def significant_words(text: str, min_len: int = 4, limit: int = 12) -> list[str]:
    """Content words from free text, for building keyword lists."""
    words = re.findall(r"[a-z0-9][a-z0-9+\-]*", text.lower())
    seen: list[str] = []
    for w in words:
        if len(w) < min_len or w in _STOPWORDS or w in seen:
            continue
        seen.append(w)
        if len(seen) >= limit:
            break
    return seen


def score_points(transcript: str, points: list[dict]) -> dict:
    """Keyword coverage of a transcript against expected key points.

    Each point is ``{"point": str, "keywords": [str]}``. A point counts as
    covered when at least one keyword appears in the transcript. This is a
    heuristic self-check, not an automated grade.
    """
    low = transcript.lower()
    covered, missed = [], []
    for p in points:
        hits = [k for k in p.get("keywords", []) if k.lower() in low]
        entry = {"point": p["point"], "hits": hits}
        (covered if hits else missed).append(entry)
    return {"score": len(covered), "max": len(points),
            "covered": covered, "missed": missed}


def render_point_score(result: dict) -> str:
    lines = [
        f"\nPoint coverage: {result['score']}/{result['max']} "
        "(keyword heuristic — a self-check, not an automated grade)",
    ]
    for c in result["covered"]:
        hits = ", ".join(c["hits"][:6])
        lines.append(f"  ✅ {c['point']}" + (f"  [matched: {hits}]" if hits else ""))
    for m in result["missed"]:
        lines.append(f"  ❌ {m['point']}")
    return "\n".join(lines)

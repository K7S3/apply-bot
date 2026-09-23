"""Local-first voice I/O layer for candid: mic recording, speech-to-text, text-to-speech.

Everything here is optional and offline. Every function degrades gracefully:
if no microphone, no STT engine, or no TTS engine is available, the module
falls back to typed input / printed text instead of failing. No network
calls, no API keys, ever.

Backends (all local):
  recording: sounddevice -> `arecord` -> `rec` (sox) -> None
  STT:       vosk (local model) -> whisper.cpp CLI -> STTUnavailable
  TTS:       espeak-ng / espeak / say CLI -> print with [voice] prefix

Dependency injection for tests: the backend-selection helpers are
module-level functions (prefixed `_`) so tests can monkeypatch them without
real audio hardware. `listen()` is the single entry point the session engine
calls per turn.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import wave
from pathlib import Path

SAMPLE_RATE = 16000
CHANNELS = 1

AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a"}


class STTUnavailable(Exception):
    """Raised when no local speech-to-text backend is usable."""

    def __init__(self, detail: str = ""):
        msg = (
            "No local speech-to-text engine is available. "
            "Install one of:\n"
            "  - vosk:  pip install vosk  and place a model in VOSK_MODEL_DIR\n"
            "           (e.g. https://alphacephei.com/vosk/models,\n"
            "           unpack to a directory and point VOSK_MODEL_DIR at it)\n"
            "  - whisper.cpp: install the whisper-cli / whisper-cpp binary and\n"
            "           its model file (https://github.com/ggml-org/whisper.cpp)\n"
            "Or type your answers instead of speaking them."
        )
        if detail:
            msg = f"{detail}\n{msg}"
        super().__init__(msg)


# ---------------------------------------------------------------------------
# microphone detection
# ---------------------------------------------------------------------------

def _sounddevice_input_devices() -> list:
    """Return sounddevice input devices, or [] if sounddevice is unusable."""
    try:
        import sounddevice as sd  # type: ignore[import]

        devices = sd.query_devices()
        inputs = [d for d in devices if d.get("max_input_channels", 0) > 0]
        return inputs
    except Exception:
        return []


def _arecord_list() -> bool:
    """True if `arecord -l` reports at least one capture device."""
    if not shutil.which("arecord"):
        return False
    try:
        out = subprocess.run(
            ["arecord", "-l"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.returncode == 0 and "card" in out.stdout.lower()
    except Exception:
        return False


def mic_available() -> bool:
    """Detect a usable microphone. Never raises."""
    try:
        if _sounddevice_input_devices():
            return True
    except Exception:
        pass
    try:
        if _arecord_list():
            return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# recording
# ---------------------------------------------------------------------------

def _stop_hint(max_seconds: int) -> str:
    mins, secs = divmod(int(max_seconds), 60)
    return (
        f"Recording from the default microphone (max {mins}:{secs:02d}).\n"
        "Press Ctrl-C to stop recording."
    )


def _record_with_sounddevice(path: Path, max_seconds: int) -> Path:
    """Record via the sounddevice python package. Raises on failure."""
    try:
        import sounddevice as sd  # type: ignore[import]
    except ImportError as e:
        raise RuntimeError("sounddevice is not installed") from e

    print(_stop_hint(max_seconds))
    chunks: list[bytes] = []
    recorded = 0.0
    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16"
        ) as stream:
            while recorded < max_seconds:
                block = min(SAMPLE_RATE, int((max_seconds - recorded) * SAMPLE_RATE))
                data, _ = stream.read(block)
                chunks.append(data.tobytes())
                recorded += block / SAMPLE_RATE
    except KeyboardInterrupt:
        print("\nRecording stopped.")
    _write_wav(path, b"".join(chunks))
    return path


def _record_with_arecord(path: Path, max_seconds: int) -> Path:
    """Record via the `arecord` ALSA CLI. Raises on failure."""
    print(_stop_hint(max_seconds))
    cmd = [
        "arecord",
        "-f", "S16_LE",
        "-r", str(SAMPLE_RATE),
        "-c", str(CHANNELS),
        "-d", str(int(max_seconds)),
        str(path),
    ]
    try:
        subprocess.run(cmd, check=False, timeout=max_seconds + 5)
    except KeyboardInterrupt:
        print("\nRecording stopped.")
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError("arecord produced no audio")
    return path


def _record_with_sox(path: Path, max_seconds: int) -> Path:
    """Record via sox `rec`. Raises on failure."""
    print(_stop_hint(max_seconds))
    cmd = [
        "rec",
        "-r", str(SAMPLE_RATE),
        "-c", str(CHANNELS),
        str(path),
        "trim", "0", str(int(max_seconds)),
    ]
    try:
        subprocess.run(cmd, check=False, timeout=max_seconds + 5)
    except KeyboardInterrupt:
        print("\nRecording stopped.")
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError("sox rec produced no audio")
    return path


def _write_wav(path: Path, frames: bytes) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(frames)


# Ordered backend chain. Each entry: (name, function).
_RECORD_BACKENDS = [
    ("sounddevice", _record_with_sounddevice),
    ("arecord", _record_with_arecord),
    ("sox rec", _record_with_sox),
]


def record_to_wav(path: str | Path, max_seconds: int = 300) -> Path | None:
    """Record from the default mic and save as a 16kHz mono WAV.

    Backend chain: sounddevice -> arecord -> sox `rec`. Returns the wav path,
    or None (after printing a clear message) when nothing can record.
    Ctrl-C stops the recording cleanly and keeps what was captured.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    for name, backend in _RECORD_BACKENDS:
        try:
            return backend(out, max_seconds)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"[voice] {name} recorder unavailable ({e}); trying next backend.")
    print(
        "[voice] No microphone recorder available. "
        "Install sounddevice (pip install sounddevice), or the `arecord` / "
        "`rec` (sox) CLI, or type your answers instead."
    )
    return None


# ---------------------------------------------------------------------------
# speech to text (all local/offline)
# ---------------------------------------------------------------------------

def _vosk_model_dir() -> Path | None:
    candidates = []
    env = os.environ.get("VOSK_MODEL_DIR")
    if env:
        candidates.append(Path(env))
    candidates += [
        Path.cwd() / "models" / "vosk",
        Path.home() / ".cache" / "vosk",
        Path(__file__).resolve().parent.parent / "models" / "vosk",
    ]
    for c in candidates:
        try:
            if c.is_dir() and any(c.iterdir()):
                return c
        except Exception:
            continue
    return None


def _transcribe_with_vosk(path: Path) -> str:
    """Transcribe with vosk and a locally present model. Raises on failure."""
    try:
        from vosk import KaldiRecognizer, Model  # type: ignore[import]
    except ImportError as e:
        raise RuntimeError("vosk is not installed") from e
    model_dir = _vosk_model_dir()
    if model_dir is None:
        raise RuntimeError("no local vosk model found (set VOSK_MODEL_DIR)")
    import json

    model = Model(str(model_dir))
    rec = KaldiRecognizer(model, SAMPLE_RATE)
    with wave.open(str(path), "rb") as wf:
        while True:
            data = wf.readframes(4000)
            if not data:
                break
            rec.AcceptWaveform(data)
    result = json.loads(rec.FinalResult())
    return (result.get("text") or "").strip()


def _transcribe_with_whisper(path: Path) -> str:
    """Transcribe with the whisper.cpp CLI. Raises on failure."""
    binary = shutil.which("whisper-cli") or shutil.which("whisper-cpp")
    if binary is None:
        raise RuntimeError("whisper-cli / whisper-cpp not found on PATH")
    txt_path = path.with_suffix(".txt")
    cmd = [binary, "-f", str(path), "-otxt", "-of", str(path.with_suffix(""))]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
    except Exception as e:
        raise RuntimeError(f"whisper.cpp failed: {e}") from e
    if txt_path.exists():
        return txt_path.read_text().strip()
    raise RuntimeError("whisper.cpp produced no output")


# Ordered backend chain. Each entry: (name, function).
_STT_BACKENDS = [
    ("vosk", _transcribe_with_vosk),
    ("whisper.cpp", _transcribe_with_whisper),
]


def transcribe_wav(path: str | Path) -> str:
    """Transcribe a wav file to text using local/offline engines only.

    Backend chain: vosk (with a locally present model) -> whisper.cpp CLI.
    Raises STTUnavailable when nothing is usable. Never makes network calls.
    """
    wav = Path(path)
    if not wav.exists():
        raise FileNotFoundError(f"audio file not found: {wav}")
    errors = []
    for name, backend in _STT_BACKENDS:
        try:
            return backend(wav)
        except Exception as e:
            errors.append(f"{name}: {e}")
    raise STTUnavailable("; ".join(errors))


# ---------------------------------------------------------------------------
# text to speech
# ---------------------------------------------------------------------------

def _speak_with_espeak(text: str) -> None:
    binary = shutil.which("espeak-ng") or shutil.which("espeak")
    if binary is None:
        raise RuntimeError("espeak-ng / espeak not found on PATH")
    subprocess.run([binary, text], check=False, timeout=120)


def _speak_with_say(text: str) -> None:
    if shutil.which("say") is None:
        raise RuntimeError("say not found on PATH")
    subprocess.run(["say", text], check=False, timeout=120)


_TTS_BACKENDS = [
    ("espeak-ng/espeak", _speak_with_espeak),
    ("say", _speak_with_say),
]


def speak(text: str) -> None:
    """Speak text aloud via espeak-ng / espeak / say if present.

    Falls back to printing the text with a [voice] prefix. Never fails.
    """
    for _, backend in _TTS_BACKENDS:
        try:
            backend(text)
            return
        except Exception:
            continue
    print(f"[voice] {text}")


# ---------------------------------------------------------------------------
# audio file helpers
# ---------------------------------------------------------------------------

def audio_file_supported(path: str | Path) -> bool:
    """True for .wav/.mp3/.m4a files.

    Non-wav formats need ffmpeg for conversion, so they only count as
    supported when ffmpeg is on PATH.
    """
    ext = Path(path).suffix.lower()
    if ext not in AUDIO_EXTENSIONS:
        return False
    if ext != ".wav" and shutil.which("ffmpeg") is None:
        return False
    return True


def convert_to_wav(src: str | Path, dst: str | Path) -> Path:
    """Convert an audio file to 16kHz mono WAV using ffmpeg.

    Raises RuntimeError when ffmpeg is missing or conversion fails.
    """
    src_p, dst_p = Path(src), Path(dst)
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is not installed; cannot convert audio")
    if not src_p.exists():
        raise FileNotFoundError(f"audio file not found: {src_p}")
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(src_p),
        "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS),
        str(dst_p),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300
        )
    except Exception as e:
        raise RuntimeError(f"ffmpeg conversion failed: {e}") from e
    if result.returncode != 0 or not dst_p.exists():
        raise RuntimeError(
            f"ffmpeg conversion failed: {result.stderr.strip()[-500:]}"
        )
    return dst_p


# ---------------------------------------------------------------------------
# one-shot turn: the session engine calls this
# ---------------------------------------------------------------------------

def listen(prompt_text: str) -> str:
    """Speak (or print) a prompt, then capture the user's spoken answer.

    Tries record -> transcribe; on ANY failure (no mic, no STT engine,
    interrupted recording, empty result) falls back to typed input. Never
    raises for audio reasons; always returns the user's text.
    """
    try:
        speak(prompt_text)
    except Exception as e:
        print(f"[voice] text-to-speech unavailable ({e}); showing the prompt instead.")
    try:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="candid_voice_") as td:
            wav = Path(td) / "answer.wav"
            recorded = record_to_wav(wav)
            if recorded is None:
                raise RuntimeError("recording unavailable")
            text = transcribe_wav(recorded).strip()
            if not text:
                raise RuntimeError("transcription was empty")
            print(f"[you] {text}")
            return text
    except Exception as e:
        print(f"[voice] voice input unavailable ({e}); falling back to typed input.")
    return input("You (type): ").strip()

# Voice mock interviews

`python -m candid mock voice --kind behavioral|coding|design` runs a mock
interview where the question is **read aloud** (system TTS when available)
and your answer is captured via a **pluggable STT backend** — with a typed
fallback so it works on any machine, no hardware or accounts needed.

```bash
python -m candid mock voice --kind behavioral
python -m candid mock voice --kind design --level senior
python -m candid mock voice --kind coding --difficulty medium --problem two-sum
python -m candid mock voice --kind behavioral --stt-backend vosk
```

The session scores your transcript by **key-point coverage** (keyword
heuristic, same honest style as the STAR self-check): covered vs missed
points, never a fabricated grade. The report is saved to
`candid_data/mock_sessions/` like every other mock track.

## Text-to-speech

`candid/voice.py` uses only system engines found on `PATH` — no
dependencies, no network:

| Engine | Platform | Install |
|---|---|---|
| `say` | macOS | built in |
| `espeak` | Linux | `sudo apt install espeak` (or your package manager) |
| `spd-say` | Linux | `sudo apt install speech-dispatcher` |

If none is found the command says so (`No TTS engine found ... Text
mode.`) and continues with the question printed as text. The first engine
on `PATH` wins.

## Speech-to-text backends

`STTBackend` in `candid/voice.py` is the interface (`is_available()`,
`capture(prompt)`). Backends are chosen with `--stt-backend` or the
`CANDID_STT_BACKEND` environment variable.

| Backend | Availability | Notes |
|---|---|---|
| `typed` | always | Offline default. Type your answer (multi-line, end with an `EOF` line). |
| `vosk` | if the `vosk` package imports | Stub: wire your model + mic in `VoskSTT.capture`. |
| `speech_recognition` | if the `SpeechRecognition` package imports | Stub: wire your mic engine in `SpeechRecognitionSTT.capture`. |

A requested backend that isn't available **degrades to `typed` with a
notice** — the session never fails for lack of a microphone. No audio is
ever recorded or saved; only the final transcript text lands in the local
session report.

To add your own backend, subclass `STTBackend` and call
`voice.register_backend(MyBackend)` — see `VoskSTT` for the shape.

## Scoring

`voice.score_points(transcript, points)` marks a point *covered* when at
least one of its keywords appears in the transcript. Key points come from
the question data itself:

- **behavioral**: the STAR rubric dimensions + "what good looks like"
- **design**: the prompt's sample-structure steps
- **coding**: the problem's hints + a complexity-analysis point (you talk
  through your *approach* out loud, not the code)

This is a rehearsal self-check, not an automated grader — it tells you
which elements you mentioned and which you skipped.

## Limits

- One question per session (like the other local tracks).
- No real-time speech recognition ships with candid — that needs a
  microphone, an OS speech engine, or a heavyweight ML dependency, all of
  which the pluggable interface leaves to you.
- TTS reads plain text; math/symbols in problem statements are read
  literally.

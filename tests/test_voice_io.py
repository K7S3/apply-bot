"""Tests for candid.voice_io (local-first voice I/O with graceful degradation).

Run: python -m unittest discover -s tests -v

No real audio hardware, mic, or network is needed: backends are faked via
module-level function hooks and shutil.which is patched.
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import voice_io as V


class MicAvailableTest(unittest.TestCase):
    def test_never_raises_when_backends_explode(self):
        with mock.patch.object(V, "_sounddevice_input_devices", side_effect=RuntimeError("boom")), \
             mock.patch.object(V, "_arecord_list", side_effect=RuntimeError("boom")):
            self.assertFalse(V.mic_available())

    def test_true_when_sounddevice_has_inputs(self):
        with mock.patch.object(V, "_sounddevice_input_devices",
                               return_value=[{"name": "mic", "max_input_channels": 1}]):
            self.assertTrue(V.mic_available())

    def test_true_when_arecord_sees_card(self):
        with mock.patch.object(V, "_sounddevice_input_devices", return_value=[]), \
             mock.patch.object(V, "_arecord_list", return_value=True):
            self.assertTrue(V.mic_available())


class RecordChainTest(unittest.TestCase):
    def test_falls_to_next_backend_on_failure(self):
        calls = []

        def failing(path, max_seconds):
            calls.append("failing")
            raise RuntimeError("no sounddevice")

        def working(path, max_seconds):
            calls.append("working")
            Path(path).write_bytes(b"wav")
            return Path(path)

        with mock.patch.object(V, "_RECORD_BACKENDS",
                               [("first", failing), ("second", working)]):
            with tempfile.TemporaryDirectory() as td:
                out = V.record_to_wav(Path(td) / "a.wav")
                self.assertEqual(calls, ["failing", "working"])
                self.assertIsNotNone(out)
                self.assertTrue(Path(out).exists())

    def test_returns_none_with_message_when_nothing_available(self):
        with mock.patch.object(V, "_RECORD_BACKENDS", []):
            with tempfile.TemporaryDirectory() as td, \
                 contextlib.redirect_stdout(io.StringIO()) as buf:
                self.assertIsNone(V.record_to_wav(Path(td) / "a.wav"))
            self.assertIn("No microphone recorder available", buf.getvalue())


class TranscribeChainTest(unittest.TestCase):
    def test_vosk_tried_before_whisper(self):
        order = []

        def vosk(path):
            order.append("vosk")
            return "hello world"

        def whisper(path):
            order.append("whisper")
            return "should not run"

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"fake")
            p = Path(f.name)
        try:
            with mock.patch.object(V, "_STT_BACKENDS",
                                   [("vosk", vosk), ("whisper.cpp", whisper)]):
                self.assertEqual(V.transcribe_wav(p), "hello world")
                self.assertEqual(order, ["vosk"])
        finally:
            p.unlink(missing_ok=True)

    def test_vosk_failure_falls_through_to_whisper(self):
        def vosk(path):
            raise RuntimeError("no model")

        def whisper(path):
            return "fallback text"

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"fake")
            p = Path(f.name)
        try:
            with mock.patch.object(V, "_STT_BACKENDS",
                                   [("vosk", vosk), ("whisper.cpp", whisper)]):
                self.assertEqual(V.transcribe_wav(p), "fallback text")
        finally:
            p.unlink(missing_ok=True)

    def test_raises_stt_unavailable_when_nothing_works(self):
        def bad(path):
            raise RuntimeError("nope")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"fake")
            p = Path(f.name)
        try:
            with mock.patch.object(V, "_STT_BACKENDS", [("vosk", bad)]):
                with self.assertRaises(V.STTUnavailable) as ctx:
                    V.transcribe_wav(p)
                self.assertIn("vosk", str(ctx.exception))
                self.assertIn("type your answers", str(ctx.exception).lower())
        finally:
            p.unlink(missing_ok=True)

    def test_missing_file_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            V.transcribe_wav("/tmp/definitely-not-here-candid.wav")


class SpeakTest(unittest.TestCase):
    def test_fallback_prints_with_voice_prefix(self):
        with mock.patch.object(V, "_TTS_BACKENDS", []), \
             contextlib.redirect_stdout(io.StringIO()) as buf:
            V.speak("hello there")
        self.assertIn("[voice] hello there", buf.getvalue())

    def test_uses_first_working_backend(self):
        calls = []

        def first(text):
            calls.append(("first", text))

        def second(text):
            calls.append(("second", text))
            raise AssertionError("should not run")

        with mock.patch.object(V, "_TTS_BACKENDS",
                               [("one", first), ("two", second)]):
            V.speak("hi")
        self.assertEqual(calls, [("first", "hi")])

    def test_broken_backend_falls_through(self):
        def broken(text):
            raise RuntimeError("no speaker")

        spoken = []

        def working(text):
            spoken.append(text)

        with mock.patch.object(V, "_TTS_BACKENDS",
                               [("broken", broken), ("working", working)]):
            V.speak("hi")
        self.assertEqual(spoken, ["hi"])

    def test_never_raises(self):
        def broken(text):
            raise RuntimeError("nope")

        with mock.patch.object(V, "_TTS_BACKENDS", [("broken", broken)]), \
             contextlib.redirect_stdout(io.StringIO()):
            V.speak("hi")  # must not raise


class AudioFileTest(unittest.TestCase):
    def test_wav_supported_without_ffmpeg(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertTrue(V.audio_file_supported("clip.wav"))
            self.assertTrue(V.audio_file_supported("CLIP.WAV"))

    def test_mp3_m4a_need_ffmpeg(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(V.audio_file_supported("clip.mp3"))
            self.assertFalse(V.audio_file_supported("clip.m4a"))
        with mock.patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            self.assertTrue(V.audio_file_supported("clip.mp3"))
            self.assertTrue(V.audio_file_supported("clip.m4a"))

    def test_unknown_extension_rejected(self):
        with mock.patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            self.assertFalse(V.audio_file_supported("clip.ogg"))
            self.assertFalse(V.audio_file_supported("clip.txt"))

    def test_convert_to_wav_requires_ffmpeg(self):
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaises(RuntimeError) as ctx:
                V.convert_to_wav("a.mp3", "a.wav")
            self.assertIn("ffmpeg", str(ctx.exception).lower())

    def test_convert_to_wav_calls_ffmpeg(self):
        with mock.patch("shutil.which", return_value="/usr/bin/ffmpeg"), \
             mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stderr="")
            with tempfile.TemporaryDirectory() as td:
                src = Path(td) / "in.mp3"
                src.write_bytes(b"fake")
                dst = Path(td) / "out.wav"
                dst.write_bytes(b"fake-wav")  # ffmpeg is mocked; simulate output
                out = V.convert_to_wav(src, dst)
                self.assertEqual(out, dst)
            cmd = run.call_args[0][0]
            self.assertIn("ffmpeg", cmd[0])
            self.assertIn("16000", cmd)


class ListenTest(unittest.TestCase):
    def test_voice_success_returns_transcript(self):
        with mock.patch.object(V, "speak"), \
             mock.patch.object(V, "record_to_wav", return_value=Path("/tmp/x.wav")), \
             mock.patch.object(V, "transcribe_wav", return_value="my answer"), \
             mock.patch("builtins.input") as fake_input, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(V.listen("Say something"), "my answer")
            fake_input.assert_not_called()

    def test_missing_everything_degrades_to_typed_input(self):
        with mock.patch.object(V, "speak"), \
             mock.patch.object(V, "record_to_wav", return_value=None), \
             mock.patch("builtins.input", return_value="typed answer") as fake_input, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(V.listen("Say something"), "typed answer")
            fake_input.assert_called_once()

    def test_stt_failure_degrades_to_typed_input(self):
        with mock.patch.object(V, "speak"), \
             mock.patch.object(V, "record_to_wav", return_value=Path("/tmp/x.wav")), \
             mock.patch.object(V, "transcribe_wav",
                               side_effect=V.STTUnavailable()), \
             mock.patch("builtins.input", return_value="typed instead"), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(V.listen("Say something"), "typed instead")

    def test_empty_transcript_degrades_to_typed_input(self):
        with mock.patch.object(V, "speak"), \
             mock.patch.object(V, "record_to_wav", return_value=Path("/tmp/x.wav")), \
             mock.patch.object(V, "transcribe_wav", return_value="   "), \
             mock.patch("builtins.input", return_value="typed"), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(V.listen("Say something"), "typed")

    def test_speak_failure_still_reaches_input(self):
        with mock.patch.object(V, "speak", side_effect=RuntimeError("no tts")), \
             mock.patch.object(V, "record_to_wav", side_effect=RuntimeError("no mic")), \
             mock.patch("builtins.input", return_value="typed"), \
             contextlib.redirect_stdout(io.StringIO()):
            # listen swallows audio errors; only input errors propagate
            self.assertEqual(V.listen("Say something"), "typed")


if __name__ == "__main__":
    unittest.main()

"""Tests for voice mock interviews (candid/voice.py + mock.voice_session).

The audio layer is fully mocked: no real TTS, microphone, or network.
Data paths are redirected into a temp dir.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import voice as V  # noqa: E402
from candid import mock as M  # noqa: E402
from candid import __main__ as CLI  # noqa: E402


class BackendSelectionTest(unittest.TestCase):
    def test_default_is_typed(self):
        os.environ.pop("CANDID_STT_BACKEND", None)
        backend = V.select_stt(None)
        self.assertIsInstance(backend, V.TypedSTT)

    def test_env_var_selects_backend(self):
        os.environ["CANDID_STT_BACKEND"] = "typed"
        try:
            self.assertIsInstance(V.select_stt(None), V.TypedSTT)
        finally:
            del os.environ["CANDID_STT_BACKEND"]

    def test_unknown_backend_raises(self):
        with self.assertRaises(V.VoiceError) as ctx:
            V.select_stt("not-a-backend")
        self.assertIn("Known:", str(ctx.exception))

    def test_unavailable_backend_falls_back_to_typed(self):
        # vosk is not installed in this environment -> graceful fallback
        if V.VoskSTT.is_available():
            self.skipTest("vosk unexpectedly installed")
        buf = io.StringIO()
        with redirect_stdout(buf):
            backend = V.select_stt("vosk")
        self.assertIsInstance(backend, V.TypedSTT)
        self.assertIn("not available", buf.getvalue())
        self.assertIn("typed input", buf.getvalue())

    def test_register_custom_backend(self):
        class EchoSTT(V.STTBackend):
            name = "echo-test"

            @classmethod
            def is_available(cls):
                return True

            def capture(self, prompt=""):
                return "echo"

        V.register_backend(EchoSTT)
        try:
            self.assertIn("echo-test", V.known_backends())
            self.assertIsInstance(V.select_stt("echo-test"), EchoSTT)
        finally:
            del V._BACKENDS["echo-test"]


class TTSFallbackTest(unittest.TestCase):
    def test_no_engine_returns_text(self):
        with mock.patch.object(V, "find_tts", return_value=None):
            self.assertEqual(V.speak("hello"), "text")

    def test_engine_invoked_via_subprocess(self):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(argv)
            return mock.Mock(returncode=0)

        with mock.patch.object(V, "find_tts", return_value=("espeak", ["espeak"])), \
             mock.patch("candid.voice.subprocess.run", side_effect=fake_run):
            self.assertEqual(V.speak("hello there"), "tts")
        self.assertEqual(calls, [["espeak", "hello there"]])

    def test_subprocess_failure_falls_back_to_text(self):
        import subprocess as sp

        with mock.patch.object(V, "find_tts", return_value=("say", ["say"])), \
             mock.patch("candid.voice.subprocess.run",
                        side_effect=sp.SubprocessError("boom")):
            self.assertEqual(V.speak("hello"), "text")


class ScorePointsTest(unittest.TestCase):
    POINTS = [
        {"point": "Situation: set context", "keywords": ["team", "project"]},
        {"point": "Result: quantified outcome", "keywords": ["increased", "shipped"]},
    ]

    def test_covered_and_missed(self):
        result = V.score_points(
            "On my team we shipped the project and increased signups.",
            self.POINTS)
        self.assertEqual(result["score"], 2)
        self.assertEqual(result["max"], 2)
        self.assertEqual(len(result["covered"]), 2)
        self.assertEqual(result["missed"], [])

    def test_partial_coverage(self):
        result = V.score_points("On my team we did the project work.", self.POINTS)
        self.assertEqual(result["score"], 1)
        self.assertEqual([c["point"] for c in result["covered"]],
                         ["Situation: set context"])
        self.assertEqual([m["point"] for m in result["missed"]],
                         ["Result: quantified outcome"])

    def test_empty_transcript_misses_everything(self):
        result = V.score_points("", self.POINTS)
        self.assertEqual(result["score"], 0)
        self.assertEqual(len(result["missed"]), 2)

    def test_render_shows_counts_and_marks(self):
        result = V.score_points("On my team we did the project work.", self.POINTS)
        text = V.render_point_score(result)
        self.assertIn("1/2", text)
        self.assertIn("not an automated grade", text)
        self.assertIn("✅", text)
        self.assertIn("❌", text)

    def test_significant_words_filters_stopwords(self):
        words = V.significant_words("The team shipped the project with great results")
        self.assertNotIn("the", words)
        self.assertNotIn("with", words)
        self.assertIn("team", words)
        self.assertIn("shipped", words)


class VoiceSessionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-voice-"))
        self._orig_sessions = M.SESSIONS_DIR
        M.SESSIONS_DIR = self.tmp / "mock_sessions"
        self._orig_data = C.DATA_DIR
        C.DATA_DIR = self.tmp

    def tearDown(self):
        M.SESSIONS_DIR = self._orig_sessions
        C.DATA_DIR = self._orig_data

    def _run_cli(self, argv, typed_lines):
        """Run the CLI with TTS absent and scripted typed input."""
        inputs = iter(typed_lines)

        def fake_input(prompt=""):
            try:
                return next(inputs)
            except StopIteration:
                raise EOFError

        buf = io.StringIO()
        with mock.patch.object(V, "find_tts", return_value=None), \
             mock.patch("builtins.input", side_effect=fake_input), \
             redirect_stdout(buf):
            CLI.main(argv)
        return buf.getvalue()

    def test_voice_behavioral_text_mode_smoke(self):
        out = self._run_cli(
            ["mock", "voice", "--kind", "behavioral"],
            ["On my team we owned the launch.", "We shipped and increased revenue 20%.",
             "I learned to set context earlier.", "EOF"])
        self.assertIn("Text mode", out)
        self.assertIn("Point coverage", out)
        self.assertIn("Session report", out)
        saved = list((self.tmp / "mock_sessions").glob("*.json"))
        self.assertEqual(len(saved), 1)
        report = json.loads(saved[0].read_text())
        self.assertEqual(report["track"], "voice_behavioral")
        self.assertEqual(report["outcome"], "completed")

    def test_voice_design_text_mode(self):
        out = self._run_cli(
            ["mock", "voice", "--kind", "design", "--level", "mid"],
            ["Requirements: shorten and redirect URLs.", "Use base62 counter for IDs.",
             "Cache hot URLs.", "EOF"])
        self.assertIn("Point coverage", out)

    def test_voice_coding_text_mode(self):
        out = self._run_cli(
            ["mock", "voice", "--kind", "coding", "--problem", "two-sum"],
            ["Use a hash map for O(n) time and O(n) space complexity.", "EOF"])
        self.assertIn("Point coverage", out)
        saved = list((self.tmp / "mock_sessions").glob("*voice_coding*.json"))
        self.assertEqual(len(saved), 1)

    def test_unavailable_stt_backend_still_runs_in_text_mode(self):
        if V.VoskSTT.is_available():
            self.skipTest("vosk unexpectedly installed")
        out = self._run_cli(
            ["mock", "voice", "--kind", "behavioral", "--stt-backend", "vosk"],
            ["On my team we shipped the project.", "EOF"])
        self.assertIn("not available", out)
        self.assertIn("typed input", out)
        self.assertIn("Point coverage", out)

    def test_unknown_kind_errors_cleanly(self):
        err = io.StringIO()
        with mock.patch.object(V, "find_tts", return_value=None):
            with self.assertRaises(SystemExit):
                with redirect_stdout(io.StringIO()), \
                     mock.patch("sys.stderr", err):
                    CLI.main(["mock", "voice", "--kind", "singing"])
        # expected errors end with the exact next command, no traceback
        self.assertIn("python -m candid mock --help", err.getvalue())

    def test_unknown_stt_backend_errors_cleanly(self):
        err = io.StringIO()
        with mock.patch.object(V, "find_tts", return_value=None):
            with self.assertRaises(SystemExit):
                with redirect_stdout(io.StringIO()), \
                     mock.patch("sys.stderr", err):
                    CLI.main(["mock", "voice", "--stt-backend", "carrier-pigeon"])
        self.assertIn("python -m candid mock voice --help", err.getvalue())


if __name__ == "__main__":
    unittest.main()

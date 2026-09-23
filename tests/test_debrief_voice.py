"""Tests for the voice debrief session engine (worker A).

Covers: session flow with a fake voice_io stub, adaptive follow-ups,
transcript file format, CLI wiring, and graceful behavior when optional
deps (voice_io, worker C's store/extraction modules) are missing.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# unique data dir for this suite (read at config import time)
_TD = tempfile.mkdtemp(prefix="candid-test-debrief-voice-")
os.environ["CANDID_DATA_DIR"] = _TD

from candid import debrief_voice as V  # noqa: E402
from candid import tracker as T  # noqa: E402


class FakeVoiceIO:
    """Stub for worker B's voice_io: records prompts, replays answers."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.spoken = []

    def speak(self, text):
        self.spoken.append(text)

    def listen(self, prompt_text=""):
        self.spoken.append(prompt_text)
        return self.answers.pop(0) if self.answers else ""


class TypedStub:
    """Fake typed input: feeds lines into input() prompts."""

    def __init__(self, lines):
        self.lines = list(lines)

    def __call__(self, _prompt=""):
        if not self.lines:
            raise EOFError
        return self.lines.pop(0)


class SessionFlowTest(unittest.TestCase):
    def _answers(self):
        return [
            "Phone screen with the hiring manager, 30 minutes.",
            "They asked about my ML experience and a SQL question about window functions.",
            "I was stumped on the window function partitioning question.",
            "The ML design discussion went well.",
            "Recruiter will get back in 3 days; I'll send a thank-you email.",
            "Remember to practice SQL window functions.",
        ]

    def test_full_session_with_fake_voice_io(self):
        io = FakeVoiceIO(self._answers())
        sess = V.DebriefSession.start_session(1, "Acme", "Data Scientist", voice_io=io)
        result = sess.run()

        # every base prompt was spoken
        self.assertGreaterEqual(len(io.spoken), len(sess.turns))
        self.assertEqual(result["num_turns"], len(sess.turns))
        self.assertGreaterEqual(len(sess.turns), 6)  # 6 base prompts

        # transcript file exists and has the expected format
        path = Path(result["transcript_path"])
        self.assertTrue(path.exists())
        data = json.loads(path.read_text())
        self.assertEqual(data["company"], "Acme")
        self.assertEqual(data["role"], "Data Scientist")
        self.assertEqual(data["app_id"], 1)
        self.assertIn("started_at", data)
        self.assertIn("ended_at", data)
        self.assertEqual(data["mode"], "voice")
        for t in data["turns"]:
            self.assertIn("n", t)
            self.assertIn("prompt_id", t)
            self.assertIn("prompt", t)
            self.assertIn("answer", t)
            self.assertIn("answered_at", t)
        # turns are sequential
        self.assertEqual([t["n"] for t in data["turns"]],
                         list(range(1, len(data["turns"]) + 1)))
        # summary embedded
        self.assertEqual(data["summary"]["app_id"], 1)
        self.assertIn("window function", data["summary"]["asked_about"])

    def test_adaptive_follow_up_on_stumped_answer(self):
        answers = [
            "Phone screen, 30 min.",
            "Mostly resume chat.",
            "I got stuck on the binary search follow-up, totally blanked.",
            "nothing else",  # follow-up answer
            "Behavioral questions went well.",
            "Wait for the recruiter.",
            "No more.",
        ]
        io = FakeVoiceIO(answers)
        sess = V.DebriefSession.start_session(None, "Beta", "SWE", voice_io=io)
        sess.run()
        follow_ups = [t for t in sess.turns if t["prompt_id"] == "stumped:followup"]
        self.assertEqual(len(follow_ups), 1)
        self.assertIn("specifically", follow_ups[0]["prompt"].lower())
        self.assertEqual(follow_ups[0]["answer"], "nothing else")

    def test_no_follow_up_without_trigger(self):
        io = FakeVoiceIO(["ok"] * 6)
        sess = V.DebriefSession.start_session(None, "Gamma", "ML", voice_io=io)
        sess.run()
        self.assertEqual(len(sess.turns), 6)
        self.assertFalse(any("followup" in t["prompt_id"] for t in sess.turns))

    def test_early_done_ends_session(self):
        io = FakeVoiceIO(["done"])
        sess = V.DebriefSession.start_session(None, "", "", voice_io=io)
        sess.run()
        self.assertEqual(len(sess.turns), 0)

    def test_typed_fallback_records_typed_mode(self):
        lines = [
            "Phone screen.", "",  # blank line finishes the answer
            "done",
        ]
        sess = V.DebriefSession.start_session(
            None, "Delta", "PM", force_typed=True, input_fn=TypedStub(lines))
        result = sess.run()
        self.assertEqual(result["num_turns"], 1)
        data = json.loads(Path(result["transcript_path"]).read_text())
        self.assertEqual(data["mode"], "typed")
        self.assertEqual(data["turns"][0]["answer"], "Phone screen.")


class OptionalDepsTest(unittest.TestCase):
    def test_voice_io_lazy_load_exposes_contract(self):
        # worker B's module is present; the engine loads it lazily and
        # speak/listen follow the prompt-based contract
        io = V.load_voice_io()
        self.assertIsNotNone(io)
        self.assertTrue(callable(io.speak) and callable(io.listen))
        self.assertTrue(V._listen_accepts_prompt(io.listen))

    def test_register_and_extract_with_worker_c(self):
        # worker C's store + extraction modules are present and integrated
        io = FakeVoiceIO([
            "Phone screen, 30 minutes.",
            "SQL window functions and a system design chat.",
            "The partitioning follow-up stumped me.",
            "The design chat went well.",
            "Recruiter follows up Friday; send a thank-you email.",
            "Practice SQL.",
        ])
        sess = V.DebriefSession.start_session(11, "Acme", "DS", voice_io=io)
        sess.run()
        extraction = sess.extract()
        self.assertIsInstance(extraction, dict)
        self.assertIn("weak_spots", extraction)
        self.assertTrue(sess.register(extraction))
        from candid import debrief as D
        stored = D.list_debriefs(app_id=11)
        self.assertTrue(any(d["transcript_path"].endswith(sess.debrief_id + ".json")
                            for d in stored))

    def test_register_and_extract_still_graceful_without_modules(self):
        # modules may be absent in other workers' checkouts: defensive paths
        import sys
        import candid as pkg
        hidden_modules, hidden_attrs = {}, {}
        for name in ("debrief", "debrief_extract"):
            full = "candid." + name
            hidden_modules[full] = sys.modules.pop(full, None)
            sys.modules[full] = None  # force ImportError on `from candid import X`
            if hasattr(pkg, name):
                hidden_attrs[name] = getattr(pkg, name)
                delattr(pkg, name)
        try:
            io = FakeVoiceIO(["ok"] * 6)
            sess = V.DebriefSession.start_session(None, "Acme", "DS", voice_io=io)
            self.assertEqual(sess.extract(), {})
            self.assertEqual(sess.register(), False)
        finally:
            for full, mod in hidden_modules.items():
                if mod is None:
                    sys.modules.pop(full, None)
                else:
                    sys.modules[full] = mod
            for name, attr in hidden_attrs.items():
                setattr(pkg, name, attr)

    def test_voice_failure_falls_back_to_typed(self):
        class BadIO:
            def speak(self, text):
                raise RuntimeError("mic exploded")

            def listen(self):
                raise RuntimeError("mic exploded")

        sess = V.DebriefSession.start_session(
            None, "Acme", "DS", voice_io=BadIO(),
            input_fn=TypedStub(["typed answer here", "", "done"]))
        result = sess.run()
        self.assertEqual(result["num_turns"], 1)
        self.assertEqual(sess.turns[0]["answer"], "typed answer here")


class PersistenceTest(unittest.TestCase):
    def test_list_and_load(self):
        io = FakeVoiceIO(["a"] * 6)
        sess = V.DebriefSession.start_session(7, "Acme", "DS", voice_io=io)
        sess.run()
        entries = V.list_transcripts(app_id=7)
        self.assertTrue(any(e["id"] == sess.debrief_id for e in entries))
        loaded = V.load_transcript(sess.debrief_id)
        self.assertEqual(loaded["company"], "Acme")

    def test_load_unknown_id_raises_friendly_error(self):
        with self.assertRaises(V.DebriefError):
            V.load_transcript("deb-nope-0000")

    def test_export_md_and_txt(self):
        io = FakeVoiceIO(["a"] * 6)
        sess = V.DebriefSession.start_session(None, "Acme", "DS", voice_io=io)
        result = sess.run()
        data = V.load_transcript(result["id"])
        md = V.export_transcript(data, "md")
        txt = V.export_transcript(data, "txt")
        self.assertTrue(md.suffix == ".md" and md.exists())
        self.assertTrue(txt.suffix == ".txt" and txt.exists())
        content = md.read_text()
        self.assertIn("Interview debrief", content)
        with self.assertRaises(V.DebriefError):
            V.export_transcript(data, "pdf")


class CliWiringTest(unittest.TestCase):
    def _parser(self):
        from candid.__main__ import build_parser
        return build_parser()

    def test_start_parses(self):
        a = self._parser().parse_args(["debrief", "start", "--app", "1", "--typed"])
        self.assertEqual(a.func.__name__, "cmd_debrief")
        self.assertEqual(a.what, "start")
        self.assertEqual(a.app, 1)
        self.assertTrue(a.typed)

    def test_show_list_export_parse(self):
        p = self._parser()
        a = p.parse_args(["debrief", "show", "deb-123"])
        self.assertEqual((a.what, a.debrief_id), ("show", "deb-123"))
        a = p.parse_args(["debrief", "list"])
        self.assertEqual(a.what, "list")
        a = p.parse_args(["debrief", "list", "--app", "2"])
        self.assertEqual(a.app, 2)
        a = p.parse_args(["debrief", "export", "deb-123", "--format", "txt"])
        self.assertEqual((a.what, a.format), ("export", "txt"))

    def test_debrief_in_command_inventory(self):
        from candid import __main__ as M
        self.assertIn("debrief", M.COMMANDS)
        self.assertEqual(M.SUBCOMMANDS["debrief"],
                         ["start", "show", "list", "export", "due"])
        self.assertIn("DebriefError", M._EXPECTED_ERRORS)

    def test_list_runs_end_to_end(self):
        from candid import __main__ as M
        io = FakeVoiceIO(["a"] * 6)
        V.DebriefSession.start_session(None, "Zeta", "Analyst", voice_io=io).run()
        a = self._parser().parse_args(["debrief", "list"])
        M.cmd_debrief(a)  # should not raise

    def test_start_with_fake_tracker(self):
        # the task's smoke scenario: --app resolves company/role from the tracker
        T.add("SmokeCo", "Smoke Engineer", path=None)
        rec = next(x for x in T.list_apps() if x["company"] == "SmokeCo")
        app_id, company, role = V.resolve_company_role(rec["id"], "", "")
        self.assertEqual((company, role), ("SmokeCo", "Smoke Engineer"))
        with self.assertRaises(V.DebriefError):
            V.resolve_company_role(999999, "", "")


if __name__ == "__main__":
    unittest.main()

"""Coordinator-level CLI smoke tests for `candid draft`.

Runs the real argparse entrypoint with an isolated data dir.
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402
from candid import tracker as TR  # noqa: E402


def run_cli(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        CLI.main(list(argv))
    return buf.getvalue()


class DraftCLITest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-draft-cli-"))
        self._saved = {n: getattr(C, n) for n in ("TRACKER_PATH", "DATA_DIR")}
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.DATA_DIR = self.tmp
        C.ensure_data_dirs()
        TR.add("Acme", "Data Scientist", status="applied",
               notes="Phone screen with Jane Doe")
        # backdate so the app is stale (fresh apps are skipped by design)
        from datetime import date, timedelta
        old = (date.today() - timedelta(days=30)).isoformat()
        apps = json.loads(C.TRACKER_PATH.read_text())
        for rec in apps:
            rec["date_added"] = old
            rec["date_updated"] = old
        C.TRACKER_PATH.write_text(json.dumps(apps))

    def tearDown(self):
        for n, v in self._saved.items():
            setattr(C, n, v)

    def test_draft_registered(self):
        self.assertIn("draft", CLI.COMMANDS)
        self.assertIn("generate", CLI.SUBCOMMANDS["draft"])

    def test_context_json(self):
        out = run_cli("draft", "context", "--company", "Acme")
        pkt = json.loads(out)
        self.assertEqual(pkt["company"], "Acme")
        self.assertTrue(pkt["found"])

    def test_thread_bullets(self):
        out = run_cli("draft", "thread", "--company", "Acme")
        self.assertIn("Thread history", out)
        self.assertIn("Acme", out)

    def test_generate(self):
        out = run_cli("draft", "generate", "--kind", "check_in",
                      "--company", "Acme", "--contact-name", "Jane")
        self.assertIn("Subject:", out)
        self.assertIn("Acme", out)

    def test_generate_with_hygiene(self):
        out = run_cli("draft", "generate", "--kind", "thank_you",
                      "--company", "Acme", "--check")
        self.assertIn("Subject:", out)

    def test_ladder(self):
        out = run_cli("draft", "ladder", "--company", "Acme")
        self.assertIn("Rung", out)
        self.assertIn("Subject:", out)

    def test_followups_json(self):
        out = run_cli("draft", "followups")
        data = json.loads(out)
        self.assertIsInstance(data, list)
        self.assertTrue(any(d["company"] == "Acme" for d in data))

    def test_check_and_send_time(self):
        out = run_cli("draft", "check", "--subject", "Quick follow-up",
                      "--body", "Hi Jane,\n\nJust checking in.\n\nBest,\nAlex")
        self.assertTrue("Clean" in out or "warn" in out or "info" in out)
        out2 = run_cli("draft", "send-time")
        self.assertIn("Best window", out2)

    def test_revise(self):
        out = run_cli("draft", "revise", "--subject", "Hi",
                      "--body", "Hello Jane. I am writing to follow up on my application. Thank you.",
                      "--instruction", "make it shorter")
        self.assertIn("Subject:", out)

    def test_save_list_show_diff(self):
        out = run_cli("draft", "save", "--app-id", "1", "--kind", "check_in",
                      "--subject", "Following up", "--body", "Hi Jane, checking in.")
        self.assertIn("Saved draft", out)
        out2 = run_cli("draft", "list", "--app-id", "1")
        self.assertIn("check_in", out2)
        did = out2.split()[0]
        out3 = run_cli("draft", "show", "--draft-id", did)
        self.assertIn("Following up", out3)
        out4 = run_cli("draft", "save", "--app-id", "1", "--kind", "check_in",
                       "--subject", "Following up", "--body", "Hi Jane, checking in again.")
        did2 = out4.split()[2]
        out5 = run_cli("draft", "diff", "--a", did, "--b", did2)
        self.assertTrue("identical" in out5 or "+" in out5 or "-" in out5)

    def test_voice_learn(self):
        samples = self.tmp / "samples.json"
        samples.write_text(json.dumps([
            {"subject": "Thank you", "body": "Hi Jane,\n\nThanks for your time today.\n\nBest,\nAlex"},
            {"subject": "Follow-up", "body": "Hi Sam,\n\nGreat speaking with you.\n\nBest,\nAlex"},
        ]))
        out = run_cli("draft", "voice-learn", "--samples-file", str(samples))
        prof = json.loads(out)
        self.assertIn("greeting", prof)
        self.assertIn("signoff", prof)

    def test_unknown_company_context_still_valid(self):
        out = run_cli("draft", "context", "--company", "NoSuchCo")
        pkt = json.loads(out)
        self.assertFalse(pkt["found"])


if __name__ == "__main__":
    unittest.main()

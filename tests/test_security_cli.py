"""CLI-level tests for the security-engineer interview track.

Run: CANDID_DATA_DIR=/tmp/candid-test-batch96 python -m unittest discover -s tests
(also honored when set in-process below).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-batch96")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402

CANDID_DIR = ROOT / "candid"


def _mod(name: str) -> bool:
    return (CANDID_DIR / f"{name}.py").exists()


def _run(argv: list[str]) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        CLI.main(argv)
    return buf.getvalue()


class SecurityQuestionsCLITest(unittest.TestCase):
    @unittest.skipUnless(_mod("security_questions"),
                         "security_questions module missing")
    def test_questions_json(self):
        out = _run(["security", "questions", "--json"])
        data = json.loads(out)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        self.assertIn("q", data[0])
        self.assertIn("category", data[0])

    @unittest.skipUnless(_mod("security_questions"),
                         "security_questions module missing")
    def test_questions_category_filter(self):
        out = _run(["security", "questions", "--category", "appsec", "--json"])
        data = json.loads(out)
        self.assertGreater(len(data), 0)
        self.assertTrue(all(q["category"] == "appsec" for q in data))

    @unittest.skipUnless(_mod("security_questions"),
                         "security_questions module missing")
    def test_questions_search(self):
        out = _run(["security", "questions", "--search", "ssrf"])
        self.assertIn("ssrf", out.lower())


class SecurityConceptsCLITest(unittest.TestCase):
    @unittest.skipUnless(_mod("security_concepts"),
                         "security_concepts module missing")
    def test_concepts_list(self):
        out = _run(["security", "concepts", "--list"])
        self.assertIn("owasp-top-10", out)

    @unittest.skipUnless(_mod("security_concepts"),
                         "security_concepts module missing")
    def test_concepts_show(self):
        out = _run(["security", "concepts", "owasp-top-10"])
        self.assertIn("OWASP", out)


class SecurityIncidentsCLITest(unittest.TestCase):
    @unittest.skipUnless(_mod("security_incidents"),
                         "security_incidents module missing")
    def test_incidents_list(self):
        out = _run(["security", "incidents", "--list"])
        self.assertIn("capital-one-2019", out)

    @unittest.skipUnless(_mod("security_incidents"),
                         "security_incidents module missing")
    def test_incidents_search(self):
        out = _run(["security", "incidents", "--search", "ransomware"])
        self.assertIn("moveit-2023", out)


class SecurityLoopCLITest(unittest.TestCase):
    @unittest.skipUnless(_mod("security_loop"), "security_loop module missing")
    def test_loop_list(self):
        out = _run(["security", "loop", "--list"])
        self.assertIn("startup", out)
        self.assertIn("bigtech", out)

    @unittest.skipUnless(_mod("security_loop"), "security_loop module missing")
    def test_loop_show(self):
        out = _run(["security", "loop", "startup"])
        self.assertIn("Startup", out)


class PrepTrackFlagTest(unittest.TestCase):
    def test_prep_help_shows_track(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                CLI.main(["prep", "--help"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("--track", buf.getvalue())


if __name__ == "__main__":
    unittest.main()

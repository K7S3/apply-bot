"""Tests for the pre-interview ritual modules: warmup drill + tech checklist.

Run: CANDID_DATA_DIR=<tmp> python -m unittest discover -s tests
(The env var is set in-process below, before any candid import.)
"""
import contextlib
import io
import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path

_TD = tempfile.mkdtemp(prefix="candid-ritual-test-")
os.environ["CANDID_DATA_DIR"] = _TD

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import ritual_techcheck as T  # noqa: E402
from candid import ritual_warmup as W  # noqa: E402


class _HermeticDataDir(unittest.TestCase):
    """Point CANDID_DATA_DIR at this module's temp dir for every test.

    Sibling test modules assign the same env var at import time; without a
    per-test reset, whichever module is imported last wins and the modules
    under test (which resolve the data dir at call time) write summaries
    into the wrong temp dir.
    """

    def setUp(self):
        self._old_candid_data_dir = os.environ.get("CANDID_DATA_DIR")
        os.environ["CANDID_DATA_DIR"] = _TD

    def tearDown(self):
        old = getattr(self, "_old_candid_data_dir", None)
        if old is None:
            os.environ.pop("CANDID_DATA_DIR", None)
        else:
            os.environ["CANDID_DATA_DIR"] = old


def _inputs(*values):
    it = iter(values)

    def _fn(prompt=""):
        try:
            return next(it)
        except StopIteration:
            return ""

    return _fn


class _FakeClock:
    def __init__(self, step_s=30.0):
        self.t = 1000.0
        self.step = step_s

    def __call__(self):
        self.t += self.step
        return self.t


def _run_warmup_quiet(minutes=15, seed=42, inputs=(), **kw):
    buf = io.StringIO()
    kw.setdefault("no_wait", True)
    kw.setdefault("clock", _FakeClock())
    with contextlib.redirect_stdout(buf):
        summary = W.run_warmup(minutes=minutes, seed=seed,
                               input_fn=_inputs(*inputs), **kw)
    return summary


# full input script: approach, behavioral answer, rating, flashcard reveal, recalled?
FULL_INPUTS = ("a hash map approach", "I debugged a prod issue once",
               "4", "", "y")


class WarmupBudgetsTest(_HermeticDataDir):
    def test_budgets_sum_to_minutes(self):
        for minutes in (3, 5, 10, 15, 30, 60):
            b = W._split_budgets(minutes)
            self.assertEqual(sum(b.values()), minutes,
                             f"budgets {b} do not sum to {minutes}")

    def test_summary_budgets_sum_to_minutes(self):
        s = _run_warmup_quiet(minutes=15, seed=7, inputs=FULL_INPUTS)
        self.assertEqual(sum(s["budgets_min"].values()), 15)

    def test_invalid_minutes_rejected(self):
        for bad in (0, -3, "15", 2.5):
            with self.assertRaises(ValueError):
                _run_warmup_quiet(minutes=bad, inputs=FULL_INPUTS)


class WarmupFlowTest(_HermeticDataDir):
    def test_mock_bank_used_when_available(self):
        if not W._HAS_MOCK:
            self.skipTest("candid.mock not importable here")
        s = _run_warmup_quiet(minutes=15, seed=42, inputs=FULL_INPUTS)
        self.assertEqual(s["coding"]["problem_source"], "mock_bank")
        self.assertEqual(s["minutes"], 15)
        self.assertEqual(s["seed"], 42)

    def test_builtin_fallback_when_mock_unavailable(self):
        orig = W._HAS_MOCK
        W._HAS_MOCK = False
        try:
            s = _run_warmup_quiet(minutes=15, seed=1, inputs=FULL_INPUTS)
        finally:
            W._HAS_MOCK = orig
        self.assertEqual(s["coding"]["problem_source"], "builtin")
        self.assertIn(s["coding"]["problem_id"],
                      {p["id"] for p in W._BUILTIN_PROBLEMS})

    def test_seed_is_deterministic(self):
        kw = dict(minutes=15, inputs=FULL_INPUTS)
        a = _run_warmup_quiet(seed=123, **kw)
        b = _run_warmup_quiet(seed=123, **kw)
        for key in ("coding", "behavioral", "flashcard"):
            self.assertEqual(a[key]["problem_id"] if key == "coding" else a[key].get("question", a[key].get("term")),
                             b[key]["problem_id"] if key == "coding" else b[key].get("question", b[key].get("term")))

    def test_rating_validation_retries(self):
        inputs = ("approach", "an answer", "9", "0", "abc", "4", "", "n")
        s = _run_warmup_quiet(minutes=5, seed=3, inputs=inputs)
        self.assertEqual(s["behavioral"]["self_rating"], 4)
        self.assertFalse(s["flashcard"]["recalled"])

    def test_rating_skip_gives_none(self):
        inputs = ("approach", "an answer", "skip", "", "y")
        s = _run_warmup_quiet(minutes=5, seed=3, inputs=inputs)
        self.assertIsNone(s["behavioral"]["self_rating"])

    def test_summary_json_saved_under_data_dir(self):
        s = _run_warmup_quiet(minutes=5, seed=9, inputs=FULL_INPUTS)
        path = Path(s["saved_to"])
        self.assertTrue(path.is_file())
        self.assertEqual(path.parent.parent.name, "rituals")
        self.assertEqual(path.parent.name, "warmups")
        self.assertTrue(str(path).startswith(_TD))
        loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(loaded["seed"], 9)
        for key in ("timestamp", "minutes", "budgets_min", "coding",
                    "behavioral", "flashcard"):
            self.assertIn(key, loaded)

    def test_no_network_use(self):
        orig_sock = socket.socket
        orig_create = socket.create_connection

        def _boom(*a, **k):
            raise AssertionError("warmup must not touch the network")

        socket.socket = _boom
        socket.create_connection = _boom
        try:
            s = _run_warmup_quiet(minutes=5, seed=11, inputs=FULL_INPUTS)
        finally:
            socket.socket = orig_sock
            socket.create_connection = orig_create
        self.assertEqual(s["minutes"], 5)


class TechcheckTest(_HermeticDataDir):
    def _names(self, items):
        return [n for n, _, _ in items]

    def test_virtual_checklist(self):
        items = T.run_techcheck("virtual", check_network=False)
        self.assertTrue(all(len(i) == 3 for i in items))
        self.assertTrue(all(s in ("pass", "warn", "info") for _, s, _ in items))
        names = self._names(items)
        for expected in ("Python version", "Core libraries", "Disk space",
                         "Network reachability", "Meeting link ready",
                         "Camera and mic", "Quiet room"):
            self.assertIn(expected, names)

    def test_coding_checklist(self):
        items = T.run_techcheck("coding", check_network=False)
        names = self._names(items)
        for expected in ("IDE ready", "Language runtime",
                         "Coding platform login", "Second monitor"):
            self.assertIn(expected, names)

    def test_phone_checklist(self):
        items = T.run_techcheck("phone", check_network=False)
        names = self._names(items)
        for expected in ("Phone charged", "Do Not Disturb",
                         "Caller number confirmed", "Notes at hand"):
            self.assertIn(expected, names)

    def test_invalid_round_type(self):
        with self.assertRaises(ValueError):
            T.run_techcheck("onsite")
        with self.assertRaises(ValueError):
            T.run_techcheck("")

    def test_network_probe_skipped(self):
        orig = socket.create_connection

        def _boom(*a, **k):
            raise AssertionError("probe should be skipped")

        socket.create_connection = _boom
        try:
            items = T.run_techcheck("virtual", check_network=False)
        finally:
            socket.create_connection = orig
        net = [i for i in items if i[0] == "Network reachability"]
        self.assertEqual(len(net), 1)
        self.assertEqual(net[0][1], "info")

    def test_network_failure_is_advisory(self):
        orig = socket.create_connection

        def _fail(*a, **k):
            raise OSError("simulated offline")

        socket.create_connection = _fail
        try:
            items = T.run_techcheck("coding", check_network=True)
        finally:
            socket.create_connection = orig
        net = [i for i in items if i[0] == "Network reachability"]
        self.assertEqual(net[0][1], "warn")

    def test_core_checks_pass_on_healthy_env(self):
        items = T.run_techcheck("phone", check_network=False)
        by_name = {n: (s, note) for n, s, note in items}
        self.assertEqual(by_name["Python version"][0], "pass")
        self.assertEqual(by_name["Core libraries"][0], "pass")
        # disk threshold is advisory; small test filesystems may warn honestly
        self.assertIn(by_name["Disk space"][0], ("pass", "warn"))
        self.assertIn("GB free", by_name["Disk space"][1])

    def test_cli_main_smoke(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = T.main(["--round-type", "phone", "--no-net"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("[PASS] Python version", out)
        self.assertIn("Phone charged", out)


if __name__ == "__main__":
    unittest.main()

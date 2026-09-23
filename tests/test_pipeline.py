"""Tests for the pipeline workstream: ghosting detector + networking CRM.

Covers: ghosts.py (quiet-window boundary 20 vs 21 vs 22 days, terminal
states never flagged, custom --days, unparseable dates skipped,
next-action suggestions), network.py (add/list/thanks/mark-thanked,
thank-you draft hook via followup.thank_you), and CLI smoke tests for
`track ghosts` and the `network` commands.

Data paths are redirected into a temp dir by monkeypatching candid.config
attributes (same approach as tests/test_cli_ux.py).
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402
from candid import ghosts as G  # noqa: E402
from candid import network as N  # noqa: E402
from candid import tracker as T  # noqa: E402

TODAY = date(2026, 9, 22)


def _rec(app_id, company, status, days_ago):
    return {
        "id": app_id,
        "company": company,
        "role": "Data Scientist",
        "jd_link": "",
        "status": status,
        "notes": "",
        "date_added": (TODAY - timedelta(days=days_ago + 5)).isoformat(),
        "date_updated": (TODAY - timedelta(days=days_ago)).isoformat(),
        "prep_pack": "",
    }


# ---------------------------------------------------------------------------
# ghosts: find_ghosts
# ---------------------------------------------------------------------------

class GhostsLibTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-ghosts-"))
        self.tracker = self.tmp / "tracker.json"

    def _seed(self, records):
        self.tracker.write_text(json.dumps(records))
        return self.tracker

    def test_boundary_20_21_22_days(self):
        self._seed([
            _rec(1, "AlphaCo", "applied", 20),
            _rec(2, "BetaCo", "applied", 21),
            _rec(3, "GammaCo", "applied", 22),
        ])
        ghosts = G.find_ghosts(days=21, today=TODAY, path=self.tracker)
        self.assertEqual({g["id"] for g in ghosts}, {2, 3})
        self.assertEqual(ghosts[0]["id"], 3)  # stalest first
        self.assertEqual(ghosts[0]["stale_days"], 22)
        self.assertEqual(ghosts[1]["stale_days"], 21)

    def test_terminal_states_never_flagged(self):
        self._seed([
            _rec(1, "AlphaCo", "offer", 60),
            _rec(2, "BetaCo", "rejected", 60),
            _rec(3, "GammaCo", "withdrawn", 60),
            _rec(4, "DeltaCo", "archived", 60),
            _rec(5, "EpsilonCo", "selected_for_interview", 60),
        ])
        ghosts = G.find_ghosts(days=21, today=TODAY, path=self.tracker)
        self.assertEqual([g["id"] for g in ghosts], [5])

    def test_custom_days(self):
        self._seed([_rec(1, "AlphaCo", "applied", 15)])
        self.assertEqual(len(G.find_ghosts(days=10, today=TODAY, path=self.tracker)), 1)
        self.assertEqual(len(G.find_ghosts(days=30, today=TODAY, path=self.tracker)), 0)

    def test_unparseable_date_skipped_not_flagged(self):
        rec = _rec(1, "AlphaCo", "applied", 99)
        rec["date_updated"] = "not-a-date"
        self._seed([rec])
        self.assertEqual(G.find_ghosts(days=21, today=TODAY, path=self.tracker), [])

    def test_invalid_days_raises(self):
        self._seed([_rec(1, "AlphaCo", "applied", 99)])
        with self.assertRaises(G.GhostError):
            G.find_ghosts(days=0, today=TODAY, path=self.tracker)

    def test_next_actions_suggest_checkin_and_archive(self):
        rec = _rec(7, "Acme", "applied", 30)
        acts = G.next_actions(rec)
        joined = " ".join(acts)
        self.assertIn("followup check-in", joined)
        self.assertIn("track update 7 --status archived", joined)

    def test_render_ghosts_empty(self):
        out = G.render_ghosts([], days=21)
        self.assertIn("No ghosted", out)

    def test_render_ghosts_shows_stale_days(self):
        rec = {**_rec(1, "Acme", "applied", 30), "stale_days": 30}
        out = G.render_ghosts([rec], days=21)
        self.assertIn("quiet 30 days", out)
        self.assertIn("Acme", out)


# ---------------------------------------------------------------------------
# network: library
# ---------------------------------------------------------------------------

class NetworkLibTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-network-"))
        self.path = self.tmp / "network.json"

    def test_add_and_list(self):
        rec = N.add("coffee-chat", "Jane Doe", company="Acme",
                    role="Data Scientist", notes="met at meetup", path=self.path)
        self.assertEqual(rec["id"], 1)
        self.assertFalse(rec["thanked"])
        self.assertEqual(rec["contact"], "Jane Doe")
        contacts = N.list_contacts(path=self.path)
        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0]["type"], "coffee-chat")

    def test_add_bad_type_and_missing_contact(self):
        with self.assertRaises(N.NetworkError):
            N.add("pen-pal", "Jane Doe", path=self.path)
        with self.assertRaises(N.NetworkError):
            N.add("coffee-chat", "", path=self.path)

    def test_list_filter_by_type(self):
        N.add("coffee-chat", "Jane Doe", path=self.path)
        N.add("referral-given", "Sam Lee", path=self.path)
        self.assertEqual(len(N.list_contacts(type_="coffee-chat", path=self.path)), 1)
        self.assertEqual(len(N.list_contacts(type_="referral-given", path=self.path)), 1)
        with self.assertRaises(N.NetworkError):
            N.list_contacts(type_="pen-pal", path=self.path)

    def test_thanks_owed_and_mark_thanked(self):
        N.add("coffee-chat", "Jane Doe", company="Acme", path=self.path)        # owed
        N.add("referral-received", "Sam Lee", company="Globex", path=self.path)  # owed
        N.add("referral-given", "Alex Rivera", company="Initech", path=self.path)  # not owed
        owed = N.thanks_owed(path=self.path)
        self.assertEqual({c["contact"] for c in owed}, {"Jane Doe", "Sam Lee"})
        N.mark_thanked(1, path=self.path)
        owed = N.thanks_owed(path=self.path)
        self.assertEqual([c["contact"] for c in owed], ["Sam Lee"])
        rec = next(c for c in N.list_contacts(path=self.path) if c["id"] == 1)
        self.assertTrue(rec["thanked"])
        with self.assertRaises(N.NetworkError):
            N.mark_thanked(999, path=self.path)

    def test_draft_command_and_draft(self):
        rec = N.add("referral-received", "Sam Lee", company="Globex",
                    role="Backend Engineer", notes="referred me", path=self.path)
        cmd = N.draft_command(rec)
        self.assertIn("followup thank-you", cmd)
        self.assertIn("Sam Lee", cmd)
        draft = N.thank_you_draft(rec["id"], "Alex Rivera", path=self.path)
        self.assertIn("Sam Lee", draft)
        self.assertIn("Globex", draft)
        self.assertIn("Subject:", draft)

    def test_render_thanks_empty_and_populated(self):
        self.assertIn("all caught up", N.render_thanks([]))
        rec = N.add("coffee-chat", "Jane Doe", company="Acme", path=self.path)
        out = N.render_thanks(N.thanks_owed(path=self.path))
        self.assertIn("Jane Doe", out)
        self.assertIn("mark-thanked", out)

    def test_storage_is_plain_json(self):
        N.add("coffee-chat", "Jane Doe", path=self.path)
        data = json.loads(self.path.read_text())
        self.assertIsInstance(data, list)
        self.assertEqual(data[0]["type"], "coffee-chat")


# ---------------------------------------------------------------------------
# CLI smoke tests (in-process, config paths monkeypatched)
# ---------------------------------------------------------------------------

class PipelineCLITest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-pipeline-"))
        self._saved = {}
        for name in ("TRACKER_PATH", "PROFILE_PATH", "PREP_PACKS_DIR",
                     "TAILOR_DIR", "SALARY_DB", "OFFERS_PATH",
                     "GMAIL_PROPOSALS_PATH", "DATA_DIR", "NETWORK_PATH"):
            self._saved[name] = getattr(C, name)
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.PROFILE_PATH = self.tmp / "profile.json"
        C.PREP_PACKS_DIR = self.tmp / "prep_packs"
        C.TAILOR_DIR = self.tmp / "tailor"
        C.SALARY_DB = self.tmp / "salary.sqlite"
        C.OFFERS_PATH = self.tmp / "offers.json"
        C.GMAIL_PROPOSALS_PATH = self.tmp / "gmail_proposals.json"
        C.NETWORK_PATH = self.tmp / "network.json"
        C.DATA_DIR = self.tmp
        C.ensure_data_dirs()
        C.PROFILE_PATH.write_text(json.dumps({"name": "Alex Rivera"}))

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                CLI.main(argv)
            except SystemExit as e:
                code = e.code
                return (code if isinstance(code, int) else 1,
                        out.getvalue(), err.getvalue())
            return 0, out.getvalue(), err.getvalue()

    # --- track ghosts -------------------------------------------------------
    def test_cli_track_ghosts_default_and_days(self):
        T.add("AlphaCo", "Data Scientist", status="applied")
        T.add("BetaCo", "Data Scientist", status="applied")
        apps = T._load()
        for a in apps:
            a["date_updated"] = "2026-08-01" if a["company"] == "AlphaCo" \
                else date.today().isoformat()
        T._save(apps)
        code, out, _ = self.run_cli(["track", "ghosts"])
        self.assertEqual(code, 0)
        self.assertIn("AlphaCo", out)
        self.assertNotIn("BetaCo", out)
        self.assertIn("followup check-in", out)
        self.assertIn("--status archived", out)

    def test_cli_track_ghosts_custom_days(self):
        T.add("AlphaCo", "Data Scientist", status="applied")
        apps = T._load()
        apps[0]["date_updated"] = (date.today() - timedelta(days=15)).isoformat()
        T._save(apps)
        code, out, _ = self.run_cli(["track", "ghosts", "--days", "10"])
        self.assertEqual(code, 0)
        self.assertIn("AlphaCo", out)
        code, out, _ = self.run_cli(["track", "ghosts", "--days", "30"])
        self.assertEqual(code, 0)
        self.assertIn("No ghosted", out)

    def test_cli_track_ghosts_bad_days_friendly_error(self):
        code, out, err = self.run_cli(["track", "ghosts", "--days", "0"])
        self.assertEqual(code, 1)
        self.assertIn("Next:", err)
        self.assertIn("track ghosts", err)
        self.assertNotIn("Traceback", err)

    def test_cli_ghosts_then_archive_flow(self):
        rec = T.add("AlphaCo", "Data Scientist", status="applied")
        apps = T._load()
        apps[0]["date_updated"] = "2026-08-01"
        T._save(apps)
        code, out, _ = self.run_cli(["track", "ghosts"])
        self.assertIn("AlphaCo", out)
        code, out, _ = self.run_cli(["track", "update", str(rec["id"]),
                                    "--status", "archived"])
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli(["track", "ghosts"])
        self.assertIn("No ghosted", out)

    # --- network ------------------------------------------------------------
    def test_cli_network_add_list_thanks_flow(self):
        code, out, _ = self.run_cli(
            ["network", "add", "--type", "coffee-chat",
             "--contact", "Jane Doe", "--company", "Acme"])
        self.assertEqual(code, 0)
        self.assertIn("Jane Doe", out)
        self.assertIn("network thanks", out)
        code, out, _ = self.run_cli(["network", "list"])
        self.assertEqual(code, 0)
        self.assertIn("Jane Doe", out)
        code, out, _ = self.run_cli(["network", "list", "--type", "coffee-chat"])
        self.assertEqual(code, 0)
        self.assertIn("Jane Doe", out)
        code, out, _ = self.run_cli(["network", "thanks"])
        self.assertEqual(code, 0)
        self.assertIn("Jane Doe", out)
        self.assertIn("followup thank-you", out)
        code, out, _ = self.run_cli(["network", "mark-thanked", "1"])
        self.assertEqual(code, 0)
        self.assertIn("thanked", out)
        code, out, _ = self.run_cli(["network", "thanks"])
        self.assertIn("all caught up", out)

    def test_cli_network_thanks_draft_uses_followup(self):
        self.run_cli(["network", "add", "--type", "referral-received",
                      "--contact", "Sam Lee", "--company", "Globex",
                      "--role", "Backend Engineer"])
        code, out, _ = self.run_cli(["network", "thanks", "--draft", "1"])
        self.assertEqual(code, 0)
        self.assertIn("Sam Lee", out)
        self.assertIn("Globex", out)
        self.assertIn("Alex Rivera", out)  # from profile name

    def test_cli_network_bad_type_friendly_error(self):
        code, out, err = self.run_cli(
            ["network", "add", "--type", "pen-pal", "--contact", "Jane Doe"])
        self.assertNotEqual(code, 0)  # argparse choice failure
        self.assertNotIn("Traceback", out + err)

    def test_cli_network_unknown_id_friendly_error(self):
        code, out, err = self.run_cli(["network", "mark-thanked", "42"])
        self.assertEqual(code, 1)
        self.assertIn("Next:", err)
        self.assertIn("python -m candid network --help", err)
        self.assertNotIn("Traceback", out + err)

    def test_cli_network_list_json(self):
        self.run_cli(["network", "add", "--type", "referral-given",
                      "--contact", "Alex Rivera", "--company", "Initech"])
        code, out, _ = self.run_cli(["network", "list", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data[0]["contact"], "Alex Rivera")


if __name__ == "__main__":
    unittest.main()

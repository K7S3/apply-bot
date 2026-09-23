"""Tests for candid warm-intro ranking (warm.py).

Run: CANDID_DATA_DIR=/tmp/candid-test-warm python3 -m pytest tests/test_warm.py -q
"""
import io
import os
import sys
import tempfile
import unittest
import zipfile
from datetime import date, timedelta
from pathlib import Path

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-warm"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import warm as W  # noqa: E402


def _make_zip(csv_text: str, name: str = "Connections.csv",
              bom: bool = True, extra_files: dict | None = None) -> Path:
    """Build a fake LinkedIn export ZIP in a temp dir."""
    td = tempfile.mkdtemp()
    zp = Path(td) / "export.zip"
    payload = ("﻿" if bom else "") + csv_text
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr(name, payload.encode("utf-8"))
        for fname, ftext in (extra_files or {}).items():
            zf.writestr(fname, ftext.encode("utf-8"))
    return zp


CONNECTIONS_CSV = (
    "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
    "Jane,Doe,https://linkedin.com/in/janedoe,jane@example.com,Acme Inc.,"
    "Engineering Manager,\"Mar 15, 2021\"\n"
    "Bob,Smith,https://linkedin.com/in/bobsmith,bob@example.com,ACME,"
    "Senior Software Engineer,\"2023-06-01\"\n"
    "\n"
    "Zoe,Lee,https://linkedin.com/in/zoelee,zoe@example.com,,,\n"
    "Rae,Khan,https://linkedin.com/in/raekhan,rae@example.com,Beta LLC,"
    "Technical Recruiter,garbage-date\n"
)


def _conn(**kw) -> dict:
    base = {"first_name": "Test", "last_name": "Person",
            "full_name": "Test Person", "company": "Acme", "position": "",
            "connected_on": None, "degree": 1}
    base.update(kw)
    return base


class LoadConnectionsTest(unittest.TestCase):
    def test_parses_connections(self):
        conns = W.load_connections(_make_zip(CONNECTIONS_CSV))
        self.assertEqual(len(conns), 4)
        jane = conns[0]
        self.assertEqual(jane["first_name"], "Jane")
        self.assertEqual(jane["last_name"], "Doe")
        self.assertEqual(jane["full_name"], "Jane Doe")
        self.assertEqual(jane["company"], "Acme Inc.")
        self.assertEqual(jane["position"], "Engineering Manager")
        self.assertEqual(jane["connected_on"], date(2021, 3, 15))
        self.assertEqual(jane["degree"], 1)

    def test_blank_rows_skipped(self):
        conns = W.load_connections(_make_zip(CONNECTIONS_CSV))
        self.assertTrue(all(c["full_name"] or c["company"] for c in conns))
        self.assertEqual(len(conns), 4)  # the empty line above is dropped

    def test_bad_date_gives_none(self):
        conns = W.load_connections(_make_zip(CONNECTIONS_CSV))
        rae = [c for c in conns if c["first_name"] == "Rae"][0]
        self.assertIsNone(rae["connected_on"])

    def test_email_addresses_never_imported(self):
        conns = W.load_connections(_make_zip(CONNECTIONS_CSV))
        for c in conns:
            for k, v in c.items():
                self.assertNotIn("email", k.lower(), f"email key leaked: {k}")
                if isinstance(v, str):
                    self.assertNotIn("@", v, f"email value leaked: {v}")

    def test_case_insensitive_columns(self):
        csv_text = ("first name,last name,company,position,connected on\n"
                    "Sam,Patel,Gamma,Engineer,2022-01-05\n")
        conns = W.load_connections(_make_zip(csv_text))
        self.assertEqual(len(conns), 1)
        self.assertEqual(conns[0]["full_name"], "Sam Patel")
        self.assertEqual(conns[0]["connected_on"], date(2022, 1, 5))

    def test_missing_columns_still_parses(self):
        csv_text = "First Name,Last Name\nSam,Patel\n"
        conns = W.load_connections(_make_zip(csv_text))
        self.assertEqual(conns[0]["full_name"], "Sam Patel")
        self.assertEqual(conns[0]["company"], "")
        self.assertIsNone(conns[0]["connected_on"])

    def test_missing_connections_csv(self):
        zp = _make_zip("a,b\n1,2\n", name="Profile.csv",
                       extra_files={})
        with self.assertRaises(W.WarmError):
            W.load_connections(zp)

    def test_not_a_zip(self):
        td = tempfile.mkdtemp()
        p = Path(td) / "nope.zip"
        p.write_text("hello")
        with self.assertRaises(W.WarmError):
            W.load_connections(p)

    def test_missing_file(self):
        with self.assertRaises(W.WarmError):
            W.load_connections("/nonexistent/export.zip")


class NormCompanyTest(unittest.TestCase):
    def test_variants(self):
        cases = {
            "Acme Inc.": "acme",
            "ACME LLC": "acme",
            "Acme  Corporation": "acme",
            "Foo GmbH": "foo",
            "Bar Ltd": "bar",
            "Baz Co": "baz",
            "Qux Incorporated": "qux",
            "  Spaced   Out  ": "spaced out",
            "Plain": "plain",
            "": "",
            None: "",
        }
        for raw, want in cases.items():
            self.assertEqual(W._norm_company(raw), want, raw)


class WarmthScoreTest(unittest.TestCase):
    def test_manager_beats_ic(self):
        mgr = _conn(position="Engineering Manager", connected_on=date(2020, 1, 1))
        ic = _conn(position="Software Engineer", connected_on=date(2020, 1, 1))
        self.assertGreater(W.warmth_score(mgr), W.warmth_score(ic))

    def test_recent_beats_ancient(self):
        today = date.today()
        recent = _conn(position="Software Engineer",
                       connected_on=today - timedelta(days=30))
        ancient = _conn(position="Software Engineer",
                        connected_on=today - timedelta(days=3000))
        self.assertGreater(W.warmth_score(recent), W.warmth_score(ancient))

    def test_unknown_date_is_neutral(self):
        today = date.today()
        unknown = _conn(position="Software Engineer", connected_on=None)
        ancient = _conn(position="Software Engineer",
                        connected_on=today - timedelta(days=3000))
        self.assertGreater(W.warmth_score(unknown), W.warmth_score(ancient))
        score = W.warmth_score(unknown)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_recruiter_scores_well(self):
        rec = _conn(position="Technical Recruiter", connected_on=date(2020, 1, 1))
        ic = _conn(position="Software Engineer", connected_on=date(2020, 1, 1))
        self.assertGreater(W.warmth_score(rec), W.warmth_score(ic))

    def test_bounds(self):
        for title in ["VP of Engineering", "Intern", "", "Chief Executive Officer"]:
            s = W.warmth_score(_conn(position=title, connected_on=date.today()))
            self.assertGreaterEqual(s, 0)
            self.assertLessEqual(s, 100)

    def test_deterministic(self):
        c = _conn(position="Director of Engineering",
                  connected_on=date(2021, 5, 5))
        self.assertEqual(W.warmth_score(c), W.warmth_score(c))


class ConnectionStrengthTest(unittest.TestCase):
    def test_empty_is_zero(self):
        self.assertEqual(W.connection_strength([]), 0.0)

    def test_single_equals_its_score(self):
        c = _conn(position="Director", connected_on=date.today())
        self.assertAlmostEqual(W.connection_strength([c]), W.warmth_score(c))

    def test_diminishing_returns(self):
        mk = lambda: _conn(position="Software Engineer",
                           connected_on=date(2022, 1, 1))
        one = W.connection_strength([mk()])
        two = W.connection_strength([mk(), mk()])
        three = W.connection_strength([mk(), mk(), mk()])
        self.assertGreater(two, one)
        self.assertGreater(three, two)
        # three connections add less than 3x the single-connection strength
        s = W.warmth_score(mk())
        self.assertLess(three, 3 * s)
        self.assertLessEqual(three, 100.0)

    def test_top_connection_counts_most(self):
        strong = _conn(position="VP Engineering", connected_on=date.today())
        weak = _conn(position="Intern", connected_on=date(2015, 1, 1))
        both = W.connection_strength([strong, weak])
        # adding a weak 2nd connection moves the needle only a little
        self.assertLess(both, W.connection_strength([strong]) + W.warmth_score(weak))
        self.assertGreater(both, W.connection_strength([strong]))


class IntroPathTest(unittest.TestCase):
    def test_format_with_date(self):
        c = _conn(first_name="Jane", last_name="Doe", full_name="Jane Doe",
                  company="Acme", position="Engineering Manager",
                  connected_on=date(2021, 3, 15))
        self.assertEqual(W.intro_path(c),
                         "You -> Jane Doe (Engineering Manager @ Acme, connected Mar 2021)")

    def test_format_without_date(self):
        c = _conn(first_name="Jane", full_name="Jane Doe",
                  company="Acme", position="Engineer")
        self.assertEqual(W.intro_path(c), "You -> Jane Doe (Engineer @ Acme)")

    def test_no_second_degree_implied(self):
        path = W.intro_path(_conn())
        self.assertTrue(path.startswith("You -> "))
        self.assertNotIn("2nd", path)


class InsiderMapTest(unittest.TestCase):
    def _conns(self):
        d = date(2022, 1, 1)
        return [
            _conn(first_name="A", full_name="A", company="Acme Inc.",
                  position="Engineering Manager", connected_on=d),
            _conn(first_name="B", full_name="B", company="ACME",
                  position="Technical Recruiter", connected_on=d),
            _conn(first_name="C", full_name="C", company="Acme LLC",
                  position="Software Engineer", connected_on=d),
            _conn(first_name="D", full_name="D", company="Acme",
                  position="Executive Assistant", connected_on=d),
            _conn(first_name="E", full_name="E", company="Other Corp",
                  position="Director", connected_on=d),
        ]

    def test_grouping(self):
        m = W.insider_map("Acme", self._conns())
        self.assertEqual({k: len(v) for k, v in m.items()},
                         {"hiring": 1, "recruiting": 1, "engineering": 1, "other": 1})
        self.assertEqual(m["hiring"][0]["first_name"], "A")
        self.assertEqual(m["recruiting"][0]["first_name"], "B")
        self.assertEqual(m["engineering"][0]["first_name"], "C")
        self.assertEqual(m["other"][0]["first_name"], "D")

    def test_sorted_by_warmth_desc(self):
        d = date(2022, 1, 1)
        conns = [
            _conn(first_name="Low", full_name="Low", company="Acme",
                  position="Software Engineer", connected_on=d),
            _conn(first_name="High", full_name="High", company="Acme",
                  position="Senior Software Engineer", connected_on=date.today()),
        ]
        m = W.insider_map("acme inc", conns)
        self.assertEqual([c["first_name"] for c in m["engineering"]],
                         ["High", "Low"])

    def test_company_matched_via_norm(self):
        m = W.insider_map("acme corporation", self._conns())
        self.assertEqual(sum(len(v) for v in m.values()), 4)


class RankJobsTest(unittest.TestCase):
    def _conns(self):
        d = date(2022, 1, 1)
        return [
            _conn(first_name="Jane", full_name="Jane Doe", company="Acme Inc.",
                  position="Engineering Manager", connected_on=d),
            _conn(first_name="Bob", full_name="Bob Smith", company="Acme",
                  position="Software Engineer", connected_on=d),
        ]

    def test_job_with_connections_ranks_first(self):
        jobs = [
            {"title": "Data Scientist", "company": "Nobody Corp"},
            {"title": "ML Engineer", "company": "Acme LLC"},
        ]
        ranked = W.rank_jobs(jobs, self._conns())
        self.assertEqual(ranked[0]["job"]["title"], "ML Engineer")
        self.assertEqual(len(ranked[0]["connections"]), 2)
        self.assertEqual(ranked[1]["connections"], [])
        self.assertEqual(ranked[1]["strength"], 0.0)

    def test_company_matching_via_norm(self):
        jobs = [{"title": "ML Engineer", "company": "acme corporation"}]
        ranked = W.rank_jobs(jobs, self._conns())
        self.assertEqual(len(ranked[0]["connections"]), 2)

    def test_item_shape(self):
        jobs = [{"title": "ML Engineer", "company": "Acme", "url": "u"}]
        item = W.rank_jobs(jobs, self._conns())[0]
        self.assertEqual(set(item),
                         {"job", "company", "connections", "strength",
                          "paths", "match", "warm_score"})
        self.assertEqual(item["company"], "Acme")
        self.assertEqual(len(item["paths"]), 2)
        self.assertTrue(all(p.startswith("You -> ") for p in item["paths"]))
        self.assertIsNone(item["match"])

    def test_match_blend_ordering(self):
        # job B has no connections but a great match; job A has weak
        # connections but a poor match. With 50/50 blending, B can win.
        weak = [_conn(company="Acme", position="Intern",
                      connected_on=date(2015, 1, 1))]
        jobs = [
            {"title": "A", "company": "Acme"},
            {"title": "B", "company": "Nobody"},
        ]
        ranked = W.rank_jobs(jobs, weak, match_scores=[10.0, 90.0])
        self.assertEqual(ranked[0]["job"]["title"], "B")
        self.assertEqual(ranked[0]["match"], 90.0)
        self.assertAlmostEqual(ranked[0]["warm_score"],
                               (0.0 + 90.0) / 2.0)

    def test_match_none_uses_strength_alone(self):
        jobs = [{"title": "A", "company": "Acme"}]
        conns = [_conn(company="Acme", position="VP Engineering",
                      connected_on=date.today())]
        item = W.rank_jobs(jobs, conns)[0]
        self.assertIsNone(item["match"])
        self.assertAlmostEqual(item["warm_score"], item["strength"])

    def test_warm_score_formula(self):
        self.assertAlmostEqual(W.warm_score(80.0, 60.0), 70.0)
        self.assertAlmostEqual(W.warm_score(80.0, None), 80.0)

    def test_dict_match_scores(self):
        jobs = [{"title": "A", "company": "Nobody"},
                {"title": "B", "company": "Nobody"}]
        ranked = W.rank_jobs(jobs, [], match_scores={1: 75.0})
        self.assertEqual(ranked[0]["job"]["title"], "B")
        self.assertEqual(ranked[0]["match"], 75.0)


class DraftIntroTest(unittest.TestCase):
    def test_content(self):
        conn = _conn(first_name="Jane", full_name="Jane Doe",
                     position="Engineering Manager")
        job = {"title": "ML Engineer", "company": "Acme"}
        draft = W.draft_intro(conn, job, "Keshavan")
        self.assertIn("Jane", draft)
        self.assertIn("Engineering Manager", draft)
        self.assertIn("ML Engineer", draft)
        self.assertIn("Acme", draft)
        self.assertIn("Keshavan", draft)
        self.assertIn("referral", draft.lower())
        self.assertNotIn("—", draft)  # no em dashes

    def test_plain_text(self):
        draft = W.draft_intro(_conn(), {"title": "T", "company": "C"}, "U")
        self.assertNotIn("<", draft)
        self.assertNotIn("**", draft)


class WarmJsonTest(unittest.TestCase):
    def setUp(self):
        from candid import config as C
        self._orig = C.WARM_PATH
        self._td = tempfile.mkdtemp()
        C.WARM_PATH = Path(self._td) / "warm.json"

    def tearDown(self):
        from candid import config as C
        C.WARM_PATH = self._orig

    def test_round_trip(self):
        from candid import config as C
        self.assertEqual(C.WARM_PATH.name, "warm.json")
        self.assertEqual(W.load_warm(), {})
        rec = W.set_status("Acme Inc.", "asked", contact="Jane Doe")
        self.assertEqual(rec["status"], "asked")
        self.assertEqual(rec["contact"], "Jane Doe")
        self.assertEqual(rec["asked_on"], date.today().isoformat())
        self.assertEqual(W.load_warm()["acme"]["status"], "asked")
        # get_status matches via normalized company name
        st = W.get_status("ACME LLC")
        self.assertEqual(st["status"], "asked")
        self.assertEqual(st["contact"], "Jane Doe")

    def test_none_resets_asked_on(self):
        W.set_status("Acme", "asked")
        rec = W.set_status("Acme", "none")
        self.assertIsNone(rec["asked_on"])
        self.assertEqual(W.get_status("Acme")["status"], "none")

    def test_contact_kept_when_not_given(self):
        W.set_status("Acme", "asked", contact="Jane Doe")
        rec = W.set_status("Acme", "introduced")
        self.assertEqual(rec["contact"], "Jane Doe")

    def test_bad_status_rejected(self):
        with self.assertRaises(W.WarmError):
            W.set_status("Acme", "maybe")

    def test_bad_json_rejected(self):
        from candid import config as C
        C.WARM_PATH.write_text("{not json", encoding="utf-8")
        try:
            with self.assertRaises(W.WarmError):
                W.load_warm()
        finally:
            C.WARM_PATH.unlink()

    def test_get_status_default(self):
        st = W.get_status("Never Seen Co")
        self.assertEqual(st, {"contact": None, "status": "none",
                             "asked_on": None})


if __name__ == "__main__":
    unittest.main()

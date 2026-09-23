"""Tests for candid alumni network mapper (batch 63).

Covers: Connections.csv/ZIP parsing, import merge/replace, normalization,
enrichment, school/company overlap, warmth scoring, warm paths,
prioritization, outreach drafts, coverage, interaction log/freshness,
stats, and CLI wiring.

Run: CANDID_DATA_DIR=/tmp/candid-test-alumni python3 -m unittest discover -s tests -v
"""
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from datetime import date, timedelta
from pathlib import Path

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-alumni"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import alumni as A  # noqa: E402
from candid import config as C  # noqa: E402


class _IsolatedData(unittest.TestCase):
    """Give each test a fresh, isolated CANDID_DATA_DIR.

    C.DATA_DIR is bound at import time, so re-setting the env var in
    setUp has no effect — patch the module attribute instead.
    """
    def setUp(self):
        self._td = tempfile.mkdtemp()
        self._old_data_dir = C.DATA_DIR
        C.DATA_DIR = Path(self._td)

    def tearDown(self):
        C.DATA_DIR = self._old_data_dir


def _contact(name, company="", position="", connected_on="", schools=(),
             history=()):
    return {"name": name, "company": company, "position": position,
            "connected_on": connected_on, "url": "",
            "schools": list(schools),
            "history": [dict(h) for h in history], "notes": ""}


PROFILE = {
    "name": "Alex Rivera",
    "headline": "Data Scientist",
    "seniority": "senior",
    "education": [{"school": "B.S. Statistics",
                   "degree": "University of Texas at Austin",
                   "dates": "2016 – 2020"}],
    "experience": [
        {"title": "Senior Data Scientist", "company": "Meridian Financial",
         "dates": "Jan 2022 – Present"},
        {"title": "Data Analyst", "company": "Northwind Retail",
         "dates": "Jun 2020 – Dec 2021"},
    ],
}


def _network(*contacts):
    return {"contacts": list(contacts), "interactions": [],
            "meta": {"imported_at": "", "source": "", "enriched_at": ""}}


class ParseTest(unittest.TestCase):
    def test_connections_csv_basic(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
                    "Priya,Nair,https://www.linkedin.com/in/x,,Meridian Financial,"
                    "Senior Data Scientist,14 Feb 2022\n")
            p = f.name
        contacts = A.parse_connections_csv(p)
        self.assertEqual(len(contacts), 1)
        c = contacts[0]
        self.assertEqual(c["name"], "Priya Nair")
        self.assertEqual(c["company"], "Meridian Financial")
        self.assertEqual(c["connected_on"], "2022-02-14")
        self.assertNotIn("Email Address", c)
        self.assertNotIn("email", json.dumps(c).lower())

    def test_connected_on_formats(self):
        self.assertEqual(A._parse_connected_on("04 Jan 2021"), "2021-01-04")
        self.assertEqual(A._parse_connected_on("2021-03-04"), "2021-03-04")
        self.assertEqual(A._parse_connected_on("3/4/2021"), "2021-03-04")
        self.assertEqual(A._parse_connected_on(""), "")
        self.assertEqual(A._parse_connected_on("sometime"), "")

    def test_connections_csv_missing_file(self):
        with self.assertRaises(A.AlumniError):
            A.parse_connections_csv("/tmp/does-not-exist-xyz.csv")

    def test_connections_csv_no_header(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("just some text, no header\n")
            p = f.name
        with self.assertRaises(A.AlumniError):
            A.parse_connections_csv(p)

    def test_connections_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("Connections.csv",
                        "First Name,Last Name,Company,Position,Connected On\n"
                        "A,B,Acme,Engineer,01 Jan 2020\n")
            zf.writestr("Profile.csv", "First Name\nA\n")
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            f.write(buf.getvalue())
            p = f.name
        contacts = A.parse_connections_zip(p)
        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0]["name"], "A B")

    def test_connections_zip_missing_file_inside(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("Profile.csv", "First Name\nA\n")
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            f.write(buf.getvalue())
            p = f.name
        with self.assertRaises(A.AlumniError) as ctx:
            A.parse_connections_zip(p)
        self.assertIn("Connections.csv", str(ctx.exception))


class ImportTest(_IsolatedData):
    def setUp(self):
        super().setUp()
        self.csv = Path(self._td) / "c.csv"
        self.csv.write_text(
            "First Name,Last Name,Company,Position,Connected On\n"
            "Priya,Nair,Meridian Financial,Senior Data Scientist,14 Feb 2022\n"
            "David,Kim,Stripe,ML Engineer,30 May 2023\n")

    def test_import_adds(self):
        res = A.import_connections(self.csv)
        self.assertEqual(res["added"], 2)
        self.assertEqual(res["total"], 2)
        net = A.load_network()
        self.assertEqual(len(net["contacts"]), 2)

    def test_reimport_merges_and_keeps_enrichment(self):
        A.import_connections(self.csv)
        net = A.load_network()
        net["contacts"][0]["schools"] = ["University of Texas at Austin"]
        A.save_network(net)
        res = A.import_connections(self.csv)
        self.assertEqual(res["added"], 0)
        self.assertEqual(res["updated"], 2)
        net = A.load_network()
        self.assertEqual(net["contacts"][0]["schools"],
                         ["University of Texas at Austin"])

    def test_replace_wipes(self):
        A.import_connections(self.csv)
        res = A.import_connections(self.csv, replace=True)
        self.assertTrue(res["replaced"])
        self.assertEqual(res["total"], 2)


class NormTest(unittest.TestCase):
    def test_company_normalization(self):
        self.assertEqual(A.norm_company("Acme Inc."), "acme")
        self.assertEqual(A.norm_company("ACME Corporation"), "acme")
        self.assertTrue(A.companies_match("Acme Inc.", "acme corporation"))
        self.assertTrue(A.companies_match("Stripe", "Stripe, Inc."))
        self.assertFalse(A.companies_match("Meta", "Metals"))
        self.assertFalse(A.companies_match("", "Acme"))
        self.assertFalse(A.companies_match("Acme", ""))

    def test_school_normalization(self):
        self.assertTrue(A.schools_match("University of Texas at Austin",
                                        "Texas Austin"))
        self.assertTrue(A.schools_match("MIT", "mit"))
        self.assertFalse(A.schools_match("UT Austin",
                                          "University of Texas at Austin"))
        self.assertFalse(A.schools_match("", "MIT"))

    def test_name_normalization(self):
        self.assertEqual(A.norm_name("  Priya  Nair "), "priya nair")


class EnrichTest(_IsolatedData):
    def setUp(self):
        super().setUp()
        self.csv = Path(self._td) / "c.csv"
        self.csv.write_text(
            "First Name,Last Name,Company,Position,Connected On\n"
            "Priya,Nair,Meridian Financial,Senior Data Scientist,14 Feb 2022\n"
            "Hannah,Cole,Meridian Financial,Data Science Manager,17 Mar 2021\n")
        A.import_connections(self.csv)

    def _enrich_csv(self, text):
        p = Path(tempfile.mkdtemp()) / "e.csv"
        p.write_text(text)
        return p

    def test_enrich_schools_and_history(self):
        p = self._enrich_csv(
            "name,school,grad_year,prev_company,start_year,end_year,notes\n"
            "Priya Nair,University of Texas at Austin,2018,,,,\n"
            "Hannah Cole,,,Stripe,2019,2022,can intro\n")
        res = A.enrich_contacts(A.parse_enrichment_csv(p))
        self.assertEqual(res["matched"], 2)
        self.assertEqual(res["unmatched"], 0)
        net = A.load_network()
        priya = next(c for c in net["contacts"] if c["name"] == "Priya Nair")
        self.assertIn("University of Texas at Austin (2018)", priya["schools"])
        hannah = next(c for c in net["contacts"] if c["name"] == "Hannah Cole")
        self.assertEqual(hannah["history"][0]["company"], "Stripe")
        self.assertEqual(hannah["history"][0]["start_year"], 2019)
        self.assertEqual(hannah["notes"], "can intro")

    def test_enrich_unmatched_names_counted(self):
        p = self._enrich_csv("name,school\nNobody Real,Harvard\n")
        res = A.enrich_contacts(A.parse_enrichment_csv(p))
        self.assertEqual(res["matched"], 0)
        self.assertEqual(res["unmatched"], 1)

    def test_enrichment_needs_name_column(self):
        p = self._enrich_csv("school\nHarvard\n")
        with self.assertRaises(A.AlumniError):
            A.parse_enrichment_csv(p)

    def test_enrichment_dedupes_history(self):
        p = self._enrich_csv("name,prev_company,start_year,end_year\n"
                             "Hannah Cole,Stripe,2019,2022\n"
                             "Hannah Cole,Stripe Inc,2019,2022\n")
        A.enrich_contacts(A.parse_enrichment_csv(p))
        net = A.load_network()
        hannah = next(c for c in net["contacts"] if c["name"] == "Hannah Cole")
        self.assertEqual(len(hannah["history"]), 1)


class ProfileFactsTest(unittest.TestCase):
    def test_user_schools_swapped_fields(self):
        schools = A.user_schools(PROFILE)
        self.assertIn("University of Texas at Austin", schools)
        self.assertNotIn("B.S. Statistics", schools)

    def test_user_schools_plain(self):
        p = {"education": [{"school": "Stanford University", "degree": "M.S."}]}
        self.assertEqual(A.user_schools(p), ["Stanford University"])

    def test_user_companies(self):
        cos = A.user_companies(PROFILE)
        self.assertEqual(cos[0]["company"], "Meridian Financial")
        self.assertTrue(cos[0]["current"])
        self.assertFalse(cos[1]["current"])
        self.assertEqual(cos[1]["start_year"], 2020)


def _sample_network():
    recent = (date.today() - timedelta(days=100)).isoformat()
    old = (date.today() - timedelta(days=900)).isoformat()
    return _network(
        _contact("Priya Nair", "Meridian Financial", "Senior Data Scientist",
                 recent, schools=["University of Texas at Austin (2018)"]),
        _contact("David Kim", "Stripe", "Machine Learning Engineer",
                 recent),
        _contact("Hannah Cole", "Meridian Financial", "Data Science Manager",
                 old, schools=["Stanford University (2015)"],
                 history=[{"company": "Stripe", "start_year": 2019,
                           "end_year": 2022}]),
        _contact("Grace Liu", "Duolingo", "Product Data Scientist", old,
                 schools=["University of Texas at Austin (2020)"]),
        _contact("Tom Becker", "Northwind Retail", "VP Analytics", old),
    )


class OverlapTest(unittest.TestCase):
    def test_school_overlap(self):
        hits = A.school_overlap(_sample_network(), PROFILE)
        names = [h["contact"]["name"] for h in hits]
        self.assertEqual(names, ["Grace Liu", "Priya Nair"])
        self.assertIn("University of Texas at Austin", hits[0]["schools"])

    def test_school_overlap_needs_enrichment(self):
        net = _network(_contact("X Y", "Acme", "Engineer"))
        self.assertEqual(A.school_overlap(net, PROFILE), [])

    def test_company_overlap_current_and_past(self):
        hits = A.company_overlap(_sample_network(), PROFILE)
        names = [h["contact"]["name"] for h in hits]
        self.assertIn("Priya Nair", names)
        self.assertIn("Hannah Cole", names)
        self.assertIn("Tom Becker", names)
        priya = next(h for h in hits if h["contact"]["name"] == "Priya Nair")
        self.assertEqual(priya["companies"][0]["company"], "Meridian Financial")
        self.assertEqual(priya["companies"][0]["where"], "current")

    def test_company_overlap_tenure_span(self):
        net = _network(_contact(
            "Hannah Cole", "Meridian Financial", "Data Science Manager", "",
            history=[{"company": "Northwind Retail", "start_year": 2019,
                      "end_year": 2021}]))
        hits = A.company_overlap(net, PROFILE)
        hannah = next(h for h in hits if h["contact"]["name"] == "Hannah Cole")
        nw = next(c for c in hannah["companies"]
                  if c["company"] == "Northwind Retail")
        self.assertEqual(nw["where"], "past")
        self.assertTrue(nw["tenure_overlap"])
        self.assertEqual(nw["span"], "2020–2021")


class WarmthTest(_IsolatedData):
    def test_base_score_and_reasons(self):
        net = _sample_network()
        c = net["contacts"][3]  # Grace Liu
        w = A.warmth_score(c, PROFILE, network=net)
        self.assertGreaterEqual(w["score"], 20)
        self.assertTrue(any("1st-degree" in r[1] for r in w["reasons"]))

    def test_shared_school_bonus(self):
        net = _sample_network()
        grace = next(c for c in net["contacts"] if c["name"] == "Grace Liu")
        tom = next(c for c in net["contacts"] if c["name"] == "Tom Becker")
        wg = A.warmth_score(grace, PROFILE, network=net)["score"]
        wt = A.warmth_score(tom, PROFILE, network=net)["score"]
        self.assertGreater(wg, wt)

    def test_target_company_bonus(self):
        net = _sample_network()
        david = next(c for c in net["contacts"] if c["name"] == "David Kim")
        no_target = A.warmth_score(david, PROFILE, network=net)["score"]
        with_target = A.warmth_score(david, PROFILE, "Stripe", network=net)["score"]
        self.assertEqual(with_target - no_target, 20)

    def test_score_capped_at_100(self):
        net = _sample_network()
        c = _contact("Super Connector", "Stripe", "Senior ML Engineer",
                     date.today().isoformat(),
                     schools=["University of Texas at Austin"],
                     history=[{"company": "Meridian Financial",
                               "start_year": 2022, "end_year": 2024}])
        w = A.warmth_score(c, PROFILE, "Stripe", "ML Engineer", net)
        self.assertLessEqual(w["score"], 100)
        self.assertGreaterEqual(w["score"], 90)

    def test_interaction_boosts_warmth(self):
        net = _sample_network()
        A.save_network(net)
        tom = next(c for c in net["contacts"] if c["name"] == "Tom Becker")
        before = A.warmth_score(tom, PROFILE, network=A.load_network())["score"]
        A.log_interaction("Tom Becker", "coffee", "good chat")
        after = A.warmth_score(tom, PROFILE, network=A.load_network())["score"]
        self.assertGreater(after, before)

    def test_seniority_rank(self):
        self.assertEqual(A.seniority_rank("Senior Data Scientist"), 3)
        self.assertEqual(A.seniority_rank("VP of Analytics"), 8)
        self.assertEqual(A.seniority_rank("Staff Engineer"), 5)
        self.assertEqual(A.seniority_rank("Barista"), 2)


class WarmPathsTest(unittest.TestCase):
    def test_direct_and_bridges(self):
        wp = A.warm_paths(_sample_network(), PROFILE, "Stripe", "ML Engineer")
        self.assertEqual(wp["total_direct"], 1)
        self.assertEqual(wp["direct"][0]["contact"]["name"], "David Kim")
        self.assertEqual(wp["total_bridges"], 1)
        self.assertEqual(wp["bridges"][0]["contact"]["name"], "Hannah Cole")

    def test_no_paths(self):
        wp = A.warm_paths(_sample_network(), PROFILE, "Nonexistent Corp")
        self.assertEqual(wp["total_direct"], 0)
        self.assertEqual(wp["total_bridges"], 0)

    def test_needs_company(self):
        with self.assertRaises(A.AlumniError):
            A.warm_paths(_sample_network(), PROFILE, "")

    def test_ranked_by_warmth(self):
        net = _network(
            _contact("Cold Contact", "Stripe", "Engineer",
                     (date.today() - timedelta(days=2000)).isoformat()),
            _contact("Warm Contact", "Stripe", "Senior Engineer",
                     date.today().isoformat(),
                     schools=["University of Texas at Austin"]),
        )
        wp = A.warm_paths(net, PROFILE, "Stripe")
        self.assertEqual(wp["direct"][0]["contact"]["name"], "Warm Contact")


class PrioritizeTest(unittest.TestCase):
    def test_tiers_and_order(self):
        queue = A.prioritize(_sample_network(), PROFILE,
                             targets=[("Stripe", "ML Engineer")])
        self.assertEqual(queue[0]["contact"]["name"], "David Kim")
        self.assertIn(queue[0]["tier"], ("this-week", "nurture"))
        tiers = {e["tier"] for e in queue}
        self.assertTrue(tiers <= {"this-week", "nurture", "low"})

    def test_no_targets_pure_warmth(self):
        queue = A.prioritize(_sample_network(), PROFILE)
        scores = [e["score"] for e in queue]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_limit(self):
        queue = A.prioritize(_sample_network(), PROFILE, limit=2)
        self.assertEqual(len(queue), 2)


class DraftTest(unittest.TestCase):
    def _david(self):
        return _contact("David Kim", "Stripe", "Machine Learning Engineer",
                        "2023-05-30")

    def test_referral_uses_facts(self):
        d = A.draft_outreach(self._david(), PROFILE, "referral",
                             "Stripe", "ML Engineer")
        self.assertIn("Hi David,", d)
        self.assertIn("Stripe", d)
        self.assertIn("ML Engineer", d)
        self.assertIn("Alex Rivera", d)

    def test_referral_shared_school_opener(self):
        c = _contact("Priya Nair", "Meridian Financial", "Senior Data Scientist",
                     "", schools=["University of Texas at Austin"])
        d = A.draft_outreach(c, PROFILE, "referral", "Stripe", "ML Engineer")
        self.assertIn("Fellow University of Texas at Austin alum", d)

    def test_referral_shared_employer_opener(self):
        c = _contact("Marcus Webb", "Meridian Financial", "Engineering Manager")
        d = A.draft_outreach(c, PROFILE, "referral", "Stripe")
        self.assertIn("Fellow ex-Meridian Financial", d)

    def test_info_chat_and_reconnect(self):
        c = self._david()
        info = A.draft_outreach(c, PROFILE, "info-chat", "Stripe", "ML Engineer")
        self.assertIn("15-minute chat", info)
        re_ = A.draft_outreach(c, PROFILE, "reconnect")
        self.assertIn("It's been a while", re_)

    def test_referral_needs_company(self):
        with self.assertRaises(A.AlumniError):
            A.draft_outreach(self._david(), PROFILE, "referral")

    def test_bad_kind(self):
        with self.assertRaises(A.AlumniError):
            A.draft_outreach(self._david(), PROFILE, "carrier-pigeon")


class CoverageTest(unittest.TestCase):
    def test_coverage_and_gaps(self):
        cov = A.coverage(_sample_network(), PROFILE,
                         ["Stripe", "OpenAI", "Nonexistent Corp"])
        by_co = {p["company"]: p for p in cov["per_company"]}
        self.assertEqual(by_co["Stripe"]["contacts"], 1)
        self.assertEqual(by_co["Stripe"]["bridges"], 1)
        self.assertEqual(by_co["Stripe"]["warmest"]["name"], "David Kim")
        self.assertIn("Nonexistent Corp", cov["gaps"])
        self.assertIn("OpenAI", cov["gaps"])
        schools = {s["school"]: s["contacts"] for s in cov["per_school"]}
        self.assertEqual(schools["University of Texas at Austin"], 2)


class LogFreshnessTest(_IsolatedData):
    def setUp(self):
        super().setUp()
        old = (date.today() - timedelta(days=900)).isoformat()
        recent = (date.today() - timedelta(days=100)).isoformat()
        A.save_network(_network(
            _contact("Old Friend", "Acme", "Engineer", old),
            _contact("New Friend", "Acme", "Engineer", recent),
        ))

    def test_log_interaction(self):
        rec = A.log_interaction("Old Friend", "coffee", "great chat")
        self.assertEqual(rec["kind"], "coffee")
        self.assertEqual(rec["date"], date.today().isoformat())
        net = A.load_network()
        self.assertEqual(len(net["interactions"]), 1)

    def test_log_bad_kind(self):
        with self.assertRaises(A.AlumniError):
            A.log_interaction("Old Friend", "telepathy")

    def test_log_unknown_name_suggests(self):
        with self.assertRaises(A.AlumniError) as ctx:
            A.log_interaction("Old Fiend", "coffee")
        self.assertIn("Old Friend", str(ctx.exception))

    def test_freshness_flags_stale(self):
        net = A.load_network()
        q = A.freshness(net, PROFILE, stale_days=365, quiet_days=180)
        names = [e["contact"]["name"] for e in q]
        self.assertIn("Old Friend", names)
        self.assertNotIn("New Friend", names)

    def test_freshness_cleared_by_recent_interaction(self):
        A.log_interaction("Old Friend", "emailed", "hello")
        net = A.load_network()
        q = A.freshness(net, PROFILE, stale_days=365, quiet_days=180)
        self.assertEqual(q, [])

    def test_find_contact(self):
        net = A.load_network()
        self.assertEqual(A.find_contact(net, "old friend")["name"], "Old Friend")
        with self.assertRaises(A.AlumniError):
            A.find_contact(net, "Nobody")


class StatsTest(unittest.TestCase):
    def test_stats(self):
        s = A.stats(_sample_network())
        self.assertEqual(s["total_contacts"], 5)
        self.assertEqual(s["with_company"], 5)
        self.assertEqual(s["enriched_schools"], 3)
        self.assertEqual(s["with_history"], 1)
        top = {x["company"]: x["contacts"] for x in s["top_companies"]}
        self.assertEqual(top["Meridian Financial"], 2)


class SampleFilesTest(unittest.TestCase):
    def test_sample_connections_parse(self):
        p = ROOT / "samples" / "candid" / "sample_connections.csv"
        contacts = A.parse_connections_csv(p)
        self.assertEqual(len(contacts), 12)
        self.assertTrue(all(c["connected_on"] for c in contacts))

    def test_sample_enrichment_matches(self):
        p = ROOT / "samples" / "candid" / "sample_enrichment.csv"
        rows = A.parse_enrichment_csv(p)
        self.assertGreater(len(rows), 5)
        names = {r["name"] for r in rows}
        contacts = {c["name"] for c in
                    A.parse_connections_csv(
                        ROOT / "samples" / "candid" / "sample_connections.csv")}
        self.assertTrue(names <= contacts)


class CliWiringTest(unittest.TestCase):
    def test_alumni_parsers(self):
        from candid.__main__ import build_parser
        p = build_parser()
        a = p.parse_args(["alumni", "warm-path", "--company", "Stripe",
                          "--role", "ML Engineer"])
        self.assertEqual(a.cmd, "alumni")
        self.assertEqual(a.what, "warm-path")
        self.assertEqual(a.company, "Stripe")
        a = p.parse_args(["alumni", "draft", "--name", "X",
                          "--kind", "reconnect"])
        self.assertEqual(a.kind, "reconnect")
        a = p.parse_args(["alumni", "log", "--name", "X", "--kind", "coffee"])
        self.assertEqual(a.kind, "coffee")


if __name__ == "__main__":
    unittest.main()

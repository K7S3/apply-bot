"""Tests for company briefs (candid/briefs.py) and the `prep brief` wiring.

All HTTP is stubbed via monkeypatching ``candid.briefs._http_json`` with
fictional fixture responses - no network in tests. Data paths are
redirected into a temp dir (same approach as tests/test_cli_ux.py).
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import briefs as B  # noqa: E402
from candid import config as C  # noqa: E402

# ---------------------------------------------------------------------------
# fixtures (fictional company; clearly public-company-style data is fake)
# ---------------------------------------------------------------------------

WIKI_EXTRACT = {
    "query": {"pages": {"424242": {
        "pageid": 424242,
        "title": "Fictional Widgets Inc.",
        "fullurl": "https://en.wikipedia.org/wiki/Fictional_Widgets_Inc.",
        "extract": ("Fictional Widgets Inc. is an American software company "
                    "headquartered in Widgetville. It raised $250 million in "
                    "Series C funding in 2023. The company employs about "
                    "4,200 people worldwide."),
    }}}
}

WIKI_WIKITEXT = {
    "query": {"pages": {"424242": {
        "pageid": 424242,
        "title": "Fictional Widgets Inc.",
        "revisions": [{"slots": {"main": {"*": (
            "{{Infobox company\n"
            "| name = Fictional Widgets Inc.\n"
            "| type = [[Private company|Private]]\n"
            "| industry = [[Software]]\n"
            "| founded = 2015\n"
            "| hq_location = Widgetville, [[California]]\n"
            "| num_employees = 4,200 (2024)\n"
            "| revenue = {{US$|1.2 billion}} (2024)\n"
            "| key_people = [[Jane Doe]] ([[Chief executive officer|CEO]])\n"
            "}}\nSome other article text."
        )}}}],
    }}}
}

TICKERS = {
    "0": {"cik_str": 1234567, "ticker": "FWID", "title": "Fictional Widgets Inc."},
    "1": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
}

SUBMISSIONS = {
    "filings": {"recent": {
        "form": ["10-K", "10-Q", "8-K"],
        "filingDate": ["2024-02-01", "2024-05-01", "2024-06-01"],
    }}
}

COMPANYFACTS = {
    "facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            {"val": 950000000, "end": "2022-12-31", "form": "10-K", "filed": "2023-02-01"},
            {"val": 1200000000, "end": "2023-12-31", "form": "10-K", "filed": "2024-02-01"},
        ]}},
        "NetIncomeLoss": {"units": {"USD": [
            {"val": 180000000, "end": "2023-12-31", "form": "10-K", "filed": "2024-02-01"},
        ]}},
        "Assets": {"units": {"USD": [
            {"val": 2400000000, "end": "2023-12-31", "form": "10-K", "filed": "2024-02-01"},
        ]}},
        "Employees": {"units": {"pure": [
            {"val": 4200, "end": "2023-12-31", "form": "10-K", "filed": "2024-02-01"},
        ]}},
    }}
}


def fake_http(url, params=None):
    """Fixture dispatcher keyed on URL (+ the Wikipedia prop being fetched)."""
    if "wikipedia.org" in url:
        if params and params.get("prop") == "revisions":
            return WIKI_WIKITEXT
        return WIKI_EXTRACT
    if "company_tickers.json" in url:
        return TICKERS
    if "/submissions/" in url:
        return SUBMISSIONS
    if "/companyfacts/" in url:
        return COMPANYFACTS
    return None


class BriefBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-briefs-"))
        self._saved = {n: getattr(C, n) for n in ("DATA_DIR", "PREP_PACKS_DIR")}
        C.DATA_DIR = self.tmp
        C.PREP_PACKS_DIR = self.tmp / "prep_packs"
        patcher = mock.patch.object(B, "_http_json", side_effect=fake_http)
        self._http = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)


class WikipediaParseTest(BriefBase):
    def test_extract_and_title(self):
        w = B.fetch_wikipedia("Fictional Widgets Inc.")
        self.assertTrue(w["found"])
        self.assertEqual(w["title"], "Fictional Widgets Inc.")
        self.assertIn("en.wikipedia.org", w["url"])
        self.assertIn("American software company", w["summary"])

    def test_infobox_facts(self):
        w = B.fetch_wikipedia("Fictional Widgets Inc.")
        facts = w["facts"]
        self.assertEqual(facts["Type"], "Private")
        self.assertEqual(facts["Industry"], "Software")
        self.assertEqual(facts["Founded"], "2015")
        self.assertEqual(facts["Headquarters"], "Widgetville, California")
        self.assertEqual(facts["Employees"], "4,200 (2024)")
        self.assertEqual(facts["Revenue"], "$1.2 billion (2024)")
        self.assertEqual(facts["Key people"], "Jane Doe (CEO)")

    def test_funding_mention(self):
        w = B.fetch_wikipedia("Fictional Widgets Inc.")
        self.assertIn("$250 million", w["funding_mention"])
        self.assertIn("Series C", w["funding_mention"])

    def test_missing_page(self):
        with mock.patch.object(B, "_http_json", return_value=None):
            w = B.fetch_wikipedia("No Such Company Xyzzy")
        self.assertFalse(w["found"])
        self.assertEqual(w["facts"], {})


class EdgarParseTest(BriefBase):
    def test_cik_resolution(self):
        resolved = B._edgar_cik("Fictional Widgets Inc.")
        self.assertEqual(resolved, ("0001234567", "FWID"))

    def test_cik_resolution_strips_suffix(self):
        resolved = B._edgar_cik("fictional widgets")
        self.assertEqual(resolved, ("0001234567", "FWID"))

    def test_ten_k_highlights(self):
        e = B.fetch_edgar("Fictional Widgets Inc.")
        self.assertTrue(e["found"])
        self.assertEqual(e["cik"], "0001234567")
        self.assertEqual(e["ticker"], "FWID")
        self.assertEqual(e["latest_10k_date"], "2024-02-01")
        self.assertEqual(e["facts"]["Revenue"]["value"], 1200000000)
        self.assertEqual(e["facts"]["Revenue"]["fy"], "2023")
        self.assertEqual(e["facts"]["Net income"]["value"], 180000000)
        self.assertEqual(e["facts"]["Total assets"]["value"], 2400000000)
        self.assertEqual(e["facts"]["Employees"]["value"], 4200)

    def test_no_filer(self):
        with mock.patch.object(B, "_http_json", return_value=None):
            e = B.fetch_edgar("No Such Company Xyzzy")
        self.assertFalse(e["found"])
        self.assertIn("No SEC EDGAR filer found", e["note"])

    def test_freshest_alias_wins(self):
        """A stale legacy concept must not shadow the current one."""
        facts = {"facts": {"us-gaap": {
            "Revenues": {"units": {"USD": [
                {"val": 1, "end": "2018-12-31", "form": "10-K", "filed": "2019-02-01"},
            ]}},
            "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
                {"val": 2, "end": "2023-12-31", "form": "10-K", "filed": "2024-02-01"},
            ]}},
        }}}
        with mock.patch.object(B, "_http_json", return_value=facts):
            out = B._edgar_facts("0001234567")
        self.assertEqual(out["Revenue"]["value"], 2)
        self.assertEqual(out["Revenue"]["fy"], "2023")


class RenderTest(BriefBase):
    def _brief(self):
        return B.get_brief("Fictional Widgets Inc.")

    def test_source_labeling(self):
        md = B.render_brief(self._brief())
        self.assertIn("Source: Wikipedia", md)
        self.assertIn("Source: Wikipedia infobox", md)
        self.assertIn("Source: SEC EDGAR 10-K XBRL", md)
        self.assertIn("Source: SEC EDGAR submissions", md)

    def test_every_fact_labeled(self):
        md = B.render_brief(self._brief())
        for label in ("Founded:", "Headquarters:", "Revenue (FY2023):",
                      "Net income (FY2023):", "Total assets (FY2023):",
                      "Latest 10-K filed:"):
            self.assertIn(label, md, f"missing fact line: {label}")

    def test_missing_data_fallback(self):
        with mock.patch.object(B, "_http_json", return_value=None):
            brief = B.get_brief("No Such Company Xyzzy", refresh=True)
        md = B.render_brief(brief)
        self.assertIn("No verified company data found", md)
        # nothing invented: no dollar figures, no headcount numbers
        self.assertNotIn("$", md.replace("`python -m candid prep brief", ""))

    def test_partial_data_no_edgar_still_honest(self):
        def wiki_only(url, params=None):
            if "wikipedia.org" in url:
                return fake_http(url, params)
            return None
        with mock.patch.object(B, "_http_json", side_effect=wiki_only):
            brief = B.get_brief("Fictional Widgets Inc.", refresh=True)
        md = B.render_brief(brief)
        self.assertIn("Source: Wikipedia", md)
        self.assertIn("No SEC EDGAR filer found", md)
        self.assertNotIn("No verified company data found", md)


class CacheTest(BriefBase):
    def test_second_call_uses_cache(self):
        b1 = B.get_brief("Fictional Widgets Inc.")
        self.assertFalse(b1["from_cache"])
        calls = self._http.call_count
        # network now fails: cached copy must be returned
        with mock.patch.object(B, "_http_json", return_value=None):
            b2 = B.get_brief("Fictional Widgets Inc.")
        self.assertTrue(b2["from_cache"])
        self.assertEqual(b2["wikipedia"]["title"], "Fictional Widgets Inc.")
        self.assertEqual(self._http.call_count, calls)

    def test_refresh_bypasses_cache(self):
        B.get_brief("Fictional Widgets Inc.")
        calls = self._http.call_count
        B.get_brief("Fictional Widgets Inc.", refresh=True)
        self.assertGreater(self._http.call_count, calls)

    def test_offline_no_cache_gives_honest_note(self):
        # even a transport that raises (belt and braces) must not escape
        with mock.patch.object(B, "_http_json", side_effect=RuntimeError("offline")):
            brief = B.get_brief("Never Heard Of It Co", refresh=True)
        md = B.render_brief(brief)
        self.assertIn("No verified company data found", md)

    def test_cache_file_written(self):
        B.get_brief("Fictional Widgets Inc.")
        cache_files = list((self.tmp / "briefs_cache").glob("*.json"))
        self.assertEqual(len(cache_files), 1)
        payload = json.loads(cache_files[0].read_text(encoding="utf-8"))
        self.assertIn("fetched_at", payload)
        self.assertIn("brief", payload)


class BriefCLITest(BriefBase):
    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                CLI.main(argv)
        except SystemExit as e:
            return e.code, out.getvalue(), err.getvalue()
        return 0, out.getvalue(), err.getvalue()

    def test_prep_brief_prints_brief(self):
        code, stdout, _ = self.run_cli(["prep", "brief", "--company", "Fictional Widgets Inc."])
        self.assertEqual(code, 0)
        self.assertIn("## Company brief", stdout)
        self.assertIn("Source: Wikipedia", stdout)
        self.assertIn("Source: SEC EDGAR 10-K XBRL", stdout)

    def test_prep_brief_needs_company(self):
        code, _, stderr = self.run_cli(["prep", "brief"])
        self.assertEqual(code, 1)
        self.assertIn("prep brief", stderr)
        self.assertIn("Next: run `python -m candid prep --help`", stderr)

    def test_prep_pack_includes_brief_section(self):
        from candid import prep as P
        prof = {"name": "Alex", "skills": ["python"], "experience": []}
        section = B.render_brief(B.get_brief("Fictional Widgets Inc."))
        md, _ = P.build_pack(prof, "Fictional Widgets Inc.", "Data Scientist",
                             brief_section=section)
        self.assertIn("## Company brief", md)
        self.assertIn("Source: Wikipedia infobox", md)

    def test_prep_pack_without_brief_stays_offline(self):
        from candid import prep as P
        prof = {"name": "Alex", "skills": ["python"], "experience": []}
        with mock.patch.object(B, "_http_json",
                               side_effect=AssertionError("must stay offline")):
            md, _ = P.build_pack(prof, "Fictional Widgets Inc.", "Data Scientist")
        self.assertNotIn("## Company brief", md)


if __name__ == "__main__":
    unittest.main()

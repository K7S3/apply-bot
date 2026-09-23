"""Tests for the candid culture decoder (candid/culture.py + CLI wiring).

Sibling modules (culture_values, culture_signals, culture_stability,
culture_process) are developed in parallel, so every test stubs them via
sys.modules injection or verifies the no-sibling fallback. Data paths are
redirected into a temp dir by monkeypatching candid.config attributes.
"""
import contextlib
import io
import json
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402
from candid import culture as CL  # noqa: E402

SIBLINGS = ("culture_values", "culture_signals",
            "culture_stability", "culture_process")


def stub(name, **funcs):
    """Install a fake sibling module into the active stub registry."""
    mod = types.ModuleType(f"candid.{name}")
    for fname, fn in funcs.items():
        setattr(mod, fname, fn)
    _ACTIVE_STUBS[name] = mod
    sys.modules[f"candid.{name}"] = mod
    return mod


def un_stub_all():
    _ACTIVE_STUBS.clear()
    for name in SIBLINGS:
        sys.modules.pop(f"candid.{name}", None)


# Registry consulted by the patched CL._sibling in tests. The production
# code resolves siblings via importlib, which re-imports real modules from
# disk even after a sys.modules pop, so tests must patch the _sibling seam
# itself to simulate a missing module.
_ACTIVE_STUBS: dict[str, types.ModuleType] = {}


class CultureBase(unittest.TestCase):
    def setUp(self):
        un_stub_all()
        self._sibling_patch = mock.patch.object(
            CL, "_sibling", side_effect=lambda name: _ACTIVE_STUBS.get(name))
        self._sibling_patch.start()
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-culture-"))
        self._saved = {}
        for attr in ("DATA_DIR", "CULTURE_DIR", "TRACKER_PATH",
                     "PREP_PACKS_DIR", "SALARY_DB"):
            self._saved[attr] = getattr(C, attr)
        C.DATA_DIR = self.tmp
        C.CULTURE_DIR = self.tmp / "culture"
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.PREP_PACKS_DIR = self.tmp / "prep_packs"
        C.SALARY_DB = self.tmp / "salary.db"

    def tearDown(self):
        self._sibling_patch.stop()
        un_stub_all()
        for attr, val in self._saved.items():
            setattr(C, attr, val)

    def run_cli(self, argv):
        """Parse argv and run the bound cmd function; returns stdout."""
        args = CLI.build_parser().parse_args(argv)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            args.func(args)
        return out.getvalue()


def _all_stubs():
    stub("culture_values",
         load_values=lambda company: [
             {"value": "transparency",
              "quote": "We default to transparency.",
              "source": "careers page"}],
         extract_values=lambda text, company, origin="user-provided text": [
             {"value": "ownership", "quote": text[:40], "source": origin}],
         values_to_questions=lambda values: [
             {"question": f"Tell me about a time you lived {v['value']}.",
              "targets_value": v["value"], "source": "culture_values"}
             for v in values])
    stub("culture_signals",
         company_jd_signals=lambda company, jobs: {
             "company": company, "job_count": 3,
             "workstyle": {"remote": "remote-first team"},
             "benefits": ["401k match"],
             "flags": ["fast-paced environment"],
             "sources": ["arbeitnow"]})
    stub("culture_stability",
         stability=lambda company, datasets: [
             {"signal": "headcount trend", "value": "growing",
              "source": "warn data", "as_of": "2026-09", "note": ""}],
         trajectory=lambda company, datasets: [])
    stub("culture_process",
         process_profile=lambda company, ctx: {
             "company": company,
             "stages": [{"stage": "phone screen",
                         "evidence": [{"quote": "30 min recruiter call",
                                       "source": "debrief"}]}],
             "coverage": "low", "note": ""})


class ProfileCardTest(CultureBase):
    def test_merges_all_siblings(self):
        _all_stubs()
        card = CL.profile_card("Acme")
        self.assertEqual(card["company"], "Acme")
        self.assertEqual(card["generated_at"], date.today().isoformat())
        self.assertNotIn("note", card)
        labels = [s["signal"] for s in card["signals"]]
        self.assertIn("value: transparency", labels)
        self.assertIn("workstyle: remote", labels)
        self.assertIn("benefit: 401k match", labels)
        self.assertIn("flag: fast-paced environment", labels)
        self.assertIn("jd sample size", labels)
        self.assertIn("headcount trend", labels)
        self.assertIn("interview process: phone screen", labels)
        cov = card["coverage"]
        self.assertEqual(cov["careers page"], 1)
        self.assertEqual(cov["arbeitnow"], 4)  # sample size + workstyle + benefit + flag
        self.assertEqual(cov["warn data"], 1)
        self.assertEqual(cov["debrief"], 1)

    def test_signals_have_canonical_shape(self):
        _all_stubs()
        for sig in CL.profile_card("Acme")["signals"]:
            self.assertEqual(set(sig), {"signal", "value", "source",
                                        "as_of", "note"})

    def test_dedupe_near_identical_signals(self):
        stub("culture_values",
             load_values=lambda company: [
                 {"value": "Transparency",
                  "quote": "  We default to transparency. ",
                  "source": "careers page"}])
        stub("culture_stability",
             stability=lambda company, datasets: [
                 {"signal": "value: transparency",
                  "value": "we default to transparency.",
                  "source": "other", "as_of": None, "note": ""}],
             trajectory=lambda company, datasets: [])
        card = CL.profile_card("Acme")
        matching = [s for s in card["signals"]
                    if s["signal"].lower() == "value: transparency"]
        self.assertEqual(len(matching), 1)
        # first occurrence (the values one) wins
        self.assertEqual(matching[0]["source"], "careers page")

    def test_no_siblings_gives_empty_card_with_note(self):
        card = CL.profile_card("Acme")
        self.assertEqual(card["signals"], [])
        self.assertEqual(card["coverage"], {})
        self.assertEqual(card["note"], "no verified culture data for Acme")
        self.assertEqual(len(card["coverage_notes"]), 4)

    def test_partial_modules_degrade_gracefully(self):
        stub("culture_values",
             load_values=lambda company: [
                 {"value": "transparency", "quote": "q", "source": "s"}])
        card = CL.profile_card("Acme")
        self.assertEqual(len(card["signals"]), 1)
        self.assertNotIn("note", card)
        notes = " ".join(card["coverage_notes"])
        self.assertIn("culture_signals", notes)
        self.assertIn("culture_stability", notes)
        self.assertIn("culture_process", notes)

    def test_sibling_error_becomes_coverage_note(self):
        def boom(company):
            raise RuntimeError("db gone")
        stub("culture_values", load_values=boom)
        card = CL.profile_card("Acme")
        self.assertEqual(card["signals"], [])
        self.assertIn("note", card)
        self.assertTrue(any("load_values failed" in n
                            for n in card["coverage_notes"]))

    def test_blank_company_raises(self):
        with self.assertRaises(CL.CultureError):
            CL.profile_card("  ")

    def test_render_card_plain_text(self):
        _all_stubs()
        text = CL.render_card(CL.profile_card("Acme"))
        self.assertIn("Culture profile: Acme", text)
        self.assertIn("Signals (", text)
        self.assertIn("Coverage:", text)
        self.assertNotIn("\u2014", text)  # no em dashes
        self.assertNotIn("\U0001f600", text)

    def test_render_empty_card_shows_note(self):
        text = CL.render_card(CL.profile_card("Acme"))
        self.assertIn("no verified culture data for Acme", text)


class CompareTest(CultureBase):
    def _stubs(self):
        by_company = {
            "Acme": [{"value": "transparency",
                      "quote": "We default to transparency.",
                      "source": "careers page"}],
            "Globex": [{"value": "ownership",
                        "quote": "Own it end to end.",
                        "source": "careers page"}],
        }
        stub("culture_values", load_values=lambda company: by_company.get(company, []))
        stub("culture_signals",
             company_jd_signals=lambda company, jobs: {
                 "company": company,
                 "job_count": 2 if company == "Acme" else 0,
                 "workstyle": {"remote": "remote-first"} if company == "Acme" else {},
                 "benefits": [], "flags": [], "sources": ["arbeitnow"]})

    def test_compare_labels_and_sources(self):
        self._stubs()
        res = CL.compare("Acme", "Globex")
        self.assertIn("a", res)
        self.assertIn("b", res)
        self.assertEqual(res["a"]["company"], "Acme")
        self.assertEqual(res["b"]["company"], "Globex")
        self.assertEqual(res["shared_sources"], ["careers page"])
        self.assertEqual(res["only_in_a"],
                         ["jd sample size", "value: transparency",
                          "workstyle: remote"])
        self.assertEqual(res["only_in_b"], ["value: ownership"])

    def test_compare_both_empty(self):
        res = CL.compare("Acme", "Globex")
        self.assertEqual(res["shared_sources"], [])
        self.assertEqual(res["only_in_a"], [])
        self.assertEqual(res["only_in_b"], [])
        self.assertIn("note", res["a"])
        self.assertIn("note", res["b"])

    def test_render_compare(self):
        self._stubs()
        text = CL.render_compare(CL.compare("Acme", "Globex"))
        self.assertIn("Culture compare: Acme vs Globex", text)
        self.assertIn("Shared sources (1): careers page", text)
        self.assertIn("Only in Acme (3):", text)
        self.assertIn("Only in Globex (1):", text)
        self.assertNotIn("\u2014", text)


class ValuesTest(CultureBase):
    def test_extract_and_store_roundtrip(self):
        stub("culture_values",
             load_values=lambda company: [],
             extract_values=lambda text, company, origin="user-provided text": [
                 {"value": "ownership", "quote": "Own it.", "source": origin}],
             values_to_questions=lambda values: [])
        vals = CL.extract_and_store_values("Acme", "We value ownership.")
        self.assertEqual(len(vals), 1)
        path = CL.values_path("Acme")
        self.assertTrue(path.exists())
        stored = CL.stored_values("Acme")
        self.assertEqual(stored[0]["value"], "ownership")
        self.assertEqual(stored[0]["source"], "user-provided text")

    def test_stored_values_merges_sibling_and_local_file(self):
        stub("culture_values",
             load_values=lambda company: [
                 {"value": "transparency", "quote": "q1", "source": "careers page"}])
        path = CL.values_path("Acme")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"company": "Acme",
                                    "values": [{"value": "Transparency",
                                                "quote": "q2",
                                                "source": "file"},
                                               {"value": "ownership",
                                                "quote": "q3",
                                                "source": "file"}]}))
        stored = CL.stored_values("Acme")
        names = [v["value"] for v in stored]
        self.assertEqual(names, ["transparency", "ownership"])  # dupe merged

    def test_extract_without_sibling_raises(self):
        with self.assertRaises(CL.CultureError):
            CL.extract_and_store_values("Acme", "some text")

    def test_prep_questions_delegates_to_sibling(self):
        stub("culture_values",
             load_values=lambda company: [
                 {"value": "transparency", "quote": "q", "source": "s"}],
             values_to_questions=lambda values: [
                 {"question": "Q?", "targets_value": v["value"],
                  "source": "culture_values"} for v in values])
        qs = CL.prep_questions_for("Acme")
        self.assertEqual(len(qs), 1)
        self.assertEqual(qs[0]["targets_value"], "transparency")

    def test_prep_questions_without_sibling_raises(self):
        with self.assertRaises(CL.CultureError):
            CL.prep_questions_for("Acme")

    def test_render_values_and_questions(self):
        vals = [{"value": "transparency", "quote": "We default to it.",
                 "source": "careers page"}]
        text = CL.render_values(vals, "Acme")
        self.assertIn("Stored values for Acme (1):", text)
        self.assertIn("transparency", text)
        self.assertIn("No stored values for Globex.", CL.render_values([], "Globex"))
        qs = [{"question": "Tell me about transparency.",
               "targets_value": "transparency", "source": "culture_values"}]
        qtext = CL.render_questions(qs, "Acme")
        self.assertIn("targeting Acme's values (1)", qtext)
        self.assertIn("(targets: transparency)", qtext)


class CtxTest(CultureBase):
    def test_build_ctx_jobs_from_tracker(self):
        from candid import tracker as T
        rec = T.add("Acme", "Data Scientist", status="applied")
        meta_path = self.tmp / "job_meta.json"
        meta_path.write_text(json.dumps({str(rec["id"]): {
            "source": "arbeitnow", "source_url": "http://x",
            "match_score": 80, "jd_text": "We are remote-first."}}))
        ctx = CL.build_ctx("Acme")
        self.assertEqual(len(ctx["jobs"]), 1)
        job = ctx["jobs"][0]
        self.assertEqual(job["company"], "Acme")
        self.assertEqual(job["description"], "We are remote-first.")
        self.assertEqual(job["status"], "applied")
        self.assertEqual(ctx["datasets"]["jobs"], ctx["jobs"])
        self.assertEqual(len(ctx["tracker"]), 1)
        self.assertEqual(ctx["prep_bank"], [])

    def test_build_ctx_empty_company_is_empty(self):
        ctx = CL.build_ctx("Nobody Inc")
        self.assertEqual(ctx["jobs"], [])
        self.assertEqual(ctx["tracker"], [])

    def test_profile_card_uses_provided_ctx(self):
        stub("culture_signals",
             company_jd_signals=lambda company, jobs: {
                 "company": company, "job_count": len(jobs),
                 "workstyle": {}, "benefits": [], "flags": [],
                 "sources": ["test"]})
        ctx = {"jobs": [{"title": "x"}], "datasets": {"warn": None,
                                                      "lca": None, "jobs": []},
               "prep_bank": [], "debriefs": [], "tracker": []}
        card = CL.profile_card("Acme", ctx=ctx)
        sample = [s for s in card["signals"] if s["signal"] == "jd sample size"]
        self.assertEqual(sample[0]["value"], "1")


class CultureCLITest(CultureBase):
    def test_cli_profile_json(self):
        _all_stubs()
        out = self.run_cli(["culture", "profile", "--company", "Acme", "--json"])
        card = json.loads(out)
        self.assertEqual(card["company"], "Acme")
        self.assertIn("signals", card)
        self.assertIn("coverage", card)

    def test_cli_profile_human(self):
        _all_stubs()
        out = self.run_cli(["culture", "profile", "--company", "Acme"])
        self.assertIn("Culture profile: Acme", out)
        self.assertIn("value: transparency", out)

    def test_cli_compare(self):
        stub("culture_values",
             load_values=lambda company: [
                 {"value": "transparency", "quote": "q", "source": "s"}]
             if company == "Acme" else [])
        out = self.run_cli(["culture", "compare", "--a", "Acme", "--b", "Globex"])
        self.assertIn("Culture compare: Acme vs Globex", out)
        out_json = self.run_cli(["culture", "compare", "--a", "Acme",
                                 "--b", "Globex", "--json"])
        res = json.loads(out_json)
        self.assertEqual(set(res), {"a", "b", "shared_sources",
                                    "only_in_a", "only_in_b"})

    def test_cli_values_extract_and_show(self):
        stub("culture_values",
             load_values=lambda company: [],
             extract_values=lambda text, company, origin="user-provided text": [
                 {"value": "ownership", "quote": "Own it.", "source": origin}],
             values_to_questions=lambda values: [])
        out = self.run_cli(["culture", "values", "--company", "Acme",
                            "--text", "We value ownership."])
        self.assertIn("Stored 1 value(s) for Acme.", out)
        self.assertIn("ownership", out)

    def test_cli_values_show_empty(self):
        out = self.run_cli(["culture", "values", "--company", "Acme"])
        self.assertIn("No stored values for Acme.", out)

    def test_cli_values_from_file(self):
        stub("culture_values",
             load_values=lambda company: [],
             extract_values=lambda text, company, origin="user-provided text": [
                 {"value": "candor", "quote": text.strip(), "source": origin}],
             values_to_questions=lambda values: [])
        fpath = self.tmp / "values.txt"
        fpath.write_text("We prize candor in feedback.")
        out = self.run_cli(["culture", "values", "--company", "Acme",
                            "--from-file", str(fpath)])
        self.assertIn("Stored 1 value(s) for Acme.", out)
        self.assertIn("candor", out)

    def test_cli_prep_questions_json(self):
        stub("culture_values",
             load_values=lambda company: [
                 {"value": "transparency", "quote": "q", "source": "s"}],
             values_to_questions=lambda values: [
                 {"question": "Q?", "targets_value": "transparency",
                  "source": "culture_values"}])
        out = self.run_cli(["culture", "prep-questions", "--company",
                            "Acme", "--json"])
        qs = json.loads(out)
        self.assertEqual(qs[0]["targets_value"], "transparency")

    def test_cli_workstyle_benefits_flags(self):
        stub("culture_signals",
             company_jd_signals=lambda company, jobs: {
                 "company": company, "job_count": 2,
                 "workstyle": {"remote": "remote-first"},
                 "benefits": ["401k"], "flags": ["on-call"],
                 "sources": ["arbeitnow"]})
        for sec, expect in (("workstyle", "remote"),
                            ("benefits", "401k"), ("flags", "on-call")):
            out = self.run_cli(["culture", sec, "--company", "Acme"])
            self.assertIn(expect, out, sec)
        out = self.run_cli(["culture", "workstyle", "--company",
                            "Acme", "--json"])
        self.assertEqual(json.loads(out)["job_count"], 2)

    def test_cli_workstyle_missing_sibling(self):
        out = self.run_cli(["culture", "workstyle", "--company", "Acme"])
        self.assertIn("not available", out)

    def test_cli_process_missing_sibling(self):
        out = self.run_cli(["culture", "process", "--company", "Acme"])
        self.assertIn("not available", out)

    def test_cli_process_with_sibling(self):
        stub("culture_process",
             process_profile=lambda company, ctx: {
                 "company": company,
                 "stages": [{"stage": "onsite",
                             "evidence": [{"quote": "4 rounds",
                                           "source": "debrief"}]}],
                 "coverage": "", "note": ""})
        out = self.run_cli(["culture", "process", "--company", "Acme"])
        self.assertIn("Stage: onsite", out)
        self.assertIn("4 rounds", out)

    def test_cli_stability_missing_sibling_shows_note(self):
        out = self.run_cli(["culture", "stability", "--company", "Acme"])
        self.assertIn("no signals", out)
        self.assertIn("note: culture_stability module not available", out)

    def test_cli_stability_with_sibling(self):
        stub("culture_stability",
             stability=lambda company, datasets: [
                 {"signal": "layoffs", "value": "none reported",
                  "source": "warn data", "as_of": None, "note": ""}],
             trajectory=lambda company, datasets: [])
        out = self.run_cli(["culture", "trajectory", "--company", "Acme"])
        self.assertIn("no signals", out)  # trajectory stub is empty
        out = self.run_cli(["culture", "stability", "--company",
                            "Acme", "--json"])
        payload = json.loads(out)
        self.assertEqual(payload["signals"][0]["signal"], "layoffs")


if __name__ == "__main__":
    unittest.main()

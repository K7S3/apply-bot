"""Tests for the pre-submit quality gate (candid.gate).

Covers: all 17 checks and their severities, blocking vs warning
semantics, --strict promotion, exit codes, deadline validation,
JD-drift detection, keyword coverage, tracker integration (variant/cover-letter/gate
recording), profile set, and the `gate` CLI end to end.

Run: CANDID_DATA_DIR=/tmp/candid-test-gate python3 -m unittest tests.test_gate -v
"""
import os

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-gate"

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _profile(**kw):
    prof = {
        "name": "Test User",
        "location": "New York, NY",
        "headline": "Data Scientist",
        "email": "test@example.com",
        "phone": "+1 555-010-1234",
        "seniority": "mid",
        "years_experience": 4.0,
        "skills": ["python", "sql"],
        "experience": [
            {"title": "Data Scientist", "company": "Initech",
             "dates": "2023 - Present",
             "bullets": ["Built models with python", "Wrote SQL reports"]},
        ],
        "education": [],
    }
    prof.update(kw)
    return prof


def _resume_text(**kw):
    bits = {
        "name": "TEST USER",
        "email": "test@example.com",
        "phone": "+1 555-010-1234",
        "location": "New York, NY",
        "sections": ("SUMMARY", "EXPERIENCE", "EDUCATION", "SKILLS"),
    }
    bits.update(kw)
    secs = "\n\n".join(f"{s}\nSome content here." for s in bits["sections"])
    return (f"{bits['name']}\n{bits['email']} | {bits['phone']} | "
            f"{bits['location']}\n\n{secs}\n")


def _app(**kw):
    rec = {
        "id": 1, "company": "Acme", "role": "Data Scientist",
        "status": "saved", "deadline": "", "resume_variant": {},
        "cover_letter": {}, "match_score": None, "gate": {},
    }
    rec.update(kw)
    return rec


def _variant(**kw):
    v = {"tone": "concise", "length": "one-page",
         "jd_sha": "", "created_at": "2026-09-20",
         "chosen": True, "resume_text": _resume_text()}
    v.update(kw)
    return v


def _check_ids(result, severity):
    return [c["id"] for c in result["checks"] if c["severity"] == severity]


class _FsCase(unittest.TestCase):
    """Rebinds candid.config paths to a temp dir (full-suite safe).

    config.DATA_DIR and friends are bound at import time, so setting the
    env var in this module is too late when the whole suite runs (another
    module is imported first). Rebinding the path constants per test is
    the pattern the other FS-touching test modules use.
    """

    PATH_ATTRS = ("DATA_DIR", "TRACKER_PATH", "PROFILE_PATH", "TAILOR_DIR",
                  "PREP_PACKS_DIR", "SALARY_DB", "OFFERS_PATH",
                  "GMAIL_PROPOSALS_PATH")

    def setUp(self):
        import json
        import tempfile
        from candid import config as C
        self._tmp = Path(tempfile.mkdtemp(prefix="candid-test-gate-"))
        self._saved = {name: getattr(C, name) for name in self.PATH_ATTRS}
        C.DATA_DIR = self._tmp
        C.TRACKER_PATH = self._tmp / "tracker.json"
        C.PROFILE_PATH = self._tmp / "profile.json"
        C.TAILOR_DIR = self._tmp / "tailored"
        C.PREP_PACKS_DIR = self._tmp / "prep_packs"
        C.SALARY_DB = self._tmp / "salary.db"
        C.OFFERS_PATH = self._tmp / "offers.json"
        C.GMAIL_PROPOSALS_PATH = self._tmp / "gmail_proposals.json"
        C.ensure_data_dirs()
        C.PROFILE_PATH.write_text(json.dumps(_profile()), encoding="utf-8")

    def tearDown(self):
        import shutil
        from candid import config as C
        for name, val in self._saved.items():
            setattr(C, name, val)
        shutil.rmtree(self._tmp, ignore_errors=True)


class AlreadySubmittedTest(unittest.TestCase):
    def test_applied_status_blocks(self):
        from candid import gate as G
        res = G.run_gate(_app(status="applied"), _profile())
        self.assertEqual(res["verdict"], "BLOCK")
        self.assertIn("already_submitted", res["blocks"])

    def test_saved_status_ok(self):
        from candid import gate as G
        res = G.run_gate(_app(), _profile())
        sev = {c["id"]: c["severity"] for c in res["checks"]}
        self.assertEqual(sev["already_submitted"], "ok")


class VariantChecksTest(unittest.TestCase):
    def test_no_variant_blocks(self):
        from candid import gate as G
        res = G.run_gate(_app(), _profile())
        self.assertIn("tailored_resume", res["blocks"])

    def test_variant_recorded_but_not_chosen_blocks(self):
        from candid import gate as G
        res = G.run_gate(_app(resume_variant=_variant(chosen=False)), _profile())
        self.assertIn("variant_chosen", res["blocks"])
        self.assertNotIn("tailored_resume", res["blocks"])

    def test_variant_chosen_ok(self):
        from candid import gate as G
        res = G.run_gate(_app(resume_variant=_variant()), _profile())
        sev = {c["id"]: c["severity"] for c in res["checks"]}
        self.assertEqual(sev["variant_chosen"], "ok")


class JdFreshnessTest(unittest.TestCase):
    def test_jd_drift_warns(self):
        from candid import gate as G
        old_sha = G.jd_sha("old jd text")
        v = _variant(jd_sha=old_sha)
        res = G.run_gate(_app(resume_variant=v), _profile(), jd_text="new jd text")
        self.assertIn("jd_freshness", res["warnings"])

    def test_jd_same_ok(self):
        from candid import gate as G
        jd = "the exact jd"
        res = G.run_gate(_app(resume_variant=_variant(jd_sha=G.jd_sha(jd))),
                         _profile(), jd_text=jd)
        sev = {c["id"]: c["severity"] for c in res["checks"]}
        self.assertEqual(sev["jd_freshness"], "ok")

    def test_no_jd_skips(self):
        from candid import gate as G
        res = G.run_gate(_app(resume_variant=_variant()), _profile())
        sev = {c["id"]: c["severity"] for c in res["checks"]}
        self.assertEqual(sev["jd_freshness"], "ok")

    def test_jd_sha_stable(self):
        from candid import gate as G
        self.assertEqual(G.jd_sha("abc"), G.jd_sha("abc"))
        self.assertNotEqual(G.jd_sha("abc"), G.jd_sha("abd"))


class AtsChecksTest(unittest.TestCase):
    def _run(self, text, **kw):
        from candid import gate as G
        return G.run_gate(_app(resume_variant=_variant(resume_text=text)),
                          _profile(), **kw)

    def test_clean_resume_ats_ok(self):
        res = self._run(_resume_text())
        sev = {c["id"]: c["severity"] for c in res["checks"]}
        for cid in ("ats_email", "ats_phone", "ats_name", "ats_sections",
                    "ats_tables", "ats_length"):
            self.assertEqual(sev[cid], "ok", cid)

    def test_missing_email_blocks(self):
        res = self._run(_resume_text(email=""))
        self.assertIn("ats_email", res["blocks"])

    def test_missing_phone_warns(self):
        res = self._run(_resume_text(phone=""))
        self.assertIn("ats_phone", res["warnings"])

    def test_missing_sections_warns(self):
        res = self._run(_resume_text(sections=("SUMMARY", "EXPERIENCE")))
        self.assertIn("ats_sections", res["warnings"])

    def test_pipe_tables_block(self):
        text = _resume_text() + "\n| a | b |\n| c | d |\n"
        res = self._run(text)
        self.assertIn("ats_tables", res["blocks"])

    def test_very_long_resume_warns(self):
        res = self._run(_resume_text() + "x" * 9000)
        self.assertIn("ats_length", res["warnings"])

    def test_no_resume_text_blocks(self):
        from candid import gate as G
        res = G.run_gate(_app(resume_variant=_variant(resume_text="")), _profile())
        self.assertIn("ats_clean", res["blocks"])


class DeadlineCheckTest(unittest.TestCase):
    def _run(self, deadline, **kw):
        from candid import gate as G
        return G.run_gate(_app(deadline=deadline), _profile(),
                          today=date(2026, 9, 22), **kw)

    def test_no_deadline_warns(self):
        res = self._run("")
        self.assertIn("deadline", res["warnings"])

    def test_future_deadline_ok(self):
        res = self._run("2026-10-15")
        sev = {c["id"]: c["severity"] for c in res["checks"]}
        self.assertEqual(sev["deadline"], "ok")

    def test_past_deadline_blocks(self):
        res = self._run("2026-09-01")
        self.assertIn("deadline", res["blocks"])

    def test_near_deadline_warns(self):
        soon = (date(2026, 9, 22) + timedelta(days=2)).isoformat()
        res = self._run(soon)
        self.assertIn("deadline", res["warnings"])

    def test_invalid_deadline_blocks(self):
        res = self._run("not-a-date")
        self.assertIn("deadline", res["blocks"])


class ContactCheckTest(unittest.TestCase):
    def test_missing_email_blocks(self):
        from candid import gate as G
        res = G.run_gate(_app(), _profile(email=""))
        self.assertIn("contact_email", res["blocks"])

    def test_missing_phone_warns(self):
        from candid import gate as G
        res = G.run_gate(_app(), _profile(phone=""))
        self.assertIn("contact_phone", res["warnings"])

    def test_missing_location_warns(self):
        from candid import gate as G
        res = G.run_gate(_app(), _profile(location=""))
        self.assertIn("contact_location", res["warnings"])


class MatchFloorTest(unittest.TestCase):
    def test_stored_score_below_floor_warns(self):
        from candid import gate as G
        res = G.run_gate(_app(match_score=10.0), _profile())
        self.assertIn("match_floor", res["warnings"])

    def test_stored_score_above_floor_ok(self):
        from candid import gate as G
        res = G.run_gate(_app(match_score=90.0), _profile())
        sev = {c["id"]: c["severity"] for c in res["checks"]}
        self.assertEqual(sev["match_floor"], "ok")

    def test_no_score_skips(self):
        from candid import gate as G
        res = G.run_gate(_app(), _profile())
        sev = {c["id"]: c["severity"] for c in res["checks"]}
        self.assertEqual(sev["match_floor"], "ok")

    def test_live_jd_scores(self):
        from candid import gate as G
        jd = "We need python and sql for this data role."
        res = G.run_gate(_app(), _profile(), jd_text=jd)
        sev = {c["id"]: c["severity"] for c in res["checks"]}
        self.assertIn(sev["match_floor"], ("ok", "warn"))


class CoverLetterTest(unittest.TestCase):
    def test_missing_cover_letter_warns(self):
        from candid import gate as G
        res = G.run_gate(_app(), _profile())
        self.assertIn("cover_letter", res["warnings"])

    def test_recorded_cover_letter_ok(self):
        from candid import gate as G
        res = G.run_gate(
            _app(cover_letter={"text": "Dear ...", "created_at": "2026-09-20"}),
            _profile())
        sev = {c["id"]: c["severity"] for c in res["checks"]}
        self.assertEqual(sev["cover_letter"], "ok")


class KeywordCoverageTest(unittest.TestCase):
    JD = ("We are hiring a Senior Data Scientist. You will build models with "
          "python and scikit-learn, write SQL queries against Snowflake, and "
          "deploy with docker and kubernetes on AWS.")
    RESUME_GOOD = ("TEST USER\ntest@example.com\n\nSUMMARY\nData scientist.\n\n"
                   "EXPERIENCE\nBuilt models with python and scikit-learn. "
                   "Wrote SQL queries.\n\nEDUCATION\nBS\n\nSKILLS\npython, sql\n")
    RESUME_THIN = ("TEST USER\ntest@example.com\n\nSUMMARY\nAnalyst.\n\n"
                   "EXPERIENCE\nMade dashboards.\n\nEDUCATION\nBS\n\n"
                   "SKILLS\nexcel\n")

    def test_no_jd_skips(self):
        from candid import gate as G
        res = G.run_gate(_app(resume_variant=_variant()), _profile())
        sev = {c["id"]: c["severity"] for c in res["checks"]}
        self.assertEqual(sev["keyword_coverage"], "ok")

    def test_no_resume_text_skips(self):
        from candid import gate as G
        res = G.run_gate(_app(), _profile(), jd_text=self.JD)
        sev = {c["id"]: c["severity"] for c in res["checks"]}
        self.assertEqual(sev["keyword_coverage"], "ok")

    def test_low_coverage_warns(self):
        from candid import gate as G
        app = _app(resume_variant=_variant(resume_text=self.RESUME_THIN))
        res = G.run_gate(app, _profile(), jd_text=self.JD)
        self.assertIn("keyword_coverage", res["warnings"])
        msg = next(c["message"] for c in res["checks"]
                   if c["id"] == "keyword_coverage")
        self.assertIn("Missing:", msg)

    def test_good_coverage_ok(self):
        from candid import gate as G
        app = _app(resume_variant=_variant(resume_text=self.RESUME_GOOD))
        res = G.run_gate(app, _profile(), jd_text=self.JD)
        sev = {c["id"]: c["severity"] for c in res["checks"]}
        self.assertEqual(sev["keyword_coverage"], "ok")

    def test_threshold_is_tunable(self):
        from candid import gate as G
        app = _app(resume_variant=_variant(resume_text=self.RESUME_GOOD))
        # 3/5 = 60% coverage: ok at 0.5, warn at 0.9
        res = G.run_gate(app, _profile(), jd_text=self.JD,
                         keyword_coverage_warn_below=0.9)
        self.assertIn("keyword_coverage", res["warnings"])

    def test_helper_shared_with_tailor(self):
        from candid import tailor as TL
        cov = TL.keyword_coverage(self.RESUME_GOOD, self.JD)
        self.assertEqual(cov["total"], 5)
        self.assertAlmostEqual(cov["coverage"], 0.6)


class VerdictTest(unittest.TestCase):
    def _full_pass(self):
        from candid import gate as G
        app = _app(deadline="2026-10-15",
                   resume_variant=_variant(),
                   cover_letter={"text": "Dear ..."},
                   match_score=90.0)
        return G.run_gate(app, _profile())

    def test_full_pass(self):
        res = self._full_pass()
        self.assertEqual(res["verdict"], "PASS")
        self.assertEqual(res["blocks"], [])
        self.assertEqual(res["warnings"], [])
        self.assertEqual(res["passed"], res["total"])

    def test_strict_promotes_warnings(self):
        from candid import gate as G
        app = _app(resume_variant=_variant(), cover_letter={},
                   match_score=90.0, deadline="2026-10-15")
        res = G.run_gate(app, _profile())
        self.assertEqual(res["verdict"], "WARN")
        strict = G.run_gate(app, _profile(), strict=True)
        self.assertEqual(strict["verdict"], "BLOCK")
        self.assertTrue(strict["strict"])

    def test_exit_codes(self):
        from candid import gate as G
        self.assertEqual(G.verdict_exit_code("PASS"), 0)
        self.assertEqual(G.verdict_exit_code("WARN"), 1)
        self.assertEqual(G.verdict_exit_code("BLOCK"), 2)

    def test_summarize_and_render(self):
        from candid import gate as G
        res = self._full_pass()
        s = G.summarize(res)
        self.assertIn("PASS", s)
        self.assertIn("17/17", s)
        report = G.render_report(res, company="Acme", role="Data Scientist")
        self.assertIn("Pre-submit gate", report)
        self.assertIn("Ready to submit", report)

    def test_render_blocked(self):
        from candid import gate as G
        res = G.run_gate(_app(), _profile())
        report = G.render_report(res)
        self.assertIn("BLOCKED", report)
        self.assertIn("fix:", report)


class TrackerIntegrationTest(_FsCase):
    def test_deadline_validation(self):
        from candid import tracker as T
        self.assertEqual(T.validate_deadline("2026-10-15"), "2026-10-15")
        self.assertEqual(T.validate_deadline(""), "")
        with self.assertRaises(T.TrackerError):
            T.validate_deadline("15/10/2026")

    def test_add_with_deadline(self):
        from candid import tracker as T
        rec = T.add("Acme", "Data Scientist", deadline="2026-10-15")
        self.assertEqual(rec["deadline"], "2026-10-15")
        self.assertEqual(rec["resume_variant"], {})
        self.assertEqual(rec["gate"], {})

    def test_update_deadline(self):
        from candid import tracker as T
        rec = T.add("Acme", "Data Scientist")
        T.update(rec["id"], deadline="2026-11-01")
        self.assertEqual(T.list_apps()[0]["deadline"], "2026-11-01")
        T.update(rec["id"], deadline="")
        self.assertEqual(T.list_apps()[0]["deadline"], "")

    def test_update_match_score_validation(self):
        from candid import tracker as T
        rec = T.add("Acme", "Data Scientist")
        T.update(rec["id"], match_score=72.5)
        self.assertEqual(T.list_apps()[0]["match_score"], 72.5)
        with self.assertRaises(T.TrackerError):
            T.update(rec["id"], match_score=150)

    def test_record_variant_and_choose(self):
        from candid import tracker as T
        rec = T.add("Acme", "Data Scientist")
        T.record_variant(rec["id"], tone="concise", length="one-page",
                         jd_text="python", resume_text=_resume_text())
        v = T.list_apps()[0]["resume_variant"]
        self.assertEqual(v["tone"], "concise")
        self.assertFalse(v["chosen"])
        T.update(rec["id"], variant_chosen=True)
        self.assertTrue(T.list_apps()[0]["resume_variant"]["chosen"])

    def test_variant_chosen_without_variant_errors(self):
        from candid import tracker as T
        rec = T.add("Acme", "Data Scientist")
        with self.assertRaises(T.TrackerError):
            T.update(rec["id"], variant_chosen=True)

    def test_record_cover_letter(self):
        from candid import tracker as T
        rec = T.add("Acme", "Data Scientist")
        T.record_cover_letter(rec["id"], text="Dear hiring manager")
        cl = T.list_apps()[0]["cover_letter"]
        self.assertTrue(cl["text"].startswith("Dear"))

    def test_record_gate_result(self):
        from candid import tracker as T
        from candid import gate as G
        rec = T.add("Acme", "Data Scientist", deadline="2026-10-15")
        T.record_variant(rec["id"], tone="concise", length="one-page",
                         jd_text="x", resume_text=_resume_text(), chosen=True)
        T.record_cover_letter(rec["id"], text="Dear ...")
        result = G.run_gate(T.list_apps()[0], _profile(),
                            today=date(2026, 9, 22))
        T.record_gate_result(rec["id"], result)
        g = T.list_apps()[0]["gate"]
        self.assertEqual(g["verdict"], result["verdict"])
        self.assertEqual(g["passed"], result["passed"])


class ProfileSetTest(_FsCase):
    def test_update_fields(self):
        from candid import profile as P
        prof = P.update_fields({"email": "new@example.com"})
        self.assertEqual(prof["email"], "new@example.com")
        self.assertEqual(P.load_profile()["email"], "new@example.com")

    def test_update_rejects_unknown_fields(self):
        from candid import profile as P
        with self.assertRaises(P.OnboardError):
            P.update_fields({"skills": ["go"]})


class GateCliTest(_FsCase):
    def _run_cli(self, *argv):
        import io
        from contextlib import redirect_stdout
        from candid import __main__ as CLI
        buf = io.StringIO()
        code = 0
        with redirect_stdout(buf):
            try:
                CLI.main(list(argv))
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
        return code, buf.getvalue()

    def _seed_passing_app(self):
        from candid import tracker as T
        rec = T.add("Acme", "Data Scientist", deadline="2026-12-31")
        T.record_variant(rec["id"], tone="concise", length="one-page",
                         jd_text="x", resume_text=_resume_text(), chosen=True)
        T.record_cover_letter(rec["id"], text="Dear hiring manager")
        T.update(rec["id"], match_score=90.0)
        return rec

    def test_gate_cli_pass_exit_zero(self):
        rec = self._seed_passing_app()
        code, out = self._run_cli("gate", "--app-id", str(rec["id"]))
        self.assertEqual(code, 0, out)
        self.assertIn("PASS", out)

    def test_gate_cli_block_exit_two(self):
        from candid import tracker as T
        rec = T.add("Beta", "Analyst")  # nothing tailored -> blocks
        code, out = self._run_cli("gate", "--app-id", str(rec["id"]))
        self.assertEqual(code, 2, out)
        self.assertIn("BLOCK", out)

    def test_gate_cli_json(self):
        import json
        rec = self._seed_passing_app()
        code, out = self._run_cli("gate", "--app-id", str(rec["id"]), "--json")
        self.assertEqual(code, 0, out)
        payload = json.loads(out)
        self.assertEqual(payload["verdict"], "PASS")

    def test_gate_cli_unknown_app(self):
        code, out = self._run_cli("gate", "--app-id", "999")
        self.assertNotEqual(code, 0)

    def test_gate_cli_company_role_lookup(self):
        rec = self._seed_passing_app()
        code, out = self._run_cli("gate", "--company", "Acme",
                                  "--role", "Data Scientist")
        self.assertEqual(code, 0, out)
        self.assertIn("PASS", out)

    def test_gate_stamps_tracker(self):
        from candid import tracker as T
        rec = self._seed_passing_app()
        self._run_cli("gate", "--app-id", str(rec["id"]))
        g = T.list_apps()[0]["gate"]
        self.assertEqual(g["verdict"], "PASS")
        self.assertTrue(g["ran_at"])
        self.assertEqual(g["gate_version"], 2)
        self.assertEqual(g["total"], 17)

    def test_track_update_gate_blocks_status_change(self):
        from candid import tracker as T
        rec = T.add("Gamma", "Analyst")  # no variant -> gate blocks
        code, out = self._run_cli("track", "update", str(rec["id"]),
                                  "--status", "applied", "--gate")
        self.assertEqual(code, 2, out)
        self.assertEqual(T.list_apps()[0]["status"], "saved")

    def test_track_update_gate_force_overrides(self):
        from candid import tracker as T
        rec = T.add("Gamma", "Analyst")
        code, out = self._run_cli("track", "update", str(rec["id"]),
                                  "--status", "applied", "--gate", "--force")
        self.assertEqual(code, 0, out)
        self.assertEqual(T.list_apps()[0]["status"], "applied")

    def test_tailor_records_variant_with_choose(self):
        jd_file = self._tmp / "jd.txt"
        jd_file.write_text(
            "We are hiring a data scientist. You will use python and sql daily "
            "to build models, write reports, and partner with product teams.")
        from candid import tracker as T
        rec = T.add("Delta", "Data Scientist")
        code, out = self._run_cli("tailor", "resume", "--jd", str(jd_file),
                                  "--app-id", str(rec["id"]), "--choose")
        self.assertEqual(code, 0, out)
        v = T.list_apps()[0]["resume_variant"]
        self.assertTrue(v["chosen"])
        self.assertTrue(v["resume_text"])

    def test_profile_set_cli(self):
        code, out = self._run_cli("profile", "set", "--email", "cli@example.com")
        self.assertEqual(code, 0, out)
        from candid import profile as P
        self.assertEqual(P.load_profile()["email"], "cli@example.com")

    def test_track_update_gate_allows_clean_apply(self):
        # Regression: gating used to run against the *prospective* record,
        # whose target status "applied" counts as submitted, so a clean
        # application could never pass `track update --status applied --gate`.
        from candid import tracker as T
        rec = self._seed_passing_app()
        code, out = self._run_cli("track", "update", str(rec["id"]),
                                  "--status", "applied", "--gate")
        self.assertEqual(code, 0, out)
        self.assertEqual(T.list_apps()[0]["status"], "applied")

    def test_jd_stdin_matches_file_hash(self):
        # Regression: the same JD fed via --jd <file> vs --jd - (stdin)
        # must hash identically, or jd_freshness warns spuriously.
        import io
        import json
        from unittest import mock
        from candid import tracker as T
        jd_file = self._tmp / "jd.txt"
        jd_file.write_text("We are hiring a data scientist. You will use "
                           "python and sql daily.\n")
        rec = T.add("Epsilon", "Data Scientist", deadline="2026-12-31")
        T.record_variant(rec["id"], tone="concise", length="one-page",
                         jd_text=jd_file.read_text().strip(),  # as _jd_text feeds it
                         resume_text=_resume_text(), chosen=True)
        T.record_cover_letter(rec["id"], text="Dear hiring manager")
        T.update(rec["id"], match_score=90.0)

        def freshness(*argv):
            # exit code may be 1 (other warnings); we only care about
            # the jd_freshness check's severity here
            _, out = self._run_cli("gate", "--app-id", str(rec["id"]),
                                   "--json", *argv)
            sev = {c["id"]: c["severity"]
                   for c in json.loads(out)["checks"]}
            return sev["jd_freshness"]

        self.assertEqual(freshness("--jd", str(jd_file)), "ok")
        with mock.patch("sys.stdin", io.StringIO(jd_file.read_text() + "\n")):
            self.assertEqual(freshness("--jd", "-"), "ok")


if __name__ == "__main__":
    unittest.main()

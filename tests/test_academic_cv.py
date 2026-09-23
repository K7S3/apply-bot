"""Tests for the academic-CV export and research-statement generator.

Run: python -m unittest tests.test_academic_cv -v   (from repo root)

No network. Uses a temporary CANDID data dir via patched C.PROFILE_PATH.
"""
import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _full_profile() -> dict:
    return {
        "name": "Alex Rivera",
        "headline": "ML researcher & engineer",
        "location": "New York, NY",
        "summary": "Research on efficient training of large language models.",
        "skills": ["python", "pytorch", "distributed training"],
        "experience": [
            {
                "title": "Research Scientist",
                "company": "Meridian AI Lab",
                "dates": "2022 - Present",
                "bullets": [
                    "Rebuilt the flux capacitor pipeline, cutting training cost by 40%.",
                    "Led a 4-person team on sparse attention kernels.",
                ],
            },
            {
                "title": "Research Intern",
                "company": "Northwind Labs",
                "dates": "Summer 2021",
                "bullets": ["Prototyped retrieval-augmented QA over 10M docs."],
            },
        ],
        "education": [
            {"school": "State University", "degree": "Ph.D. Computer Science", "dates": "2018 - 2022"},
            {"school": "City College", "degree": "B.S. Mathematics", "dates": "2014 - 2018"},
        ],
        "publications": [
            {"authors": "A. Rivera, B. Chen", "title": "Sparse attention at scale",
             "venue": "Proc. of MLConf", "year": "2023"},
            "A. Rivera. Notes on efficient optimizers. arXiv:2301.00001. 2023.",
        ],
        "projects": [
            {"name": "open-kernels", "description": "CUDA kernels for sparse attention, 2k stars."},
        ],
        "teaching": [
            "TA, Deep Learning (CS 542), State University, Fall 2020.",
        ],
        "grants": [
            "NSF Graduate Research Fellowship, 2019 - 2022.",
        ],
        "service": [
            "Reviewer, MLConf 2023-2024.",
        ],
        "years_experience": 4.0,
        "seniority": "mid",
    }


def _minimal_profile() -> dict:
    return {
        "name": "Alex Rivera",
        "headline": "Software engineer",
        "location": "New York, NY",
        "summary": "Backend engineer.",
        "skills": ["python"],
        "experience": [
            {"title": "Software Engineer", "company": "Acme", "dates": "2023 - Present",
             "bullets": ["Shipped the billing service."]},
        ],
        "education": [],
        "years_experience": 3.0,
        "seniority": "mid",
    }


def _special_chars_profile() -> dict:
    p = _minimal_profile()
    p["experience"][0]["company"] = "R&D Labs %100"
    p["experience"][0]["bullets"] = ["Cut cost 50% & raised throughput $2M/yr; handled a_b, c#d {e} ~f^g."]
    return p


class AcademicCvBuildTest(unittest.TestCase):
    def setUp(self):
        from candid import academic_cv as AC
        self.AC = AC

    def test_full_profile_has_all_sections(self):
        cv = self.AC.build_academic_cv(_full_profile())
        self.assertEqual(cv["name"], "Alex Rivera")
        self.assertEqual(len(cv["education"]), 2)
        self.assertEqual(len(cv["appointments"]), 2)
        self.assertEqual(cv["appointments"][0]["organization"], "Meridian AI Lab")
        self.assertEqual(len(cv["publications"]), 2)
        self.assertIn("Sparse attention at scale", cv["publications"][0])
        self.assertEqual(len(cv["teaching"]), 1)
        self.assertEqual(len(cv["grants"]), 1)
        self.assertEqual(len(cv["service"]), 1)
        self.assertIn("pytorch", cv["skills"])

    def test_minimal_profile_omits_optional_sections(self):
        cv = self.AC.build_academic_cv(_minimal_profile())
        for key in ("publications", "teaching", "grants", "service"):
            self.assertNotIn(key, cv, f"optional section {key!r} must be omitted, not empty")
        self.assertEqual(len(cv["appointments"]), 1)
        self.assertEqual(cv["education"], [])

    def test_empty_lists_also_omitted(self):
        prof = _full_profile()
        prof["publications"] = []
        prof["teaching"] = []
        cv = self.AC.build_academic_cv(prof)
        self.assertNotIn("publications", cv)
        self.assertNotIn("teaching", cv)
        self.assertIn("grants", cv)  # non-empty ones stay

    def test_publications_accept_strings_and_dicts(self):
        prof = _minimal_profile()
        prof["publications"] = [
            "Doe, J. A paper. Some Venue. 2020.",
            {"title": "Another paper", "venue": "Conf", "year": "2021", "authors": "J. Doe"},
        ]
        cv = self.AC.build_academic_cv(prof)
        self.assertEqual(len(cv["publications"]), 2)
        self.assertIn("Another paper", cv["publications"][1])


class LatexEscapeTest(unittest.TestCase):
    def setUp(self):
        from candid import academic_cv as AC
        self.AC = AC

    def test_special_chars_escaped(self):
        cv = self.AC.build_academic_cv(_special_chars_profile())
        tex = self.AC.export_latex(cv)
        self.assertIn(r"R\&D Labs \%100", tex)
        self.assertIn(r"50\% \&", tex)
        self.assertIn(r"\$2M", tex)
        self.assertIn(r"a\_b", tex)
        self.assertIn(r"c\#d", tex)
        self.assertIn(r"\{e\}", tex)
        self.assertIn(r"\textasciitilde{}f\textasciicircum{}g", tex)
        # no raw unescaped specials may survive in the rendered item line
        line = next(l for l in tex.splitlines() if "R\\&D" in l)
        import re
        # strip the escaped sequences, then no special chars should remain
        stripped = line
        for seq in (r"\&", r"\%", r"\$", r"\#", r"\_", r"\{", r"\}",
                    r"\textasciitilde{}", r"\textasciicircum{}", r"\textbackslash{}"):
            stripped = stripped.replace(seq, "")
        self.assertNotRegex(stripped, r"[&%$#_~^]")

    def test_ascii_safe(self):
        prof = _minimal_profile()
        prof["name"] = "Zoë M\u00fcller \u2014 researcher"
        tex = self.AC.export_latex(self.AC.build_academic_cv(prof))
        tex.encode("ascii")  # must not raise

    def test_balanced_braces(self):
        for prof in (_full_profile(), _minimal_profile(), _special_chars_profile()):
            tex = self.AC.export_latex(self.AC.build_academic_cv(prof))
            self.assertEqual(tex.count("{"), tex.count("}"),
                             "LaTeX braces must balance")
            self.assertIn(r"\begin{document}", tex)
            self.assertIn(r"\end{document}", tex)

    def test_minimal_latex_has_no_optional_sections(self):
        tex = self.AC.export_latex(self.AC.build_academic_cv(_minimal_profile()))
        for title in ("Publications", "Teaching", "Grants and Service"):
            self.assertNotIn(title, tex)


class TextExportTest(unittest.TestCase):
    def test_text_export_renders(self):
        from candid import academic_cv as AC
        txt = AC.export_text(AC.build_academic_cv(_full_profile()))
        self.assertIn("Alex Rivera", txt)
        self.assertIn("PUBLICATIONS", txt)
        self.assertIn("TEACHING", txt)
        self.assertIn("GRANTS & SERVICE", txt)
        txt_min = AC.export_text(AC.build_academic_cv(_minimal_profile()))
        self.assertNotIn("PUBLICATIONS", txt_min)


class ResearchStatementTest(unittest.TestCase):
    def setUp(self):
        from candid import research_statement as RS
        self.RS = RS

    def test_past_research_grounded_in_profile(self):
        st = self.RS.build_statement(_full_profile())
        texts = [i["text"] for i in st["past_research"]]
        joined = " ".join(texts)
        # verbatim profile content must appear
        self.assertIn("flux capacitor pipeline", joined)
        self.assertIn("Sparse attention at scale", joined)
        self.assertIn("open-kernels", joined)
        self.assertIn("retrieval-augmented QA", joined)
        # every bullet cites its source
        for item in st["past_research"]:
            self.assertTrue(item["source"], "each past-research item needs a source tag")

    def test_zero_invented_claims(self):
        st = self.RS.build_statement(_minimal_profile())
        md = self.RS.render_markdown(st)
        # nothing invented: no publication titles the profile lacks
        self.assertNotIn("Sparse attention", md)
        self.assertNotIn("Quantum", md)
        self.assertNotIn("Hypernet", md)
        # scaffold TODOs present and unfilled
        self.assertGreaterEqual(len(st["scaffold"]), 3)
        for item in st["scaffold"]:
            self.assertEqual(item["marker"], "TODO: personalize")
            self.assertIn("TODO: personalize", md)
        # scaffold prompts are generic questions, not invented plans
        for item in st["scaffold"]:
            self.assertNotIn("flux capacitor", item["prompt"])
            self.assertNotIn("Acme", item["prompt"])

    def test_current_direction_grounded(self):
        st = self.RS.build_statement(_full_profile())
        self.assertIn("Meridian AI Lab", st["current_direction"])
        self.assertIn("pytorch", st["current_direction"])

    def test_lab_pi_tailoring(self):
        st = self.RS.build_statement(_full_profile(), lab="Vision Lab", pi="Dr. Rao")
        self.assertIn("Vision Lab", st["framing"])
        self.assertIn("Dr. Rao", st["framing"])
        st2 = self.RS.build_statement(_full_profile())
        self.assertNotIn("Vision Lab", st2["framing"])

    def test_render_markdown_structure(self):
        md = self.RS.render_markdown(self.RS.build_statement(_full_profile()))
        self.assertIn("# Research Statement", md)
        self.assertIn("## Past Research", md)
        self.assertIn("## Current Direction", md)
        self.assertIn("## Future Directions", md)
        self.assertIn("SCAFFOLD", md)


class CliWiringTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        from candid import config as C
        self.C = C
        self.orig = C.PROFILE_PATH
        C.PROFILE_PATH = Path(self.td.name) / "profile.json"
        C.PROFILE_PATH.write_text(json.dumps(_full_profile()), encoding="utf-8")
        self.addCleanup(self._restore)

    def _restore(self):
        self.C.PROFILE_PATH = self.orig
        self.td.cleanup()

    def _parser(self, module):
        p = argparse.ArgumentParser(prog="candid")
        module.add_parsers(p.add_subparsers(dest="cmd"))
        return p

    def test_academic_cv_parsers_register(self):
        from candid import academic_cv as AC
        p = self._parser(AC)
        a = p.parse_args(["academic-cv", "--tex", "cv.tex"])
        self.assertEqual(a.tex, "cv.tex")
        self.assertFalse(a.text)
        a = p.parse_args(["academic-cv", "--text"])
        self.assertTrue(a.text)
        self.assertTrue(callable(a.func))

    def test_research_statement_parsers_register(self):
        from candid import research_statement as RS
        p = self._parser(RS)
        a = p.parse_args(["research-statement", "--lab", "Vision Lab", "--pi", "Dr. Rao",
                          "--out", "stmt.md"])
        self.assertEqual(a.lab, "Vision Lab")
        self.assertEqual(a.pi, "Dr. Rao")
        self.assertEqual(a.out, "stmt.md")
        self.assertTrue(callable(a.func))

    def test_academic_cv_cmd_writes_tex(self):
        from candid import academic_cv as AC
        out = Path(self.td.name) / "cv.tex"
        ns = argparse.Namespace(tex=str(out), text=False)
        AC.cmd_academic_cv(ns)
        tex = out.read_text(encoding="utf-8")
        self.assertIn(r"\begin{document}", tex)
        self.assertIn("Meridian AI Lab", tex)

    def test_research_statement_cmd_writes_md(self):
        from candid import research_statement as RS
        out = Path(self.td.name) / "stmt.md"
        ns = argparse.Namespace(lab="Vision Lab", pi="Dr. Rao", out=str(out))
        RS.cmd_research_statement(ns)
        md = out.read_text(encoding="utf-8")
        self.assertIn("Vision Lab", md)
        self.assertIn("TODO: personalize", md)


if __name__ == "__main__":
    unittest.main()

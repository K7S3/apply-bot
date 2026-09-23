"""Tests for the match-boost workstream: skills normalizer + GitHub project matcher.

Covers:
  - candid.skills: alias normalization both directions, no false positives
    from short/common words ("go", "cv"), unknown terms unchanged, the
    alias JSON file loads.
  - match scoring with aliases applied (JD "k8s" vs profile "Kubernetes"
    and vice versa; aliases only add matches, never remove).
  - candid.github_projects: keyword extraction from fixture JSON (no
    network), best_project_for_jd overlap ranking, cache save/load,
    refresh semantics, graceful offline fallback.
  - CLI smoke tests: `profile github` (with the API mocked), `match`
    gaining the "most relevant project" line, error paths ending with
    the exact next command.

No network access anywhere in this file: the GitHub API is mocked.
Fictional usernames/repos only — nothing real, nothing personal.
"""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-match-boost")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402

# Fictional GitHub API fixture: shapes mirror the real API response, but
# every name is invented for tests.
FIXTURE_REPOS = [
    {
        "name": "k8s-deploy-helper",
        "full_name": "fixture-dev/k8s-deploy-helper",
        "description": "A tiny helper that rolls out containers to Kubernetes clusters",
        "html_url": "https://github.com/fixture-dev/k8s-deploy-helper",
        "language": "Python",
        "topics": ["kubernetes", "devops", "docker"],
        "stargazers_count": 12,
        "updated_at": "2026-08-01T10:00:00Z",
    },
    {
        "name": "bread-recipes",
        "full_name": "fixture-dev/bread-recipes",
        "description": "My sourdough experiments and baking notes",
        "html_url": "https://github.com/fixture-dev/bread-recipes",
        "language": "Markdown",
        "topics": ["baking"],
        "stargazers_count": 3,
        "updated_at": "2026-07-01T10:00:00Z",
    },
    {
        "name": "ts-dashboard",
        "full_name": "fixture-dev/ts-dashboard",
        "description": "Analytics dashboard in TypeScript and React",
        "html_url": "https://github.com/fixture-dev/ts-dashboard",
        "language": "TypeScript",
        "topics": ["react", "visualization"],
        "stargazers_count": 30,
        "updated_at": "2026-09-01T10:00:00Z",
    },
]


def _mini_profile(**kw):
    prof = {
        "name": "Test User",
        "location": "New York, NY",
        "headline": "Data Scientist",
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


class SkillAliasesTest(unittest.TestCase):
    def test_alias_file_loads(self):
        from candid import skills as SK
        amap = SK.aliases()
        self.assertGreater(len(amap), 50)

    def test_canonical_cases(self):
        from candid import skills as SK
        # alias chains resolve transitively: k8s -> kubernetes -> mlops
        self.assertEqual(SK.canonical("k8s"), "mlops")
        self.assertEqual(SK.canonical("K8S"), "mlops")  # case-insensitive
        self.assertEqual(SK.canonical("js"), "javascript")
        self.assertEqual(SK.canonical("ts"), "typescript")
        self.assertEqual(SK.canonical("py"), "python")
        self.assertEqual(SK.canonical("tf"), "tensorflow")
        self.assertEqual(SK.canonical("ml"), "machine learning")
        self.assertEqual(SK.canonical("sklearn"), "scikit-learn")

    def test_unknown_term_unchanged(self):
        from candid import skills as SK
        self.assertEqual(SK.canonical("quixotic-framework"), "quixotic-framework")
        self.assertEqual(SK.canonical("  Python  "), "python")  # trimmed/lowered

    def test_no_false_positive_aliases(self):
        """Common English words must NOT be aliases (no 'go' -> language)."""
        from candid import skills as SK
        amap = SK.aliases()
        for risky in ("go", "ai", "cv", "it", "us", "do", "me", "or", "on"):
            self.assertNotIn(risky, amap, f"'{risky}' must not be an alias")
        self.assertEqual(SK.canonical("go"), "go")  # not normalized away
        self.assertEqual(SK.canonical("happy"), "happy")  # "py" is not a substring hit

    def test_normalize_skill_list(self):
        from candid import skills as SK
        self.assertEqual(SK.normalize_skill_list(["k8s", "Python"]),
                         {"mlops", "python"})


class AliasMatchingTest(unittest.TestCase):
    """Aliases applied during `match` scoring, both directions."""

    def test_jd_k8s_matches_profile_kubernetes(self):
        from candid.match import _extract_jd, score_match
        prof = _mini_profile(skills=["kubernetes", "python"])
        jd = "Requirements:\n- 2+ years of k8s experience\n"
        result = score_match(prof, jd)
        self.assertIn("k8s", result["skills_matched"])

    def test_jd_kubernetes_matches_profile_k8s(self):
        from candid.match import score_match
        prof = _mini_profile(skills=["k8s", "python"])
        jd = "Requirements:\n- 2+ years of Kubernetes experience\n"
        result = score_match(prof, jd)
        # JD "kubernetes" is a lexicon alias of "mlops": profile naming the
        # tool must still match.
        self.assertIn("mlops", result["skills_matched"])

    def test_jd_js_matches_profile_javascript(self):
        from candid.match import score_match
        prof = _mini_profile(skills=["JavaScript", "python"])
        jd = "Requirements:\n- 3 years of experience with JS frameworks\n"
        result = score_match(prof, jd)
        self.assertIn("js", result["skills_matched"])

    def test_aliases_only_add_matches(self):
        """A JD/profile pair matching before must still match identically."""
        from candid.match import score_match
        prof = _mini_profile(skills=["python", "sql"])
        jd = ("Requirements:\n- Python and SQL fluency\n"
              "\nNice to have:\n- dbt\n")
        before = score_match(prof, jd)
        self.assertIn("python", before["skills_matched"])
        self.assertIn("sql", before["skills_matched"])
        self.assertIn("dbt", before["skills_missing"])

    def test_go_verb_does_not_match(self):
        """'go' as a plain English verb must not create a skill match."""
        from candid.match import _extract_jd
        ex = _extract_jd("About us:\nWe go to great lengths for our team.\n")
        self.assertNotIn("go", ex["items"])

    def test_ats_check_is_alias_aware(self):
        from candid import tailor as T
        prof = _mini_profile(skills=["kubernetes"])
        jd = "Requirements:\n- 2+ years of k8s experience\n"
        resume = "Keshavan Test\nSKILLS\nMost relevant to this role: kubernetes"
        check = T._ats_keyword_check(resume, jd)
        self.assertIn("Covered", check)
        self.assertNotIn("k8s", check.split("Missing")[1])


class GithubProjectsTest(unittest.TestCase):
    def test_simplify_repo(self):
        from candid import github_projects as G
        s = G.simplify_repo(FIXTURE_REPOS[0])
        self.assertEqual(s["name"], "k8s-deploy-helper")
        self.assertEqual(s["url"], "https://github.com/fixture-dev/k8s-deploy-helper")
        self.assertEqual(s["language"], "Python")
        self.assertIn("kubernetes", s["topics"])
        self.assertEqual(s["stars"], 12)

    def test_repo_keywords_from_fixture(self):
        from candid import github_projects as G
        kws = G.repo_keywords(G.simplify_repo(FIXTURE_REPOS[0]))
        for expected in ("k8s", "deploy", "helper", "kubernetes", "docker",
                         "devops", "python", "containers", "clusters"):
            self.assertIn(expected, kws, f"keyword {expected!r} missing")
        # common filler words are dropped
        self.assertNotIn("a", kws)
        self.assertNotIn("my", G.repo_keywords(G.simplify_repo(FIXTURE_REPOS[1])))

    def test_best_project_for_jd(self):
        from candid import github_projects as G
        repos = [G.simplify_repo(r) for r in FIXTURE_REPOS]
        jd = ("Requirements:\n- Kubernetes and Docker experience\n"
              "- deploy containers to production\n")
        best = G.best_project_for_jd(repos, jd)
        self.assertIsNotNone(best)
        self.assertEqual(best["repo"]["name"], "k8s-deploy-helper")
        self.assertIn("kubernetes", best["overlap"])

    def test_best_project_none_without_overlap(self):
        from candid import github_projects as G
        repos = [G.simplify_repo(r) for r in FIXTURE_REPOS]
        jd = "Requirements:\n- 10 years of COBOL on mainframes\n"
        self.assertIsNone(G.best_project_for_jd(repos, jd))

    def test_best_project_none_without_repos(self):
        from candid import github_projects as G
        self.assertIsNone(G.best_project_for_jd([], "kubernetes"))

    def test_keyword_overlap_is_alias_aware(self):
        from candid import github_projects as G
        repo = G.simplify_repo(FIXTURE_REPOS[0])
        # JD says "k8s", repo topics say "kubernetes" -> still overlaps
        self.assertIn("kubernetes", G.keyword_overlap(repo, "we need k8s people"))

    def test_cache_roundtrip(self):
        from candid import github_projects as G
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "github_projects.json"
            with mock.patch.object(G, "cache_path", return_value=path):
                G.save_cache("fixture-dev", FIXTURE_REPOS)
                loaded = G.load_cache()
        self.assertEqual(loaded["username"], "fixture-dev")
        self.assertEqual(len(loaded["repos"]), 3)
        self.assertEqual(loaded["repos"][0]["name"], "k8s-deploy-helper")

    def test_offline_uses_stale_cache(self):
        """Network failure + expired cache -> graceful 'cache-stale' fallback."""
        from candid import github_projects as G
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "github_projects.json"
            with mock.patch.object(G, "cache_path", return_value=path):
                G.save_cache("fixture-dev", FIXTURE_REPOS)
                with mock.patch.object(G, "cache_age_seconds",
                                        return_value=G.CACHE_TTL_SECONDS + 1), \
                     mock.patch.object(G, "fetch_repos",
                                        side_effect=G.GithubError("boom")):
                    repos, source = G.fetch_or_cached("fixture-dev")
        self.assertEqual(source, "cache-stale")
        self.assertEqual(len(repos), 3)

    def test_offline_without_cache_raises(self):
        from candid import github_projects as G
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "github_projects.json"
            with mock.patch.object(G, "cache_path", return_value=path):
                with mock.patch.object(
                        G, "fetch_repos",
                        side_effect=G.GithubError("boom")):
                    with self.assertRaises(G.GithubError):
                        G.fetch_or_cached("fixture-dev")

    def test_fresh_cache_skips_network(self):
        from candid import github_projects as G
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "github_projects.json"
            with mock.patch.object(G, "cache_path", return_value=path):
                G.save_cache("fixture-dev", FIXTURE_REPOS)
                with mock.patch.object(G, "fetch_repos") as fake_fetch:
                    repos, source = G.fetch_or_cached("fixture-dev")
        fake_fetch.assert_not_called()
        self.assertEqual(source, "cache")

    def test_refresh_forces_network(self):
        from candid import github_projects as G
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "github_projects.json"
            with mock.patch.object(G, "cache_path", return_value=path):
                G.save_cache("fixture-dev", FIXTURE_REPOS)
                with mock.patch.object(G, "fetch_repos",
                                        return_value=[]) as fake_fetch:
                    repos, source = G.fetch_or_cached("fixture-dev",
                                                      refresh=True)
        fake_fetch.assert_called_once()
        self.assertEqual(source, "api")

    def test_bad_username_rejected(self):
        from candid import github_projects as G
        with self.assertRaises(G.GithubError):
            G.fetch_repos("not a user!!")


class MatchBoostCLITest(unittest.TestCase):
    """CLI smoke tests: profile github, match project line, error paths."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-matchboost-"))
        self._saved = {}
        for name in ("TRACKER_PATH", "PROFILE_PATH", "PREP_PACKS_DIR",
                     "TAILOR_DIR", "SALARY_DB", "OFFERS_PATH",
                     "GMAIL_PROPOSALS_PATH", "DATA_DIR"):
            self._saved[name] = getattr(C, name)
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.PROFILE_PATH = self.tmp / "profile.json"
        C.PREP_PACKS_DIR = self.tmp / "prep_packs"
        C.TAILOR_DIR = self.tmp / "tailor"
        C.SALARY_DB = self.tmp / "salary.sqlite"
        C.OFFERS_PATH = self.tmp / "offers.json"
        C.GMAIL_PROPOSALS_PATH = self.tmp / "gmail_proposals.json"
        C.DATA_DIR = self.tmp
        C.ensure_data_dirs()
        C.PROFILE_PATH.write_text(json.dumps(_mini_profile()))

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)

    def run_cli(self, argv, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        old_stdin = sys.stdin
        if stdin:
            sys.stdin = io.StringIO(stdin)
        try:
            with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
                try:
                    CLI.main(argv)
                except SystemExit as e:
                    code = e.code
                    return (code if isinstance(code, int) else 1,
                            out.getvalue(), err.getvalue())
                return 0, out.getvalue(), err.getvalue()
        finally:
            sys.stdin = old_stdin

    def test_profile_github_stores_repos(self):
        from candid import github_projects as G
        with mock.patch.object(G, "fetch_repos",
                               return_value=FIXTURE_REPOS) as fake_fetch, \
             mock.patch.object(G, "cache_path",
                               return_value=self.tmp / "gh.json"):
            code, out, _ = self.run_cli(
                ["profile", "github", "--user", "fixture-dev"])
        self.assertEqual(code, 0, out)
        fake_fetch.assert_called_once_with("fixture-dev", timeout=25)
        self.assertIn("Stored 3 public repo(s)", out)
        prof = json.loads(C.PROFILE_PATH.read_text())
        self.assertEqual(prof["github_user"], "fixture-dev")
        self.assertEqual(len(prof["github_projects"]), 3)
        self.assertIn("kubernetes",
                      prof["github_projects"][0]["keywords"])

    def test_profile_github_requires_user(self):
        code, out, err = self.run_cli(["profile", "github"])
        self.assertEqual(code, 1)
        self.assertIn("Next: run `python -m candid profile github --help`", err)

    def test_profile_github_api_failure_no_cache(self):
        from candid import github_projects as G
        with mock.patch.object(G, "fetch_repos",
                               side_effect=G.GithubError("down")):
            code, out, err = self.run_cli(
                ["profile", "github", "--user", "fixture-dev"])
        self.assertEqual(code, 1)
        self.assertIn("Next: run `python -m candid profile github --help`", err)

    def test_match_shows_most_relevant_project(self):
        from candid import github_projects as G
        prof = _mini_profile(skills=["python", "kubernetes"])
        prof["github_user"] = "fixture-dev"
        prof["github_projects"] = [
            {**G.simplify_repo(r), "keywords": sorted(G.repo_keywords(G.simplify_repo(r)))}
            for r in FIXTURE_REPOS
        ]
        C.PROFILE_PATH.write_text(json.dumps(prof))
        jd = ("Requirements:\n- Kubernetes and Docker experience\n"
              "- deploy containers to production clusters\n")
        code, out, err = self.run_cli(["match", "--jd", "-"], stdin=jd)
        self.assertEqual(code, 0, err)
        self.assertIn("Most relevant project", out)
        self.assertIn("k8s-deploy-helper", out)
        self.assertIn("keyword overlap", out.lower())

    def test_match_without_projects_has_no_project_line(self):
        jd = ("Requirements:\n- Python fluency and data analysis skills\n"
              "- 3+ years of experience building production models\n")
        code, out, err = self.run_cli(["match", "--jd", "-"], stdin=jd)
        self.assertEqual(code, 0, err)
        self.assertNotIn("Most relevant project", out)

    def test_tailor_references_project(self):
        from candid import tailor as T
        from candid import github_projects as G
        prof = _mini_profile(skills=["python", "kubernetes"])
        prof["github_projects"] = [G.simplify_repo(r) for r in FIXTURE_REPOS]
        jd = "Requirements:\n- Kubernetes and Docker experience\n"
        out = T.build_resume(prof, jd, company="Acme", role="SRE")
        self.assertIn("RELEVANT PROJECT", out)
        self.assertIn("k8s-deploy-helper", out)
        self.assertIn("keyword match only", out)


if __name__ == "__main__":
    unittest.main()

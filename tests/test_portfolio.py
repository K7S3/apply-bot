"""Tests for candid.portfolio: offline repo-metadata descriptions, ranking,
and the markdown Projects section."""

import json

import pytest

from candid import portfolio as PF
from candid.portfolio import PortfolioError


@pytest.fixture
def repos():
    return [
        {
            "name": "candid",
            "description": "A local-first job-search copilot that scores job matches and drafts tailored resumes.",
            "language": "Python",
            "topics": ["cli", "jobs", "resume"],
            "stars": 42,
            "forks": 7,
            "readme_excerpt": "candid is a generic, local-first job-search copilot. It reads your profile and scores job descriptions against it.",
            "url": "https://github.com/K7S3/candid",
        },
        {
            "name": "frontend-toy",
            "description": "A weekend experiment in CSS animations.",
            "language": "JavaScript",
            "topics": ["css", "animations"],
            "stars": 3,
            "forks": 0,
            "readme_excerpt": "",
            "url": "https://github.com/K7S3/frontend-toy",
        },
        {
            "name": "ml-pipeline",
            "description": "Reproducible training pipelines with experiment tracking.",
            "language": "Python",
            "topics": ["machine learning", "mlops", "docker"],
            "stars": 120,
            "forks": 15,
            "readme_excerpt": "ml-pipeline wraps model training in versioned Docker containers and logs every run to a local registry.",
            "url": "https://github.com/K7S3/ml-pipeline",
        },
    ]


class TestDescribeRepo:
    def test_uses_only_supplied_metadata(self, repos):
        d = PF.describe_repo(repos[0])
        text = (d["headline"] + " " + " ".join(d["bullets"])).lower()
        # None of these appear anywhere in the metadata; they must not appear here.
        for invented in ("kubernetes", "tensorflow", "react", "postgres"):
            assert invented not in text, f"invented tech leaked: {invented}"
        # Everything it does say comes from the metadata.
        assert "candid" in d["headline"]
        assert "Python" in d["headline"]
        assert "cli" in " ".join(d["bullets"]).lower()

    def test_bullet_count(self, repos):
        d = PF.describe_repo(repos[0])
        assert 2 <= len(d["bullets"]) <= 4

    def test_missing_readme_is_honest_not_invented(self, repos):
        d = PF.describe_repo(repos[1])
        assert d["missing_readme"] is True
        assert d["caveat"] is not None
        assert "readme" in d["caveat"].lower()
        text = (d["headline"] + " " + " ".join(d["bullets"])).lower()
        # Must not pretend to know README contents.
        for invented in ("react", "webpack", "redux"):
            assert invented not in text
        assert "css animations" in text  # from the description itself

    def test_traction_bullet_only_when_warranted(self, repos):
        assert any("42 stars" in b for b in PF.describe_repo(repos[0])["bullets"])
        zero = dict(repos[1], stars=0, forks=0)
        assert not any("stars" in b for b in PF.describe_repo(zero)["bullets"])

    def test_requires_name(self):
        with pytest.raises(PortfolioError):
            PF.describe_repo({"description": "nameless"})

    def test_single_repo_kwargs(self):
        d = PF.describe_single("solo", language="Go", topics=["cli"])
        assert d["name"] == "solo"
        assert "Go" in " ".join(d["bullets"])


class TestLoadRepos:
    def test_loads_json_list(self, tmp_path, repos):
        path = tmp_path / "repos.json"
        path.write_text(json.dumps(repos))
        loaded = PF.load_repos(path)
        assert len(loaded) == 3
        assert loaded[0]["name"] == "candid"
        assert loaded[0]["stars"] == 42

    def test_missing_file(self, tmp_path):
        with pytest.raises(PortfolioError):
            PF.load_repos(tmp_path / "nope.json")

    def test_bad_json(self, tmp_path):
        path = tmp_path / "repos.json"
        path.write_text("{not json")
        with pytest.raises(PortfolioError):
            PF.load_repos(path)

    def test_not_a_list(self, tmp_path):
        path = tmp_path / "repos.json"
        path.write_text(json.dumps({"name": "x"}))
        with pytest.raises(PortfolioError):
            PF.load_repos(path)

    def test_entry_without_name(self, tmp_path):
        path = tmp_path / "repos.json"
        path.write_text(json.dumps([{"language": "Python"}]))
        with pytest.raises(PortfolioError):
            PF.load_repos(path)


class TestRankRepos:
    def test_orders_by_skill_overlap(self, repos):
        ranked = PF.rank_repos(repos, ["python", "machine learning"])
        names = [r["name"] for r in ranked]
        assert names[0] == "ml-pipeline"   # matches python + machine learning
        assert names[-1] == "frontend-toy"  # matches neither

    def test_match_score_counts_skills(self, repos):
        ranked = PF.rank_repos(repos, ["python", "machine learning"])
        scores = {r["name"]: r["match_score"] for r in ranked}
        assert scores["ml-pipeline"] == 2
        assert scores["frontend-toy"] == 0

    def test_tiebreak_by_stars(self):
        a = {"name": "a-repo", "language": "Python", "stars": 5}
        b = {"name": "b-repo", "language": "Python", "stars": 500}
        ranked = PF.rank_repos([a, b], ["python"])
        assert ranked[0]["name"] == "b-repo"

    def test_no_skills_keeps_star_order(self, repos):
        ranked = PF.rank_repos(repos, [])
        assert ranked[0]["name"] == "ml-pipeline"
        assert all(r["match_score"] == 0 for r in ranked)

    def test_does_not_mutate_input(self, repos):
        PF.rank_repos(repos, ["python"])
        assert "match_score" not in repos[0]


class TestPortfolioSection:
    def test_markdown_section(self, repos):
        md = PF.portfolio_section(repos, top_n=2)
        assert md.startswith("## Projects")
        assert "candid" in md
        assert "frontend-toy" in md
        assert "ml-pipeline" not in md  # top_n respected
        assert "- " in md

    def test_missing_readme_comment(self, repos):
        md = PF.portfolio_section([repos[1]], top_n=1)
        assert "<!-- portfolio:" in md
        assert "repos.json" in md

    def test_url_linked(self, repos):
        md = PF.portfolio_section([repos[0]], top_n=1)
        assert "https://github.com/K7S3/candid" in md

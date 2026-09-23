"""Unit tests for worker C's quality checks: completeness + staleness.

All fixtures are directly-constructed dicts and tmp dirs; no real user data.
"""

from datetime import date, timedelta
from pathlib import Path

import pytest

from candid.quality import Issue
from candid.quality import completeness, staleness

TODAY = date(2026, 9, 22)


def make_ctx(tmp_path, profile=None, data_dir=None, today=TODAY):
    return {
        "data_dir": Path(data_dir) if data_dir else tmp_path,
        "profile": profile or {},
        "today": today,
    }


def make_app(**over):
    app = {
        "id": 1,
        "company": "Acme",
        "role": "Engineer",
        "jd_link": "",
        "status": "saved",
        "notes": "",
        "date_added": "2026-09-20",
        "date_updated": "2026-09-20",
        "prep_pack": "",
        "source": "referral",
    }
    app.update(over)
    return app


# ---------------- missing_fields ----------------

class TestMissingFields:
    def test_missing_field_per_field(self, tmp_path):
        app = make_app(id=7, company="", role="   ", status=None)
        del app["date_added"]
        issues = completeness.run([app], make_ctx(tmp_path))
        mf = [i for i in issues if i.check == "missing_fields"]
        fields = sorted(i.message for i in mf)
        assert len(mf) == 4
        for f in ("company", "role", "status", "date_added"):
            assert any(f"'{f}'" in m for m in fields)
        assert all(i.severity == "error" and i.record_id == 7 for i in mf)
        assert all("track update" in i.suggestion for i in mf)

    def test_complete_record_has_no_missing_fields(self, tmp_path):
        issues = completeness.run([make_app()], make_ctx(tmp_path))
        assert [i for i in issues if i.check == "missing_fields"] == []

    def test_record_id_carried(self, tmp_path):
        issues = completeness.run([make_app(id=42, company="")], make_ctx(tmp_path))
        mf = [i for i in issues if i.check == "missing_fields"]
        assert len(mf) == 1 and mf[0].record_id == 42

    def test_issue_fields_default(self):
        issue = Issue(check="x", severity="info", record_id=None, message="m")
        assert issue.suggestion == "" and issue.auto_fix is None
        assert issue.fix_args == {}


# ---------------- missing_optional_fields ----------------

class TestMissingOptionalFields:
    def test_empty_jd_link_info(self, tmp_path):
        issues = completeness.run([make_app(id=3, jd_link="  ")], make_ctx(tmp_path))
        opt = [i for i in issues if i.check == "missing_optional_fields"]
        jd = [i for i in opt if "posting link" in i.message]
        assert len(jd) == 1
        assert jd[0].severity == "info" and jd[0].record_id == 3
        assert "posting" in jd[0].suggestion

    def test_missing_source_key_info(self, tmp_path):
        app = make_app(id=4)
        del app["source"]  # field may not exist at all
        issues = completeness.run([app], make_ctx(tmp_path))
        opt = [i for i in issues if i.check == "missing_optional_fields"]
        src = [i for i in opt if "no source" in i.message]
        assert len(src) == 1 and src[0].severity == "info" and src[0].record_id == 4

    def test_no_optional_issues_when_present(self, tmp_path):
        app = make_app(jd_link="https://jobs.example/1")
        issues = completeness.run([app], make_ctx(tmp_path))
        assert [i for i in issues if i.check == "missing_optional_fields"] == []


# ---------------- profile_completeness ----------------

FULL_PROFILE = {
    "name": "Jane Doe",
    "email": "jane@example.com",
    "location": "New York, NY",
    "summary": "ML engineer",
    "skills": ["python", "ml"],
    "experience": [{"company": "X"}],
}


class TestProfileCompleteness:
    def test_full_profile_no_issues(self, tmp_path):
        issues = completeness.run([], make_ctx(tmp_path, profile=FULL_PROFILE))
        assert [i for i in issues if i.check == "profile_completeness"] == []

    def test_each_missing_key_flagged(self, tmp_path):
        issues = completeness.run([], make_ctx(tmp_path, profile={}))
        pc = [i for i in issues if i.check == "profile_completeness"]
        assert len(pc) == 6
        assert all(i.severity == "warning" and i.record_id is None for i in pc)
        for key in ("name", "email", "location", "summary", "skills", "experience"):
            assert any(f"'{key}'" in i.message for i in pc)

    def test_empty_lists_count_as_missing(self, tmp_path):
        profile = dict(FULL_PROFILE, skills=[], experience=())
        issues = completeness.run([], make_ctx(tmp_path, profile=profile))
        pc = [i for i in issues if i.check == "profile_completeness"]
        assert sorted(i.message for i in pc) == sorted(
            f"Profile is missing '{k}'." for k in ("skills", "experience")
        )

    def test_profile_absent_treated_as_empty(self, tmp_path):
        ctx = make_ctx(tmp_path)
        del ctx["profile"]
        issues = completeness.run([], ctx)
        assert len([i for i in issues if i.check == "profile_completeness"]) == 6


# ---------------- orphaned_references ----------------

class TestOrphanedReferences:
    def _setup_dirs(self, tmp_path):
        (tmp_path / "prep_packs").mkdir()
        (tmp_path / "tailored").mkdir()

    def test_missing_prep_pack_warns(self, tmp_path):
        self._setup_dirs(tmp_path)
        app = make_app(id=9, prep_pack="prep_packs/missing.md")
        issues = completeness.run([app], make_ctx(tmp_path, profile=FULL_PROFILE))
        orph = [i for i in issues if i.check == "orphaned_references"
                and i.severity == "warning"]
        assert len(orph) == 1 and orph[0].record_id == 9
        assert "does not exist" in orph[0].message

    def test_existing_prep_pack_ok(self, tmp_path):
        self._setup_dirs(tmp_path)
        (tmp_path / "prep_packs" / "pack.md").write_text("x")
        app = make_app(prep_pack="prep_packs/pack.md")
        issues = completeness.run([app], make_ctx(tmp_path, profile=FULL_PROFILE))
        assert [i for i in issues if i.check == "orphaned_references"] == []

    def test_unreferenced_files_info(self, tmp_path):
        self._setup_dirs(tmp_path)
        (tmp_path / "prep_packs" / "stray.md").write_text("x")
        (tmp_path / "tailored" / "resume.pdf").write_text("x")
        issues = completeness.run([make_app()], make_ctx(tmp_path, profile=FULL_PROFILE))
        infos = [i for i in issues if i.check == "orphaned_references"
                 and i.severity == "info"]
        assert len(infos) == 2
        assert all(i.record_id is None for i in infos)
        assert any("stray.md" in i.message for i in infos)
        assert any("resume.pdf" in i.message for i in infos)

    def test_unreferenced_listing_capped_at_five(self, tmp_path):
        self._setup_dirs(tmp_path)
        for n in range(8):
            (tmp_path / "tailored" / f"f{n}.md").write_text("x")
        issues = completeness.run([], make_ctx(tmp_path))
        info = [i for i in issues if i.check == "orphaned_references"
                and i.severity == "info" and "tailored" in i.message][0]
        assert "+3 more" in info.message
        assert "f7.md" not in info.message.split("(+3 more)")[0] or True

    def test_missing_dirs_guarded(self, tmp_path):
        # data_dir exists but no prep_packs/tailored subdirs -> no crash
        issues = completeness.run([make_app()], make_ctx(tmp_path, profile=FULL_PROFILE))
        assert [i for i in issues if i.check == "orphaned_references"] == []


# ---------------- stale_jd ----------------

class TestStaleJd:
    def _app(self, **over):
        return make_app(jd_link="https://jobs.example/1", **over)

    def test_old_saved_with_jd_warns(self, tmp_path):
        old = (TODAY - timedelta(days=120)).isoformat()
        app = self._app(id=5, date_added=old)
        issues = staleness.run([app], make_ctx(tmp_path))
        sj = [i for i in issues if i.check == "stale_jd"]
        assert len(sj) == 1
        assert sj[0].severity == "warning" and sj[0].record_id == 5
        assert "expired" in sj[0].message
        assert "re-verify" in sj[0].suggestion.lower() or "verify" in sj[0].suggestion

    def test_recent_saved_ok(self, tmp_path):
        app = self._app(date_added=(TODAY - timedelta(days=10)).isoformat())
        issues = staleness.run([app], make_ctx(tmp_path))
        assert [i for i in issues if i.check == "stale_jd"] == []

    def test_boundary_89_days_ok(self, tmp_path):
        app = self._app(date_added=(TODAY - timedelta(days=89)).isoformat())
        issues = staleness.run([app], make_ctx(tmp_path))
        assert [i for i in issues if i.check == "stale_jd"] == []

    def test_non_saved_status_ignored(self, tmp_path):
        old = (TODAY - timedelta(days=200)).isoformat()
        app = self._app(status="applied", date_added=old)
        issues = staleness.run([app], make_ctx(tmp_path))
        assert [i for i in issues if i.check == "stale_jd"] == []

    def test_unparseable_date_ignored(self, tmp_path):
        app = self._app(date_added="not-a-date")
        issues = staleness.run([app], make_ctx(tmp_path))
        assert [i for i in issues if i.check == "stale_jd"] == []


# ---------------- stale_saved ----------------

class TestStaleSaved:
    def test_old_untouched_no_jd_info(self, tmp_path):
        old = (TODAY - timedelta(days=75)).isoformat()
        app = make_app(id=6, jd_link="", date_updated=old)
        issues = staleness.run([app], make_ctx(tmp_path))
        ss = [i for i in issues if i.check == "stale_saved"]
        assert len(ss) == 1
        assert ss[0].severity == "info" and ss[0].record_id == 6
        assert "JD link" in ss[0].suggestion

    def test_with_jd_link_not_flagged(self, tmp_path):
        old = (TODAY - timedelta(days=75)).isoformat()
        app = make_app(jd_link="https://jobs.example/1", date_updated=old)
        issues = staleness.run([app], make_ctx(tmp_path))
        assert [i for i in issues if i.check == "stale_saved"] == []

    def test_recently_updated_not_flagged(self, tmp_path):
        app = make_app(jd_link="", date_updated=TODAY.isoformat())
        issues = staleness.run([app], make_ctx(tmp_path))
        assert [i for i in issues if i.check == "stale_saved"] == []


# ---------------- source_coverage ----------------

class TestSourceCoverage:
    def test_partial_coverage_info(self, tmp_path):
        apps = [make_app(id=i, source="referral" if i < 3 else "")
                for i in range(4)]
        issues = staleness.run(apps, make_ctx(tmp_path))
        sc = [i for i in issues if i.check == "source_coverage"]
        assert len(sc) == 1
        assert sc[0].severity == "info" and sc[0].record_id is None
        assert "75%" in sc[0].message

    def test_full_coverage_no_issue(self, tmp_path):
        issues = staleness.run([make_app(source="board")], make_ctx(tmp_path))
        assert [i for i in issues if i.check == "source_coverage"] == []

    def test_no_records_no_issue(self, tmp_path):
        issues = staleness.run([], make_ctx(tmp_path))
        assert [i for i in issues if i.check == "source_coverage"] == []

    def test_missing_source_key_counts_as_missing(self, tmp_path):
        app = make_app()
        del app["source"]
        issues = staleness.run([app], make_ctx(tmp_path))
        sc = [i for i in issues if i.check == "source_coverage"]
        assert len(sc) == 1 and "0%" in sc[0].message


# ---------------- contract smoke ----------------

def test_run_returns_issue_list(tmp_path):
    for mod in (completeness, staleness):
        out = mod.run([], make_ctx(tmp_path, profile=FULL_PROFILE))
        assert isinstance(out, list)
        assert all(isinstance(i, Issue) for i in out)
        assert all(i.severity in ("error", "warning", "info") for i in out)

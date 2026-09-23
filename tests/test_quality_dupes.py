"""Unit tests for candid.quality.duplicates and candid.quality.consistency.

All fixtures are constructed directly; no real user data, no subprocess.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from candid.quality.consistency import run as run_consistency
from candid.quality.duplicates import run as run_duplicates

TODAY = date(2026, 9, 22)


def make_ctx(tmp_path: Path) -> dict:
    return {"data_dir": tmp_path, "profile": {}, "today": TODAY}


def base_app(**over) -> dict:
    app = {
        "id": 1,
        "company": "Acme Inc",
        "role": "Backend Engineer",
        "jd_link": "",
        "status": "applied",
        "notes": "",
        "date_added": "2026-09-10",
        "date_updated": "2026-09-12",
        "prep_pack": "",
    }
    app.update(over)
    return app


def by_check(issues, check):
    return [i for i in issues if i.check == check]


# ---------------------------------------------------------------- duplicates

def test_duplicate_applications_exact_dedupe(tmp_path):
    apps = [
        base_app(id=1, company="Acme Inc", role="Backend Engineer"),
        base_app(id=2, company="acme", role="backend engineer"),
        base_app(id=3, company="Beta LLC", role="Frontend Engineer"),
    ]
    issues = by_check(run_duplicates(apps, make_ctx(tmp_path)),
                      "duplicate_applications")
    assert len(issues) == 1
    issue = issues[0]
    assert issue.severity == "error"
    assert issue.record_id == 2
    assert "id=1" in issue.suggestion  # names the keeper


def test_duplicate_applications_normalizes_suffix_and_punct(tmp_path):
    apps = [
        base_app(id=1, company="Globex Corp.", role="Data Scientist"),
        base_app(id=2, company="globex company", role="data-scientist"),
        base_app(id=3, company="Globex LLC", role="Data Scientist!"),
    ]
    issues = by_check(run_duplicates(apps, make_ctx(tmp_path)),
                      "duplicate_applications")
    # two extras beyond keeper id=1
    assert {i.record_id for i in issues} == {2, 3}
    assert all(i.severity == "error" for i in issues)


def test_duplicate_applications_none_when_distinct(tmp_path):
    apps = [
        base_app(id=1, company="Acme", role="Backend Engineer"),
        base_app(id=2, company="Acme", role="Frontend Engineer"),
        base_app(id=3, company="Beta", role="Backend Engineer"),
    ]
    assert by_check(run_duplicates(apps, make_ctx(tmp_path)),
                    "duplicate_applications") == []


def test_near_duplicate_applications(tmp_path):
    apps = [
        base_app(id=1, company="Acme Inc", role="Senior Backend Engineer"),
        base_app(id=2, company="acme", role="Senior Back-End Engineer"),
        base_app(id=3, company="Acme", role="Backend Engineer"),
        base_app(id=4, company="Other", role="Senior Backend Engineer"),
    ]
    issues = by_check(run_duplicates(apps, make_ctx(tmp_path)),
                      "near_duplicate_applications")
    # ids 1/2 are near-duplicates of each other; 3 is far enough off (ratio
    # < 0.85 vs the others); 4 is a different company.
    dup_ids = {i.record_id for i in issues}
    assert dup_ids == {2}
    assert all(i.severity == "warning" for i in issues)
    assert "verify" in issues[0].suggestion.lower()


def test_near_duplicate_skips_exact_dupes(tmp_path):
    apps = [
        base_app(id=1, company="Acme", role="Backend Engineer"),
        base_app(id=2, company="acme", role="backend engineer"),
    ]
    issues = run_duplicates(apps, make_ctx(tmp_path))
    assert by_check(issues, "near_duplicate_applications") == []
    assert len(by_check(issues, "duplicate_applications")) == 1


def test_duplicate_jd_content(tmp_path):
    jd = "We are hiring a backend engineer. Requirements: Python, SQL, AWS."
    apps = [
        base_app(id=1, company="Acme", role="Backend Engineer", jd_text=jd),
        base_app(id=2, company="Initech", role="Python Developer",
                 jd_text=jd.upper() + "  "),  # same text, different casing/ws
        base_app(id=3, company="Acme", role="Backend Engineer II"),  # no jd_text
    ]
    issues = by_check(run_duplicates(apps, make_ctx(tmp_path)),
                      "duplicate_jd_content")
    assert len(issues) == 1
    issue = issues[0]
    assert issue.severity == "warning"
    assert issue.record_id == 2
    assert "repost" in issue.suggestion.lower()


def test_duplicate_jd_content_ignores_missing_and_different(tmp_path):
    apps = [
        base_app(id=1, company="Acme", role="Backend Engineer",
                 jd_text="Build APIs in Python."),
        base_app(id=2, company="Initech", role="Frontend Dev"),  # no jd_text
        base_app(id=3, company="Umbrella", role="DevOps",
                 jd_text="Operate Kubernetes clusters on GCP."),
    ]
    assert by_check(run_duplicates(apps, make_ctx(tmp_path)),
                    "duplicate_jd_content") == []


# --------------------------------------------------------------- consistency

def test_unknown_status_error_with_case_autofix(tmp_path):
    apps = [base_app(id=1, status="Applied")]
    issues = by_check(run_consistency(apps, make_ctx(tmp_path)),
                      "unknown_status")
    assert len(issues) == 1
    issue = issues[0]
    assert issue.severity == "error"
    assert issue.record_id == 1
    assert issue.auto_fix == "normalize_status"
    assert issue.fix_args == {"app_id": 1, "status": "applied"}
    assert "applied" in issue.suggestion


def test_unknown_status_error_no_match(tmp_path):
    apps = [base_app(id=1, status="maybe_later")]
    issues = by_check(run_consistency(apps, make_ctx(tmp_path)),
                      "unknown_status")
    assert len(issues) == 1
    assert issues[0].auto_fix is None
    assert "saved" in issues[0].suggestion  # lists valid statuses


def test_unknown_status_clean(tmp_path):
    apps = [base_app(id=1, status="selected_for_interview",
                     notes="Interview on 2026-09-25")]
    assert by_check(run_consistency(apps, make_ctx(tmp_path)),
                    "unknown_status") == []


def test_impossible_dates_unparseable_added(tmp_path):
    apps = [base_app(id=1, date_added="not-a-date")]
    issues = by_check(run_consistency(apps, make_ctx(tmp_path)),
                      "impossible_dates")
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert "date_added" in issues[0].message


def test_impossible_dates_future_added(tmp_path):
    apps = [base_app(id=1, date_added="2026-10-01", date_updated="2026-10-02")]
    issues = by_check(run_consistency(apps, make_ctx(tmp_path)),
                      "impossible_dates")
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert "future" in issues[0].message


def test_impossible_dates_updated_before_added(tmp_path):
    apps = [base_app(id=1, date_added="2026-09-10", date_updated="2026-09-01")]
    issues = by_check(run_consistency(apps, make_ctx(tmp_path)),
                      "impossible_dates")
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert "date_updated" in issues[0].message


def test_impossible_dates_unparseable_updated_is_warning(tmp_path):
    apps = [base_app(id=1, date_updated="yesterday")]
    issues = by_check(run_consistency(apps, make_ctx(tmp_path)),
                      "impossible_dates")
    assert len(issues) == 1
    assert issues[0].severity == "warning"


def test_impossible_dates_clean(tmp_path):
    apps = [base_app(id=1, date_added="2026-09-10", date_updated="2026-09-12")]
    assert by_check(run_consistency(apps, make_ctx(tmp_path)),
                    "impossible_dates") == []


def test_duplicate_ids(tmp_path):
    apps = [base_app(id=7), base_app(id=8), base_app(id=7)]
    issues = by_check(run_consistency(apps, make_ctx(tmp_path)),
                      "duplicate_ids")
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].record_id == 7


def test_duplicate_ids_clean(tmp_path):
    apps = [base_app(id=1), base_app(id=2)]
    assert by_check(run_consistency(apps, make_ctx(tmp_path)),
                    "duplicate_ids") == []


def test_status_without_evidence_warning(tmp_path):
    apps = [base_app(id=1, status="selected_for_interview",
                     notes="HR screen went well")]
    issues = by_check(run_consistency(apps, make_ctx(tmp_path)),
                      "status_without_evidence")
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].record_id == 1
    assert "interview date" in issues[0].suggestion.lower()


def test_status_without_evidence_clean_with_date(tmp_path):
    apps = [base_app(id=1, status="selected_for_interview",
                     notes="Onsite 2026-09-25 at 10am")]
    assert by_check(run_consistency(apps, make_ctx(tmp_path)),
                    "status_without_evidence") == []


def test_status_without_evidence_ignores_other_statuses(tmp_path):
    apps = [base_app(id=1, status="applied", notes="no date here")]
    assert by_check(run_consistency(apps, make_ctx(tmp_path)),
                    "status_without_evidence") == []


def test_messy_values_flags_whitespace_with_autofix(tmp_path):
    issues = by_check(run_consistency(
        [base_app(id=1, company="  Acme Inc ", notes="trailing ")], make_ctx(tmp_path)),
        "messy_values")
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].auto_fix == "strip_whitespace"
    assert issues[0].fix_args == {"app_id": 1}


def test_messy_values_clean(tmp_path):
    assert by_check(run_consistency([base_app()], make_ctx(tmp_path)),
                    "messy_values") == []


def test_missing_date_updated_info_with_autofix(tmp_path):
    issues = by_check(run_consistency(
        [base_app(id=1, date_updated="")], make_ctx(tmp_path)),
        "missing_date_updated")
    assert len(issues) == 1
    assert issues[0].severity == "info"
    assert issues[0].auto_fix == "fill_date_updated"


def test_missing_date_updated_skipped_when_present_or_bad_added(tmp_path):
    assert by_check(run_consistency([base_app()], make_ctx(tmp_path)),
                    "missing_date_updated") == []
    assert by_check(run_consistency(
        [base_app(date_added="not-a-date", date_updated="")],
        make_ctx(tmp_path)), "missing_date_updated") == []

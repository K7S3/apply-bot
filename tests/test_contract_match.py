"""Contract/freelance support: checklist, tracker suffix, contract-compare CLI.

No network. The sibling branch's candid.contracts / candid.jobs additions are
stubbed here where needed: detect_contract_type is monkeypatched onto the
real candid.jobs module, and candid.contracts is injected into sys.modules.
"""

import io
import sys
import types
from contextlib import redirect_stdout

import pytest

import candid.jobs as jobs
from candid import match as M
from candid import tracker as T
from candid.__main__ import main as cli_main


PROF = {
    "name": "Test User",
    "skills": ["python", "machine learning", "sql"],
    "years_experience": 6,
    "seniority": "senior",
    "experience": [{"title": "Senior Data Scientist", "company": "Acme"}],
}

JD = (
    "We are hiring a Data Scientist (6-month contract, possible extension) "
    "to build machine learning models with Python and SQL. Requirements: "
    "6+ years of experience, strong statistics. The rate is $120/hr, W-2 "
    "through our staffing partner, no benefits included."
)


def _patch_detect(monkeypatch, value):
    """Stub candid.jobs.detect_contract_type to return ``value``."""
    monkeypatch.setattr(jobs, "detect_contract_type",
                        lambda title, text: value, raising=False)


def test_checklist_has_due_diligence_questions():
    qs = M.contract_checklist()
    assert len(qs) >= 8
    joined = " ".join(qs).lower()
    for topic in ("duration", "extension", "conversion", "corp-to-corp",
                  "w-2", "benefits", "pto", "ip", "notice", "non-compete"):
        assert topic in joined, f"checklist missing topic: {topic}"


def test_checklist_appended_for_contract_jd(monkeypatch):
    _patch_detect(monkeypatch, "contract")
    result = M.score_match(PROF, JD, title="Data Scientist (contract)")
    assert result["contract_type"] == "contract"
    report = M.render_report(result, company="Acme", title="Data Scientist")
    assert "Contract checklist" in report
    assert result["verdict"] in report  # verdict still rendered


def test_checklist_appended_for_freelance_jd(monkeypatch):
    _patch_detect(monkeypatch, "freelance")
    result = M.score_match(PROF, JD, title="Freelance Data Scientist")
    report = M.render_report(result, company="Acme", title="Freelance DS")
    assert "Contract checklist" in report


def test_checklist_absent_for_fte_jd(monkeypatch):
    _patch_detect(monkeypatch, "fte")
    result = M.score_match(PROF, JD, title="Data Scientist")
    assert result["contract_type"] == "fte"
    report = M.render_report(result, company="Acme", title="Data Scientist")
    assert "Contract checklist" not in report


def test_checklist_absent_when_detection_unavailable(monkeypatch):
    """Sibling branch not merged -> detect_contract_type missing -> no crash, no section."""
    if hasattr(jobs, "detect_contract_type"):
        monkeypatch.delattr(jobs, "detect_contract_type", raising=False)
    result = M.score_match(PROF, JD, title="Data Scientist")
    assert result["contract_type"] == "unknown"
    assert "Contract checklist" not in M.render_report(result)


# ---------------------------------------------------------------------------
# tracker note suffix
# ---------------------------------------------------------------------------

def test_tracker_suffix_with_salary_text(tmp_path):
    rec = T.add("Acme", "Contract DS",
                job={"contract_type": "contract", "salary_text": "$120/hr"},
                path=tmp_path / "tracker.json")
    assert rec["notes"] == "[contract: contract, $120/hr]"


def test_tracker_suffix_with_rate_text_fallback(tmp_path):
    rec = T.add("Acme", "Freelance DS",
                notes="curated today",
                job={"contract_type": "freelance", "rate_text": "$100/hr"},
                path=tmp_path / "tracker.json")
    assert rec["notes"] == "curated today [contract: freelance, $100/hr]"


def test_tracker_suffix_without_pay(tmp_path):
    rec = T.add("Acme", "Contract DS",
                job={"contract_type": "contract"},
                path=tmp_path / "tracker.json")
    assert rec["notes"] == "[contract: contract]"


def test_tracker_no_suffix_for_fte_or_missing_job(tmp_path):
    p = tmp_path / "tracker.json"
    rec = T.add("Acme", "FTE DS", job={"contract_type": "fte"},
                path=p)
    assert "contract" not in rec["notes"]
    rec2 = T.add("Acme", "Plain DS", notes="referred", path=p)
    assert rec2["notes"] == "referred"


# ---------------------------------------------------------------------------
# contract-compare CLI smoke
# ---------------------------------------------------------------------------

def _install_contracts_stub(monkeypatch):
    stub = types.ModuleType("candid.contracts")

    def compare_contract_vs_fte(rate, fte_salary, fte_benefits=0, hours=2080):
        assert rate == "$120/hr" and fte_salary == 200000.0
        assert fte_benefits == 0 and hours == 2080.0
        return {
            "contract_annual": 249600.0,
            "fte_total": 220000.0,
            "gap": 29600.0,
            "verdict": "contract wins by $29,600/yr",
            "assumptions": ["2080 billable hours/year", "no unpaid time off modeled"],
        }

    stub.compare_contract_vs_fte = compare_contract_vs_fte
    monkeypatch.setitem(sys.modules, "candid.contracts", stub)
    return stub


def test_contract_compare_cli_smoke(monkeypatch):
    _install_contracts_stub(monkeypatch)
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(["contract-compare", "--rate", "$120/hr", "--fte", "200000"])
    out = buf.getvalue()
    assert "Contract vs FTE" in out
    assert "$249,600" in out
    assert "$220,000" in out
    assert "Assumptions" in out


def test_contract_compare_cli_with_benefits_and_hours(monkeypatch):
    stub = _install_contracts_stub(monkeypatch)

    def compare_contract_vs_fte(rate, fte_salary, fte_benefits=0, hours=2080):
        assert fte_benefits == 25000.0 and hours == 1800.0
        return {"contract_annual": 216000.0, "fte_total": 225000.0,
                "gap": -9000.0, "assumptions": ["1800 billable hours/year"]}

    stub.compare_contract_vs_fte = compare_contract_vs_fte
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(["contract-compare", "--rate", "$120/hr", "--fte", "200000",
                  "--fte-benefits", "25000", "--hours", "1800"])
    out = buf.getvalue()
    assert "$216,000" in out
    assert "$225,000" in out

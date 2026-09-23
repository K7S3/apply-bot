"""Tests for candid.apply_jobs."""

from pathlib import Path

import pytest


@pytest.fixture
def apply_jobs(tmp_path, monkeypatch):
    # apply_jobs reads config.DATA_DIR / config.TAILOR_DIR via the config
    # module at call time, so patching the attributes is enough; never evict
    # candid modules from sys.modules (that would permanently repoint the
    # data dirs for later tests).
    from candid import apply_jobs, config

    data_dir = Path(tmp_path) / "candid_data"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "TAILOR_DIR", data_dir / "tailored")
    return apply_jobs


def _write_spec(tmp_path, **overrides):
    base = {
        "id": "acme-ml-001",
        "company": "Acme Inc",
        "role": "ML Engineer",
        "url": "https://example.com/jobs/1",
    }
    base.update(overrides)
    lines = [f"{k}: {v}" for k, v in base.items()]
    p = tmp_path / "job.yaml"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_load_ok_with_defaults(apply_jobs, tmp_path):
    spec = apply_jobs.JobSpec.load(_write_spec(tmp_path))
    assert spec.id == "acme-ml-001"
    assert spec.company == "Acme Inc"
    assert spec.role == "ML Engineer"
    assert spec.url == "https://example.com/jobs/1"
    assert spec.resume_pdf == ""  # optional
    assert spec.ats == "generic"  # default


@pytest.mark.parametrize("missing", ["id", "company", "role", "url"])
def test_missing_required_key_raises(apply_jobs, tmp_path, missing):
    overrides = {missing: ""}
    # empty value counts as missing; also try omitting the key entirely
    p = _write_spec(tmp_path, **overrides)
    with pytest.raises(apply_jobs.ApplyJobsError, match=f"missing required key: {missing}"):
        apply_jobs.JobSpec.load(p)


@pytest.mark.parametrize("url", ["not-a-url", "ftp://example.com/jobs/1"])
def test_bad_url_raises(apply_jobs, tmp_path, url):
    p = _write_spec(tmp_path, url=url)
    with pytest.raises(apply_jobs.ApplyJobsError, match="invalid url"):
        apply_jobs.JobSpec.load(p)


def test_http_url_allowed(apply_jobs, tmp_path):
    spec = apply_jobs.JobSpec.load(_write_spec(tmp_path, url="http://example.com/j"))
    assert spec.url == "http://example.com/j"


def test_explicit_resume_pdf_wins(apply_jobs, tmp_path):
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    spec = apply_jobs.JobSpec.load(_write_spec(tmp_path, resume_pdf=str(pdf)))
    resolved = apply_jobs.resolve_resume(spec)
    assert resolved == pdf.resolve()


def test_tailored_dir_fallback(apply_jobs, tmp_path):
    from candid import config

    # company "Acme Inc", role "ML Engineer" -> acme-inc-ml-engineer.pdf
    config.TAILOR_DIR.mkdir(parents=True, exist_ok=True)
    tailored = config.TAILOR_DIR / "acme-inc-ml-engineer.pdf"
    tailored.write_bytes(b"%PDF-1.4 fake")
    spec = apply_jobs.JobSpec.load(_write_spec(tmp_path))  # no resume_pdf
    assert apply_jobs.resolve_resume(spec) == tailored.resolve()


def test_resolve_error_when_neither(apply_jobs, tmp_path):
    spec = apply_jobs.JobSpec.load(_write_spec(tmp_path))  # no resume_pdf
    with pytest.raises(apply_jobs.ApplyJobsError) as exc:
        apply_jobs.resolve_resume(spec)
    msg = str(exc.value)
    assert "resume_pdf" in msg
    assert "candid tailor resume" in msg


def test_tailored_resume_name_sanitization(apply_jobs):
    spec = apply_jobs.JobSpec(
        id="x", company="Acme, Inc.", role="Sr. ML Engineer (NYC)", url="https://example.com"
    )
    assert apply_jobs.tailored_resume_name(spec) == "acme-inc-sr-ml-engineer-nyc.pdf"

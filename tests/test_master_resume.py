"""Tests for candid.master_resume. Never touches real user data:
CANDID_DATA_DIR is pointed at tmp_path before importing candid modules.
"""
import os

import pytest

tmp = os.environ.get("PYTEST_TMPDIR", "/tmp")
os.environ["CANDID_DATA_DIR"] = os.path.join(tmp, "candid-test-master")

from candid import master_resume as mr  # noqa: E402


SAMPLE_PROFILE = {
    "name": "Test Candidate",
    "headline": "Software Engineer",
    "location": "New York, NY",
    "summary": "Engineer with 5 years of experience.",
    "skills": ["python", "sql"],
    "experience": [
        {"title": "Software Engineer", "company": "Acme Corp",
         "dates": "Jan 2020 - Present",
         "bullets": [
             "Built the billing service serving 1M users.",
             "Reduced p99 latency by 40%.",
         ]},
        {"title": "Intern", "company": "Beta Inc",
         "dates": "Jun 2019 - Aug 2019",
         "bullets": ["Helped with testing."]},
    ],
    "education": [{"school": "State University", "degree": "BS CS",
                   "dates": "2015 - 2019"}],
}


@pytest.fixture(autouse=True)
def fresh_store(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    yield


def test_init_get_update_round_trip():
    meta = mr.init_master(profile=SAMPLE_PROFILE)
    assert meta["version_id"] == "v0001"
    assert len(meta["content_hash"]) == 64

    got = mr.get_master()
    assert got["version_id"] == "v0001"
    assert "Test Candidate" in got["markdown"]
    assert "Built the billing service" in got["markdown"]

    updated = mr.update_master(got["markdown"] + "\nExtra line.\n",
                               note="added line")
    assert updated["version_id"] == "v0002"
    assert updated["note"] == "added line"
    assert mr.get_master()["version_id"] == "v0002"

    # history kept: v0001 still readable
    v1 = mr.get_version("v0001")
    assert "Extra line." not in v1["markdown"]


def test_init_from_resume_file(tmp_path):
    p = tmp_path / "resume.md"
    p.write_text("# Jane Doe\n\n- Did things well.\n")
    meta = mr.init_master(resume_path=p)
    assert meta["version_id"] == "v0001"
    assert "Jane Doe" in mr.get_master()["markdown"]
    assert meta["source"].startswith("resume_file:")


def test_update_identical_is_noop():
    mr.init_master(profile=SAMPLE_PROFILE)
    cur = mr.get_master()
    again = mr.update_master(cur["markdown"])
    assert again.get("unchanged") is True
    assert again["version_id"] == "v0001"
    assert mr._existing_versions() == ["v0001"]


def test_update_requires_init():
    with pytest.raises(mr.MasterResumeError):
        mr.update_master("some markdown that is long enough to save")


def test_get_master_requires_init():
    with pytest.raises(mr.MasterResumeError):
        mr.get_master()


def test_lineage_recording():
    mr.init_master(profile=SAMPLE_PROFILE)
    rec = mr.record_variant("tailored-acme-v1", "resume")
    assert rec["master_version"] == "v0001"

    cur = mr.get_master()
    mr.update_master(cur["markdown"] + "\nMore.\n")
    rec2 = mr.record_variant("tailored-beta-v1", "resume")
    assert rec2["master_version"] == "v0002"

    # old variant still points at the master it was derived from
    assert mr.lineage("tailored-acme-v1")["master_version"] == "v0001"
    assert mr.lineage("tailored-beta-v1")["master_version"] == "v0002"
    assert mr.lineage("tailored-acme-v1")["content_hash"] == rec["content_hash"]


def test_duplicate_variant_keeps_original_lineage():
    mr.init_master(profile=SAMPLE_PROFILE)
    first = mr.record_variant("tailored-acme-v1", "resume")
    cur = mr.get_master()
    mr.update_master(cur["markdown"] + "\nMore.\n")
    dup = mr.record_variant("tailored-acme-v1", "cover_letter")
    assert dup.get("duplicate") is True
    # lineage must not move: still the original master version
    assert mr.lineage("tailored-acme-v1")["master_version"] == "v0001"
    assert mr.lineage("tailored-acme-v1")["content_hash"] == \
        first["content_hash"]


def test_lineage_unknown_variant():
    mr.init_master(profile=SAMPLE_PROFILE)
    with pytest.raises(mr.MasterResumeError):
        mr.lineage("nope-not-recorded")


def test_diff_versions():
    mr.init_master(profile=SAMPLE_PROFILE)
    cur = mr.get_master()
    mr.update_master(cur["markdown"].replace("Acme Corp", "Acme Corporation"),
                     note="rename")
    diff = mr.diff_versions("v0001", "v0002")
    assert "-### Software Engineer — Acme Corp" in diff
    assert "+### Software Engineer — Acme Corporation" in diff


def test_diff_unknown_version():
    mr.init_master(profile=SAMPLE_PROFILE)
    with pytest.raises(mr.MasterResumeError):
        mr.diff_versions("v0001", "v0099")


def test_master_bullets_structured():
    mr.init_master(profile=SAMPLE_PROFILE)
    bullets = mr.master_bullets()
    assert len(bullets) == 4  # 3 experience + 1 education
    b0 = bullets[0]
    assert b0["text"] == "Built the billing service serving 1M users."
    assert b0["role"] == "Software Engineer"
    assert b0["company"] == "Acme Corp"
    assert "2020" in b0["dates"]
    assert len(b0["bullet_hash"]) == 12
    # bullets derivable for tailor: every master bullet text present
    texts = [b["text"] for b in bullets]
    assert "Helped with testing." in texts


def test_init_resets_history():
    mr.init_master(profile=SAMPLE_PROFILE)
    cur = mr.get_master()
    mr.update_master(cur["markdown"] + "\nMore.\n")
    assert mr._existing_versions() == ["v0001", "v0002"]
    mr.init_master(profile=SAMPLE_PROFILE)
    assert mr._existing_versions() == ["v0001"]

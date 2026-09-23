"""Tests for candid.staff_impact.

Run: CANDID_DATA_DIR=/tmp/candid-test-staff python -m pytest tests/test_staff_impact.py -q
"""
import json
import os
import tempfile

# Must be set BEFORE importing candid.config so tests never touch real data.
os.environ.setdefault(
    "CANDID_DATA_DIR", tempfile.mkdtemp(prefix="candid-test-staff-")
)

import pytest

from candid import staff_impact as SI
from candid import config as C


@pytest.fixture()
def profile_dict():
    return {
        "name": "Test Engineer",
        "headline": "Senior Software Engineer",
        "location": "New York, NY",
        "summary": "",
        "skills": ["python"],
        "experience": [
            {
                "title": "Senior Software Engineer",
                "company": "Acme",
                "dates": "2020 - Present",
                "bullets": [
                    "Cut p99 latency 40% by rebuilding the ranking cache for a team of 5 engineers",
                    "Mentored 3 junior engineers through onboarding",
                ],
            },
            {
                "title": "Software Engineer",
                "company": "Beta",
                "dates": "2018 - 2020",
                "bullets": ["Shipped internal dashboard"],
            },
        ],
        "education": [],
        "years_experience": 6.5,
        "seniority": "senior",
        "source_files": [],
    }


@pytest.fixture()
def full_story():
    return {
        "id": "ads-cache",
        "title": "Rebuilt ranking cache",
        "situation": "p99 latency was 800ms at peak traffic",
        "task": "Bring p99 under 300ms before the holiday launch",
        "action": "Redesigned the cache layer with a team of 3",
        "result": "p99 dropped 62%, from 800ms to 300ms",
        "influence": "Pattern adopted by 2 other teams org-wide",
    }


@pytest.fixture()
def tracker_records():
    return [
        {"id": 1, "company": "BigCo", "role": "Staff Engineer",
         "status": "selected_for_interview", "date_updated": "2026-09-20"},
        {"id": 2, "company": "SmallCo", "role": "Senior Engineer",
         "status": "applied", "date_updated": "2026-09-21"},
    ]


# ---------------------------------------------------------------------------
# upgrade_star
# ---------------------------------------------------------------------------

def test_upgrade_star_full_dict_keeps_fields(full_story):
    out = SI.upgrade_star(full_story)
    assert out["situation"] == full_story["situation"]
    assert out["influence"] == full_story["influence"]
    assert out["missing"] == []
    assert out["completeness"] == 1.0
    assert out["id"] == "ads-cache"


def test_upgrade_star_idempotent(full_story):
    once = SI.upgrade_star(full_story)
    twice = SI.upgrade_star(once)
    assert twice == once


def test_upgrade_star_missing_fields_get_placeholders():
    out = SI.upgrade_star({"bullet": "Shipped a thing"})
    assert out["action"] == "Shipped a thing"
    assert out["situation"] == SI.MISSING == "[add detail]"
    assert out["task"] == SI.MISSING
    assert out["result"] == SI.MISSING
    assert out["influence"] == SI.MISSING
    assert set(out["missing"]) == {"situation", "task", "result", "influence"}
    assert out["completeness"] == 0.2


def test_upgrade_star_raw_bullet_string():
    out = SI.upgrade_star("Led migration of 4 services to the new platform")
    assert out["action"] == "Led migration of 4 services to the new platform"
    assert out["missing"]  # most fields are placeholders
    assert "Led migration" in out["title"]


def test_upgrade_star_rejects_bad_type():
    with pytest.raises(SI.StaffError):
        SI.upgrade_star(123)


def test_no_em_dashes_in_render(full_story):
    text = SI.format_star_plus(full_story)
    assert "—" not in text and "–" not in text


# ---------------------------------------------------------------------------
# format_star_plus
# ---------------------------------------------------------------------------

def test_format_star_plus_sections(full_story):
    text = SI.format_star_plus(full_story)
    for field in SI.STAR_FIELDS:
        assert f"**{field.capitalize()}:**" in text
    assert "Rebuilt ranking cache" in text
    # Complete story: no "still needed" note
    assert "Still needed" not in text


def test_format_star_plus_flags_missing():
    text = SI.format_star_plus("Shipped a thing")
    assert "Still needed" in text
    assert "influence" in text


# ---------------------------------------------------------------------------
# influence_score
# ---------------------------------------------------------------------------

def test_influence_score_orders_by_scope():
    big = SI.upgrade_star({
        "action": "Did X",
        "result": "Latency down 40%",
        "influence": "Adopted by 3 teams org-wide; mentored 2 engineers",
    })
    small = SI.upgrade_star({
        "action": "Did Y",
        "result": "Fixed a bug",
        "influence": "Helped my team",
    })
    assert SI.influence_score(big) > SI.influence_score(small)


def test_influence_score_never_invents():
    out = SI.upgrade_star({"bullet": "no numbers here at all"})
    assert SI.influence_score(out) >= 0


# ---------------------------------------------------------------------------
# extract_metrics
# ---------------------------------------------------------------------------

def test_extract_metrics_only_what_is_present():
    found = SI.extract_metrics(
        "Cut p99 latency 40% and saved 2 weeks of work", source="story: x"
    )
    values = [m["value"] for m in found]
    assert "40%" in values
    assert "2weeks" in values
    for m in found:
        assert m["source"] == "story: x"
        assert m["context"]


def test_extract_metrics_no_numbers():
    assert SI.extract_metrics("Did good work, shipped on time", "s") == []


# ---------------------------------------------------------------------------
# build_packet / save_packet
# ---------------------------------------------------------------------------

def test_build_packet_sections(profile_dict, full_story, tracker_records):
    md = SI.build_packet(profile_dict, [full_story], tracker_records)
    assert "# Staff impact packet: Test Engineer" in md
    assert "## Impact summary" in md
    assert "## Scope trajectory" in md
    assert "## Technical leadership evidence" in md
    assert "## Mentorship evidence" in md
    assert "## Selected metrics" in md
    assert "## Open gaps" in md
    # Scope trajectory uses real role data
    assert "Senior Software Engineer" in md and "Acme" in md
    # Pipeline context only for interview/offer statuses
    assert "BigCo" in md and "SmallCo" not in md
    assert "—" not in md


def test_build_packet_metrics_attributed_and_honest(profile_dict, full_story):
    md = SI.build_packet(profile_dict, [full_story], [])
    # Metrics come from the story result and the resume bullets
    assert "62%" in md
    assert "40%" in md
    assert "(story: Rebuilt ranking cache)" in md
    assert "resume: Senior Software Engineer" in md
    # Honesty banner present
    assert "Nothing here is estimated" in md


def test_build_packet_empty_inputs():
    md = SI.build_packet({"name": "", "experience": []}, [], [])
    assert "[add detail]" in md
    assert "## Impact summary" in md


def test_build_packet_leadership_and_mentorship_lists(profile_dict):
    lead = {"bullet": "Led platform migration adopted by 2 teams",
            "result": "done", "influence": "standardized across org"}
    ment = {"bullet": "Mentored 3 junior engineers"}
    md = SI.build_packet(profile_dict, [lead, ment], [])
    assert "## Technical leadership evidence" in md
    # mentorship story shows in mentorship section
    ment_section = md.split("## Mentorship evidence")[1]
    assert "Mentored 3 junior engineers" in ment_section or "junior" in ment_section.lower()


def test_save_packet(tmp_path):
    out = SI.save_packet("# hi", tmp_path / "sub" / "packet.md")
    assert out.exists()
    assert out.read_text(encoding="utf-8") == "# hi"


# ---------------------------------------------------------------------------
# CLI main(argv)
# ---------------------------------------------------------------------------

def test_cli_story_bullet(capsys):
    rc = SI.main(["story", "--bullet", "Cut p99 latency 40%"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "**Action:** Cut p99 latency 40%" in out
    assert "**Influence:** [add detail]" in out


def test_cli_story_bullet_and_story_conflict():
    rc = SI.main(["story", "--bullet", "x", "--story", "y"])
    assert rc == 2


def test_cli_story_missing_args():
    rc = SI.main(["story"])
    assert rc == 2


def test_cli_packet_json(capsys, profile_dict, tmp_path):
    C.PROFILE_PATH.write_text(json.dumps(profile_dict), encoding="utf-8")
    rc = SI.main(["packet", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["name"] == "Test Engineer"
    assert data["ranked_stories"]
    # stories fell back to resume bullets
    assert any("40%" in s["action"] for s in data["ranked_stories"])


def test_cli_packet_writes_default_path(profile_dict, tmp_path, monkeypatch):
    C.PROFILE_PATH.write_text(json.dumps(profile_dict), encoding="utf-8")
    rc = SI.main(["packet"])
    assert rc == 0
    default = C.DATA_DIR / "staff_packet" / "staff-packet.md"
    assert default.exists()
    assert "Staff impact packet" in default.read_text(encoding="utf-8")


def test_cli_packet_out_flag(profile_dict, tmp_path):
    C.PROFILE_PATH.write_text(json.dumps(profile_dict), encoding="utf-8")
    dest = tmp_path / "my-packet.md"
    rc = SI.main(["packet", "--out", str(dest)])
    assert rc == 0
    assert dest.exists()


def test_data_dir_is_tmp():
    # DATA_DIR must resolve to a scratch dir, never the real repo candid_data.
    # NOTE: os.environ["CANDID_DATA_DIR"] is not a reliable oracle here --
    # other test modules overwrite it at import time -- so assert directly
    # against the temp dir and the real default location.
    data_dir = str(C.DATA_DIR)
    assert data_dir.startswith(tempfile.gettempdir()), data_dir
    assert data_dir != str(C.PROJECT_ROOT / "candid_data"), data_dir

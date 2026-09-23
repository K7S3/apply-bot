"""Tests for Worker C: panel planning, reverse questions, brief builder."""

from __future__ import annotations

import os

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-batch84-test-data")

from candid import brief as brief_mod
from candid import config as C
from candid import panel as panel_mod
from candid import reverse_questions as rq_mod
from candid import tracker


SAMPLE_INTERVIEWERS = [
    {
        "id": 1,
        "name": "Priya Nair",
        "role": "hiring_manager",
        "round_label": "Round 2",
        "background": {
            "title": "Engineering Manager, Ads Ranking",
            "team": "Ads Ranking",
            "tenure": "3 years",
            "focus_areas": ["ranking models", "online experiments"],
            "talks": [{"title": "Learning to rank", "topics": ["ranking", "ML"]}],
            "notes": "Met at a meetup.",
        },
        "debrief": {
            "asked": ["Tell me about a conflict"],
            "signals": ["pressed on metrics"],
            "follow_up": "Send the experiment write-up.",
        },
    },
    {
        "id": 2,
        "name": "Tom Alvarez",
        "role": "peer_engineer",
        "round_label": "Round 3",
        "background": {"focus_areas": ["serving infra"]},
    },
    {
        "id": 3,
        "name": "Grace Liu",
        "role": "bar_raiser",
        "round_label": "Round 4",
        "background": {},
    },
    {
        "id": 4,
        "name": "Sam Park",
        "role": "recruiter",
        "round_label": "Round 1",
        "background": {},
    },
]

BULLETS = [
    "Cut p99 latency 40% by rewriting the ranking feature pipeline.",
    "Led a 4-engineer squad through a messy ads migration.",
    "Built the on-call runbook that halved MTTR.",
    "Shipped an A/B testing framework used by 3 teams.",
    "Mentored two interns to full-time offers.",
]


def test_panel_assigns_distinct_primary_categories():
    plan = panel_mod.plan_panel(SAMPLE_INTERVIEWERS)
    primaries = [a["focus_categories"][0] for a in plan["assignments"]]
    assert len(primaries) == len(set(primaries)), f"duplicate primaries: {primaries}"
    assert len(plan["assignments"]) == 4


def test_panel_tie_resolved_by_role_priority():
    ivs = [
        {"name": "A", "role": "peer_engineer", "background": {}},
        {"name": "B", "role": "peer_engineer", "background": {}},
    ]
    plan = panel_mod.plan_panel(ivs)
    primaries = [a["focus_categories"][0] for a in plan["assignments"]]
    assert primaries[0] != primaries[1]


def test_panel_no_repeated_talking_points():
    plan = panel_mod.plan_panel(SAMPLE_INTERVIEWERS, profile_bullets=BULLETS)
    all_points = [tp for a in plan["assignments"] for tp in a["talking_points"]]
    assert len(all_points) == len(set(all_points)) == len(BULLETS)
    # round-robin: first assignment gets bullets 0 and 4
    first = plan["assignments"][0]["talking_points"]
    assert BULLETS[0] in first


def test_panel_avoid_lists_earlier_categories():
    plan = panel_mod.plan_panel(SAMPLE_INTERVIEWERS)
    for i, a in enumerate(plan["assignments"]):
        assert len(a["avoid"]) == i
    assert "don't repeat your" in plan["assignments"][1]["avoid"][0]


def test_panel_strategy_notes_count():
    plan = panel_mod.plan_panel(SAMPLE_INTERVIEWERS)
    assert 3 <= len(plan["strategy_notes"]) <= 5


def test_reverse_questions_per_role_non_empty():
    for role in ("hiring_manager", "peer_engineer", "bar_raiser",
                 "recruiter", "skip_level", "domain_specialist"):
        qs = rq_mod.questions_for_role(role)
        assert len(qs) == 5, role
        assert all(q.strip() for q in qs)


def test_reverse_questions_unknown_role_falls_back():
    qs = rq_mod.questions_for_role("mystery_role")
    assert qs == rq_mod.questions_for_role("generic")
    assert len(qs) > 0


def test_reverse_questions_for_panel_dedups():
    panel_qs = rq_mod.questions_for_panel(["hiring_manager", "peer_engineer", "nope"])
    flat = [q for qs in panel_qs.values() for q in qs]
    assert len(flat) == len({q.strip().lower() for q in flat})
    assert set(panel_qs) == {"hiring_manager", "peer_engineer", "nope"}
    assert panel_qs["nope"]  # fallback is non-empty


def test_build_brief_contains_all_sections_and_names():
    md = brief_mod.build_brief(
        SAMPLE_INTERVIEWERS,
        company="Acme",
        role_title="ML Engineer",
        jd_text="ranking models and online experiments",
        profile_bullets=BULLETS,
        questions_db=["Tell me about a conflict",
                      {"q": "Design a ranking system", "category": "system design",
                       "source": "reported"}],
    )
    assert md.startswith("# Interview brief: Acme")
    for header in brief_mod.SECTION_HEADERS:
        assert header in md, f"missing section: {header}"
    for iv in SAMPLE_INTERVIEWERS:
        assert iv["name"] in md
    assert "ML Engineer" in md
    # debrief history renders
    assert "pressed on metrics" in md
    # reverse questions render
    assert "What does success look like in the first 90 days?" in md


def test_build_brief_no_em_dashes():
    md = brief_mod.build_brief(SAMPLE_INTERVIEWERS, company="Acme",
                               questions_db=["Q1"])
    assert "\u2014" not in md
    plan = panel_mod.plan_panel(SAMPLE_INTERVIEWERS, profile_bullets=BULLETS)
    for a in plan["assignments"]:
        for tp in a["talking_points"] + a["avoid"]:
            assert "\u2014" not in tp
    for note in plan["strategy_notes"]:
        assert "\u2014" not in note
    for qs in rq_mod.REVERSE_QUESTIONS.values():
        for q in qs:
            assert "\u2014" not in q


def test_save_brief_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "DATA_DIR", tmp_path)
    path = brief_mod.save_brief("# hi", "Acme Corp!")
    assert path == tmp_path / "briefs" / "acme-corp.md"
    assert path.read_text(encoding="utf-8") == "# hi"


def test_brief_section_for_prep_empty_with_no_data(monkeypatch):
    monkeypatch.setattr(tracker, "list_apps", lambda **kw: [])
    assert brief_mod.brief_section_for_prep("Acme") == ""


def test_brief_section_for_prep_with_data(monkeypatch):
    monkeypatch.setattr(tracker, "list_apps", lambda **kw: [{"id": 7, "company": "Acme"}])
    monkeypatch.setattr(
        brief_mod.roster, "list_interviewers",
        lambda app_id=None, **kw: SAMPLE_INTERVIEWERS if app_id == 7 else [],
    )
    section = brief_mod.brief_section_for_prep("Acme")
    assert section.startswith("## Interview brief")
    assert "Priya Nair" in section
    assert "Grace Liu" in section

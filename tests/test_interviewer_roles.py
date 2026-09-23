"""Tests for candid.interviewer_roles and candid.brief_rank."""

from candid import brief_rank
from candid.brief_rank import rank_questions, topic_deep_dives
from candid.interviewer_roles import ROLES, ROLE_PROFILES, get_role_profile, list_roles

REQUIRED_PROFILE_KEYS = {
    "label",
    "description",
    "evaluates",
    "angle_categories",
    "likely_angles",
    "prep_tips",
    "tells",
}


def test_every_role_has_a_complete_profile():
    for role in ROLES:
        profile = get_role_profile(role)
        assert REQUIRED_PROFILE_KEYS <= set(profile), role
        assert profile["label"], role
        assert profile["description"], role
        assert len(profile["evaluates"]) >= 1, role
        assert len(profile["angle_categories"]) >= 1, role
        assert 4 <= len(profile["likely_angles"]) <= 6, role
        assert 3 <= len(profile["prep_tips"]) <= 5, role
        assert 2 <= len(profile["tells"]) <= 3, role


def test_canonical_roles_are_defined():
    for role in [
        "hiring_manager",
        "peer_engineer",
        "bar_raiser",
        "recruiter",
        "skip_level",
        "domain_specialist",
    ]:
        assert role in ROLE_PROFILES, role
        assert role in list_roles(), role


def test_role_lookup_is_case_insensitive():
    assert get_role_profile("HIRING_MANAGER") == get_role_profile("hiring_manager")
    assert get_role_profile("Bar_Raiser")["label"] == "Bar Raiser"


def test_unknown_role_falls_back_never_keyerror():
    for odd in ["wizard", "", "VP OF VIBES", None, 42]:
        profile = get_role_profile(odd)
        assert REQUIRED_PROFILE_KEYS <= set(profile)
        assert profile["angle_categories"]


def test_list_roles_returns_role_keys():
    assert list_roles() == list(ROLES)


def test_ranking_prefers_role_matching_categories():
    questions = [
        {"q": "Write a SQL window query for a 7-day rolling average.", "category": "sql"},
        {"q": "Tell me about a time you disagreed with a stakeholder.", "category": "behavioral"},
    ]
    ranked = rank_questions(questions, role="hiring_manager")
    assert len(ranked) == 2
    assert ranked[0][0]["category"] == "behavioral"
    assert ranked[0][1] > ranked[1][1]
    assert "behavioral" in ranked[0][2]


def test_ranking_bonus_weighs_early_angle_categories_more():
    questions = [
        {"q": "Design an A/B test for a new feature.", "category": "stats"},
        {"q": "Tell me about a time you owned a project end to end.", "category": "behavioral"},
    ]
    ranked = rank_questions(questions, role="hiring_manager")
    assert ranked[0][0]["category"] == "behavioral"
    assert ranked[1][0]["category"] == "stats"


def test_jd_overlap_changes_ordering():
    questions = [
        {"q": "Tell me about a time you disagreed with a stakeholder.", "category": "behavioral"},
        {"q": "Describe a project where you built a kafka pipeline.", "category": "behavioral"},
    ]
    jd = "We need kafka pipeline experience for this role."
    ranked = rank_questions(questions, role="recruiter", jd_text=jd)
    assert ranked[0][0]["q"].startswith("Describe a project")
    assert "2 JD keyword hits" in ranked[0][2]
    assert ranked[1][0]["q"].startswith("Tell me about")


def test_source_bonus_rewards_company_verified_questions():
    questions = [
        {"q": "Design an A/B test for a new feature.", "category": "stats"},
        {
            "q": "Design an A/B test for a new feature, exactly as asked at Meta.",
            "category": "stats",
            "source": "Interview Query",
        },
    ]
    ranked = rank_questions(questions, role="domain_specialist")
    assert ranked[0][0]["source"] == "Interview Query"
    assert "company-verified" in ranked[0][2]


def test_ranking_keeps_input_order_on_ties():
    questions = [
        {"q": "First question here.", "category": "unknown_cat"},
        {"q": "Second question here.", "category": "unknown_cat"},
    ]
    ranked = rank_questions(questions, role="recruiter")
    assert [r[0]["q"] for r in ranked] == ["First question here.", "Second question here."]


def test_rationale_strings_are_non_empty():
    questions = [
        {"q": "Write a SQL window query.", "category": "sql"},
        {"q": "Something with no category at all."},
        {"q": "Tell me about a conflict.", "category": "behavioral", "source": "LeetCode"},
    ]
    for _, score, rationale in rank_questions(questions, role="hiring_manager", jd_text=""):
        assert isinstance(rationale, str) and rationale.strip()
        assert isinstance(score, (int, float))


def test_unknown_role_still_ranks_without_error():
    questions = [{"q": "Tell me about yourself.", "category": "behavioral"}]
    ranked = rank_questions(questions, role="chief_vibes_officer", jd_text="hiring")
    assert len(ranked) == 1
    assert ranked[0][2].strip()


def test_topic_deep_dives_returns_generated_flagged_items():
    dives = topic_deep_dives(["retrieval-augmented generation"], n=3)
    assert len(dives) == 3
    for item in dives:
        assert item["generated"] is True
        assert item["topic"] == "retrieval-augmented generation"
        assert "retrieval-augmented generation" in item["question"]
        assert item["angle"]


def test_topic_deep_dives_is_deterministic_and_labeled_generated():
    topics = ["feature stores", "embeddings"]
    first = topic_deep_dives(topics, role="domain_specialist", n=4)
    second = topic_deep_dives(topics, role="domain_specialist", n=4)
    assert first == second
    assert len(first) == 8
    assert "generated" in brief_rank.topic_deep_dives.__doc__.lower()
    assert "not verified" in brief_rank.topic_deep_dives.__doc__.lower()


def test_topic_deep_dives_honors_role_and_empty_topics():
    dives = topic_deep_dives(["x"], role="peer_engineer", n=2)
    assert all("peer-engineer" in d["angle"] for d in dives)
    assert topic_deep_dives([], n=5) == []
    assert topic_deep_dives(["x"], n=0) == []


def test_no_em_dashes_in_new_modules():
    import pathlib

    for name in ("candid/interviewer_roles.py", "candid/brief_rank.py"):
        text = pathlib.Path(name).read_text(encoding="utf-8")
        assert "\u2014" not in text, name

"""Tests for the PM question bank (candid.pm_questions) and PM concept
deep-dives (candid.pm_concepts). No network, no LLM: pure data checks.
"""

from __future__ import annotations

import argparse
import contextlib
import inspect
import io
import json

import pytest

from candid import pm_questions as PQ
from candid import pm_concepts as PC

REQUIRED_KEYS = {"q", "category", "company", "source", "url", "reported"}


def _all_entries() -> list[dict]:
    out: list[dict] = []
    for entries in PQ.PM_QUESTIONS_DB.values():
        out.extend(entries)
    return out


# ---------------------------------------------------------------------------
# Bank integrity
# ---------------------------------------------------------------------------

def test_bank_has_at_least_40_questions():
    assert len(_all_entries()) >= 40


def test_every_entry_has_q():
    for e in _all_entries():
        assert e.get("q") and e["q"].strip(), f"missing q: {e}"


def test_every_entry_has_source():
    for e in _all_entries():
        assert e.get("source") and e["source"].strip(), f"missing source: {e['q']}"


def test_every_entry_has_url():
    for e in _all_entries():
        assert e.get("url") and e["url"].startswith("http"), f"bad url: {e['q']}"


def test_every_entry_has_reported():
    for e in _all_entries():
        assert e.get("reported") and e["reported"].strip(), f"missing reported: {e['q']}"


def test_every_entry_has_required_keys():
    for e in _all_entries():
        assert REQUIRED_KEYS.issubset(e.keys()), f"missing keys in: {e['q']}"


def test_entry_company_matches_bank_key():
    for key, entries in PQ.PM_QUESTIONS_DB.items():
        for e in entries:
            assert e["company"] == key, f"{e['q']}: company {e['company']} != key {key}"


def test_categories_are_valid():
    valid = set(PQ.CATEGORIES)
    for e in _all_entries():
        assert e["category"] in valid, f"bad category {e['category']}: {e['q']}"


def test_core_categories_present():
    cats = {e["category"] for e in _all_entries()}
    for needed in ("product_sense", "metrics", "execution", "estimation",
                   "behavioral"):
        assert needed in cats


def test_company_keys_normalized():
    for key in PQ.PM_QUESTIONS_DB:
        assert key == key.lower(), f"company key not lowercase: {key}"
        assert key == key.strip()


def test_general_bank_clearly_labeled():
    assert "general" in PQ.PM_QUESTIONS_DB
    assert len(PQ.PM_QUESTIONS_DB["general"]) >= 5


def test_target_companies_have_entries():
    for co in ("google", "meta", "amazon", "microsoft", "apple", "stripe",
               "openai"):
        assert co in PQ.PM_QUESTIONS_DB, f"missing company bank: {co}"
        assert len(PQ.PM_QUESTIONS_DB[co]) >= 2, f"too few for {co}"


# ---------------------------------------------------------------------------
# Query API
# ---------------------------------------------------------------------------

def test_companies_returns_sorted_unique():
    cos = PQ.companies()
    assert cos == sorted(cos)
    assert len(cos) == len(set(cos))
    assert "general" in cos
    assert "google" in cos


def test_list_questions_no_filter_returns_all():
    assert len(PQ.list_questions()) == len(_all_entries())


def test_list_questions_category_filter():
    metrics = PQ.list_questions(category="metrics")
    assert metrics, "no metrics questions"
    assert all(e["category"] == "metrics" for e in metrics)


def test_list_questions_company_filter_case_insensitive():
    a = PQ.list_questions(company="Google")
    b = PQ.list_questions(company="google")
    assert a and a == b
    assert all(e["company"] == "google" for e in a)


def test_list_questions_company_alias():
    assert PQ.list_questions(company="facebook") == PQ.list_questions(company="meta")


def test_list_questions_combined_filters():
    res = PQ.list_questions(category="execution", company="meta")
    assert res, "expected meta execution questions"
    assert all(e["company"] == "meta" and e["category"] == "execution"
               for e in res)


def test_list_questions_unknown_filter_returns_empty():
    assert PQ.list_questions(category="nope") == []
    assert PQ.list_questions(company="nope-co") == []


def test_search_questions_finds_keyword():
    hits = PQ.search_questions("checkout")
    assert hits, "expected a hit for 'checkout'"
    assert any("checkout" in h["q"].lower() for h in hits)


def test_search_questions_case_insensitive():
    assert PQ.search_questions("YOUTUBE") == PQ.search_questions("youtube")


def test_search_questions_matches_source():
    hits = PQ.search_questions("IGotAnOffer")
    assert hits, "expected hits in source field"


def test_search_questions_no_match():
    assert PQ.search_questions("zzzzqqq") == []


def test_search_questions_empty_query():
    assert PQ.search_questions("") == []


# ---------------------------------------------------------------------------
# Prep-pack hook
# ---------------------------------------------------------------------------

def test_bank_section_shape():
    sec = PQ.build_pm_bank_section("Google", "Product Manager")
    assert set(sec) >= {"company", "role", "company_questions",
                        "general_must_knows", "categories_covered", "note"}
    assert sec["company"] == "google"
    assert sec["role"] == "Product Manager"


def test_bank_section_company_questions_tagged():
    sec = PQ.build_pm_bank_section("meta", "PM")
    assert sec["company_questions"], "expected meta-tagged questions"
    assert all(e["company"] == "meta" for e in sec["company_questions"])
    assert all(REQUIRED_KEYS.issubset(e.keys())
               for e in sec["company_questions"])


def test_bank_section_general_must_knows():
    sec = PQ.build_pm_bank_section("stripe", "PM")
    assert sec["general_must_knows"], "expected general must-knows"
    assert all(e["company"] == "general" for e in sec["general_must_knows"])
    cats = {e["category"] for e in sec["general_must_knows"]}
    assert {"product_sense", "metrics", "execution", "estimation",
            "behavioral"} <= cats


def test_bank_section_unknown_company_falls_back_to_general():
    sec = PQ.build_pm_bank_section("acme-corp", "PM")
    assert sec["company_questions"] == []
    assert sec["general_must_knows"], "fallback generals should still exist"


def test_bank_section_dependency_free():
    src = inspect.getsource(PQ.build_pm_bank_section)
    assert "candid." not in src
    assert "import " not in src


# ---------------------------------------------------------------------------
# Concepts
# ---------------------------------------------------------------------------

def test_concepts_at_least_12():
    assert len(PC.list_concepts()) >= 12


def test_concept_keys_present():
    keys = set(PC.list_concepts())
    for needed in ("funnels", "retention_cohorts", "north_star", "okrs",
                   "prioritization", "ab_testing", "unit_economics",
                   "network_effects", "pricing", "gtm",
                   "experimentation_pitfalls", "stakeholder_mgmt"):
        assert needed in keys, f"missing concept: {needed}"


def test_every_concept_has_required_fields():
    for key in PC.list_concepts():
        c = PC.get_concept(key)
        for field in ("name", "summary", "key_points", "pitfalls",
                      "interview_angle"):
            assert c.get(field), f"{key}: missing/empty {field}"
        assert isinstance(c["key_points"], list) and c["key_points"]
        assert isinstance(c["pitfalls"], list) and c["pitfalls"]


def test_get_concept_case_insensitive():
    assert PC.get_concept("North_Star") == PC.get_concept("north_star")


def test_get_concept_by_display_name():
    c = PC.get_concept("A/B Testing")
    assert c["name"] == "A/B Testing for PMs"


def test_get_concept_unknown_raises():
    with pytest.raises(PQ.PMError):
        PC.get_concept("teleportation")


def test_concepts_for_category():
    res = PC.concepts_for_category("metrics")
    assert res, "expected concepts for metrics"
    names = [c["name"] for c in res]
    assert "North Star Metric" in names


def test_concepts_for_unknown_category_empty():
    assert PC.concepts_for_category("nope") == []


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

def _pm_parser():
    top = argparse.ArgumentParser()
    return top, top.add_subparsers(dest="pm_cmd")


def _run(args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        args.func(args)
    return buf.getvalue()


def test_register_pm_questions_text_output():
    top, subs = _pm_parser()
    PQ.register_pm(subs)
    args = top.parse_args(["questions", "--company", "google"])
    out = _run(args)
    assert "youtube" in out.lower() or "google" in out.lower()
    assert "http" in out  # source urls shown


def test_register_pm_questions_json_output():
    top, subs = _pm_parser()
    PQ.register_pm(subs)
    args = top.parse_args(["questions", "--category", "estimation", "--json"])
    data = json.loads(_run(args))
    assert isinstance(data, list) and data
    assert all(e["category"] == "estimation" for e in data)


def test_register_pm_questions_query():
    top, subs = _pm_parser()
    PQ.register_pm(subs)
    args = top.parse_args(["questions", "--query", "checkout", "--json"])
    data = json.loads(_run(args))
    assert data, "expected query hits"
    assert any("checkout" in e["q"].lower() for e in data)


def test_register_pm_concepts_text_output():
    top, subs = _pm_parser()
    PC.register_pm(subs)
    args = top.parse_args(["concepts", "--name", "north_star"])
    out = _run(args)
    assert "North Star Metric" in out
    assert "Interview angle" in out


def test_register_pm_concepts_json_output():
    top, subs = _pm_parser()
    PC.register_pm(subs)
    args = top.parse_args(["concepts", "--json"])
    data = json.loads(_run(args))
    assert isinstance(data, list) and len(data) >= 12


def test_register_pm_both_subcommands_coexist():
    top, subs = _pm_parser()
    PQ.register_pm(subs)
    PC.register_pm(subs)
    a = top.parse_args(["questions", "--json"])
    b = top.parse_args(["concepts", "--json"])
    assert json.loads(_run(a))
    assert json.loads(_run(b))

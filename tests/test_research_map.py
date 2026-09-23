"""Tests for candid/research_map.py (prior-work map + rebuttal trainer).

No network, no fixtures on disk besides tmp_path. All entry/critique
data below is synthetic test data, clearly invented for tests only.
"""

from __future__ import annotations

import json

import pytest

from candid import research_map as rm


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

SAMPLE_ENTRIES = [
    {
        "title": "RankEval",
        "year": 2024,
        "kind": "project",
        "areas": ["ads ranking", "evaluation"],
        "claims": ["Novel pairwise ranking objective",
                   "Improved offline AUC by 3.2%"],
        "techniques": ["pytorch", "two-tower"],
    },
    {
        "title": "ServeFast",
        "year": 2023,
        "kind": "project",
        "areas": ["ads ranking"],
        "claims": ["Designed a low-latency serving path"],
        "techniques": ["pytorch", "onnx"],
    },
    {
        "title": "Calibration under shift",
        "year": 2022,
        "kind": "publication",
        "areas": ["evaluation"],
        "claims": ["Proposed a recalibration method"],
        "techniques": ["scikit-learn"],
    },
]


def _rb_path(tmp_path):
    return tmp_path / "rebuttals.json"


# ---------------------------------------------------------------------------
# feature 1: build_map
# ---------------------------------------------------------------------------

def test_build_map_timeline_sorted():
    m = rm.build_map(list(reversed(SAMPLE_ENTRIES)))
    years = [e["year"] for e in m["timeline"]]
    assert years == [2022, 2023, 2024]


def test_build_map_counts_kinds():
    m = rm.build_map(SAMPLE_ENTRIES)
    assert m["entry_count"] == 3
    assert m["projects"] == 2
    assert m["publications"] == 1


def test_build_map_area_coverage():
    m = rm.build_map(SAMPLE_ENTRIES)
    assert m["area_coverage"]["ads ranking"] == 2
    assert m["area_coverage"]["evaluation"] == 2


def test_build_map_technique_frequency():
    m = rm.build_map(SAMPLE_ENTRIES)
    assert m["technique_frequency"]["pytorch"] == 2
    assert m["technique_frequency"]["onnx"] == 1


def test_build_map_claims_index_links_claim_to_entry():
    m = rm.build_map(SAMPLE_ENTRIES)
    by_claim = {c["claim"]: c for c in m["claims_index"]}
    assert by_claim["Novel pairwise ranking objective"]["entry"] == "RankEval"
    assert by_claim["Improved offline AUC by 3.2%"]["claim_kind"] == "empirical"
    assert by_claim["Novel pairwise ranking objective"]["claim_kind"] == "method"


def test_build_map_years_summary():
    m = rm.build_map(SAMPLE_ENTRIES)
    assert m["years"]["start"] == 2022
    assert m["years"]["end"] == 2024
    assert m["years"]["by_year"] == {2022: 1, 2023: 1, 2024: 1}
    assert m["years"]["undated"] == 0


def test_build_map_empty_entries():
    m = rm.build_map([])
    assert m["entry_count"] == 0
    assert m["timeline"] == []
    assert m["area_coverage"] == {}
    gaps = rm.gap_observations(m)
    assert len(gaps) == 1
    assert "no entries" in gaps[0]["observation"].lower()


def test_build_map_defaults_kind_to_project():
    m = rm.build_map([{"title": "Solo"}])
    assert m["projects"] == 1
    assert m["publications"] == 0


def test_entry_missing_title_raises():
    with pytest.raises(rm.ResearchMapError):
        rm.build_map([{"year": 2024}])


def test_entry_not_dict_raises():
    with pytest.raises(rm.ResearchMapError):
        rm.build_map(["not a dict"])


def test_entry_bad_kind_raises():
    with pytest.raises(rm.ResearchMapError):
        rm.build_map([{"title": "X", "kind": "patent"}])


def test_entry_year_coerced_from_string():
    m = rm.build_map([{"title": "X", "year": "2021"}])
    assert m["timeline"][0]["year"] == 2021


def test_entry_bad_year_raises():
    with pytest.raises(rm.ResearchMapError):
        rm.build_map([{"title": "X", "year": "soon"}])


def test_entry_single_string_list_fields():
    m = rm.build_map([{"title": "X", "areas": "nlp", "techniques": "bert"}])
    assert m["timeline"][0]["areas"] == ["nlp"]
    assert m["technique_frequency"] == {"bert": 1}


# ---------------------------------------------------------------------------
# feature 1: gap observations
# ---------------------------------------------------------------------------

def test_gap_area_missing_in_last_two_years():
    entries = [
        {"title": "Old", "year": 2019, "areas": ["time series"]},
        {"title": "New", "year": 2026, "areas": ["nlp"]},
    ]
    gaps = rm.gap_observations(rm.build_map(entries))
    obs = [g["observation"] for g in gaps]
    assert any("time series" in o and "last 2 years" in o for o in obs)
    assert not any("'nlp'" in o for o in obs)


def test_gap_all_method_claims_none_empirical():
    entries = [
        {"title": "A", "year": 2024, "claims": ["Proposed a novel framework"]},
        {"title": "B", "year": 2025, "claims": ["Designed a new architecture"]},
    ]
    gaps = rm.gap_observations(rm.build_map(entries))
    assert any("all claims are method claims" in g["observation"].lower()
               for g in gaps)


def test_gap_no_publications():
    gaps = rm.gap_observations(rm.build_map(
        [{"title": "A", "year": 2024, "kind": "project"}]))
    assert any("no publications" in g["observation"].lower() for g in gaps)


def test_gap_no_claims_at_all():
    gaps = rm.gap_observations(rm.build_map([{"title": "A", "year": 2024}]))
    assert any("no contribution claims" in g["observation"].lower()
               for g in gaps)


def test_gaps_every_suggestion_labeled_heuristic():
    gaps = rm.gap_observations(rm.build_map(SAMPLE_ENTRIES))
    assert gaps, "expected at least one gap for the sample entries"
    for g in gaps:
        assert "heuristic" in g["suggestion"].lower()
        assert "not a fact" in g["suggestion"].lower()


def test_gap_balanced_map_has_no_method_only_gap():
    entries = [
        {"title": "A", "year": 2026,
         "claims": ["Proposed a novel framework", "Improved AUC by 2%"]},
        {"title": "B", "year": 2026, "kind": "publication",
         "claims": ["Evaluated on three benchmarks"]},
    ]
    gaps = rm.gap_observations(rm.build_map(entries))
    assert not any("all claims are method claims" in g["observation"].lower()
                   for g in gaps)
    assert not any("no publications" in g["observation"].lower()
                   for g in gaps)


# ---------------------------------------------------------------------------
# feature 1: rendering
# ---------------------------------------------------------------------------

def test_render_map_text_sections():
    text = rm.render_map(rm.build_map(SAMPLE_ENTRIES))
    for section in ("Timeline", "Area coverage", "Technique frequency",
                    "Claims index", "Gap observations"):
        assert section in text
    assert "RankEval" in text
    assert "2022" in text


def test_render_map_md_sections():
    md = rm.render_map_md(rm.build_map(SAMPLE_ENTRIES))
    for header in ("# Prior-work map", "## Timeline", "## Area coverage",
                   "## Technique frequency", "## Claims index",
                   "## Gap observations"):
        assert header in md
    assert "| 2024 | RankEval |" in md


def test_render_empty_map():
    text = rm.render_map(rm.build_map([]))
    assert "0 entries" in text
    md = rm.render_map_md(rm.build_map([]))
    assert "# Prior-work map" in md


# ---------------------------------------------------------------------------
# feature 1: loading entries
# ---------------------------------------------------------------------------

def test_load_entries_from_list():
    assert rm.load_entries(SAMPLE_ENTRIES) == SAMPLE_ENTRIES


def test_load_entries_from_json_file(tmp_path):
    p = tmp_path / "entries.json"
    p.write_text(json.dumps(SAMPLE_ENTRIES), encoding="utf-8")
    assert rm.load_entries(p) == SAMPLE_ENTRIES


def test_load_entries_from_json_object_wrapper(tmp_path):
    p = tmp_path / "entries.json"
    p.write_text(json.dumps({"entries": SAMPLE_ENTRIES}), encoding="utf-8")
    assert rm.load_entries(str(p)) == SAMPLE_ENTRIES


def test_load_entries_missing_file_raises(tmp_path):
    with pytest.raises(rm.ResearchMapError):
        rm.load_entries(tmp_path / "nope.json")


def test_load_entries_bad_json_raises(tmp_path):
    p = tmp_path / "entries.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(rm.ResearchMapError):
        rm.load_entries(p)


def test_load_profile_projects(tmp_path):
    p = tmp_path / "profile.json"
    p.write_text(json.dumps({"name": "Test", "projects": SAMPLE_ENTRIES}),
                 encoding="utf-8")
    assert rm.load_entries(profile_path=p) == SAMPLE_ENTRIES


def test_load_entries_profile_fallback_empty(tmp_path):
    # no profile file at all -> clean fallback, no exception
    assert rm.load_entries(profile_path=tmp_path / "missing.json") == []
    # profile without a "projects" key -> clean fallback
    p = tmp_path / "profile.json"
    p.write_text(json.dumps({"name": "Test"}), encoding="utf-8")
    assert rm.load_entries(profile_path=p) == []


# ---------------------------------------------------------------------------
# feature 2: rebuttal trainer
# ---------------------------------------------------------------------------

def test_add_critique_classifies_novelty(tmp_path):
    c = rm.add_critique("This feels incremental over prior work.",
                        path=_rb_path(tmp_path))
    assert c["type"] == "novelty"
    assert c["status"] == "pending"
    assert c["draft"] == ""
    assert c["id"] == 1


def test_add_critique_classifies_experiments(tmp_path):
    c = rm.add_critique("Please add an ablation study of the two components.",
                        path=_rb_path(tmp_path))
    assert c["type"] == "experiments"


def test_add_critique_classifies_clarity(tmp_path):
    c = rm.add_critique("Section 3 is unclear and hard to follow.",
                        path=_rb_path(tmp_path))
    assert c["type"] == "clarity"


def test_add_critique_classifies_baselines(tmp_path):
    c = rm.add_critique("Missing comparison to standard baselines.",
                        path=_rb_path(tmp_path))
    assert c["type"] == "baselines"


def test_add_critique_classifies_significance(tmp_path):
    c = rm.add_critique("The contribution seems marginal in impact.",
                        path=_rb_path(tmp_path))
    assert c["type"] == "significance"


def test_add_critique_classifies_scope(tmp_path):
    c = rm.add_critique("The scope is narrow; it only covers one domain.",
                        path=_rb_path(tmp_path))
    assert c["type"] == "scope"


def test_add_critique_unknown_type_is_other(tmp_path):
    c = rm.add_critique("What is the runtime in milliseconds?",
                        path=_rb_path(tmp_path))
    assert c["type"] == "other"


def test_add_critique_empty_raises(tmp_path):
    with pytest.raises(rm.ResearchMapError):
        rm.add_critique("   ", path=_rb_path(tmp_path))


def test_add_critique_ids_increment(tmp_path):
    p = _rb_path(tmp_path)
    a = rm.add_critique("First critique.", path=p)
    b = rm.add_critique("Second critique.", path=p)
    assert (a["id"], b["id"]) == (1, 2)


def test_suggest_template_structure(tmp_path):
    p = _rb_path(tmp_path)
    c = rm.add_critique("Needs more baselines.", path=p)
    tpl = rm.suggest_template(c)
    low = tpl.lower()
    assert "acknowledge" in low
    assert "clarify" in low
    assert "evidence" in low or "commitment" in low
    assert "never" in low  # warns against inventing data


def test_suggest_template_accepts_id(tmp_path):
    p = _rb_path(tmp_path)
    c = rm.add_critique("Section 2 is confusing.", path=p)
    assert rm.suggest_template(c["id"], p) == rm.suggest_template(c)


def test_draft_response_stores_draft(tmp_path):
    p = _rb_path(tmp_path)
    c = rm.add_critique("Unclear notation.", path=p)
    rec = rm.draft_response(c["id"], "We will add a notation table.", path=p)
    assert rec["draft"] == "We will add a notation table."
    assert rec["status"] == "pending"  # drafting does not auto-address


def test_draft_response_missing_id_raises(tmp_path):
    with pytest.raises(rm.ResearchMapError):
        rm.draft_response(99, "draft", path=_rb_path(tmp_path))


def test_mark_addressed(tmp_path):
    p = _rb_path(tmp_path)
    c = rm.add_critique("Unclear notation.", path=p)
    rec = rm.mark_addressed(c["id"], path=p)
    assert rec["status"] == "addressed"
    assert rm.list_critiques(status="addressed", path=p)[0]["id"] == c["id"]
    assert rm.list_critiques(status="pending", path=p) == []


def test_mark_addressed_missing_id_raises(tmp_path):
    with pytest.raises(rm.ResearchMapError):
        rm.mark_addressed(99, path=_rb_path(tmp_path))


def test_rebuttal_progress(tmp_path):
    p = _rb_path(tmp_path)
    assert rm.rebuttal_progress(path=p) == {
        "total": 0, "addressed": 0, "pending": 0, "percent_addressed": 0.0}
    a = rm.add_critique("First.", path=p)
    rm.add_critique("Second.", path=p)
    rm.mark_addressed(a["id"], path=p)
    stats = rm.rebuttal_progress(path=p)
    assert stats == {"total": 2, "addressed": 1, "pending": 1,
                     "percent_addressed": 50.0}


def test_persistence_round_trip(tmp_path):
    p = _rb_path(tmp_path)
    c = rm.add_critique("Needs baselines.", path=p)
    rm.draft_response(c["id"], "Will add.", path=p)
    # reload from disk via a fresh read
    stored = json.loads(p.read_text(encoding="utf-8"))
    assert stored["critiques"][0]["draft"] == "Will add."
    assert rm.get_critique(c["id"], path=p)["type"] == "baselines"


def test_get_critique_missing_raises(tmp_path):
    with pytest.raises(rm.ResearchMapError):
        rm.get_critique(42, path=_rb_path(tmp_path))


def test_list_critiques_bad_status_raises(tmp_path):
    with pytest.raises(rm.ResearchMapError):
        rm.list_critiques(status="done", path=_rb_path(tmp_path))

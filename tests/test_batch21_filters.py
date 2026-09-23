"""Tests for candid/jobs_startup_filters.py (candid batch 21)."""

import argparse
import json
import os
import sys
import tempfile

# Point the data dir at a scratch dir BEFORE candid.config is imported,
# and patch it explicitly: the env var alone is order-dependent because
# candid.config binds DATA_DIR at first import (another test module may
# import it first in a full-suite run).
_TMP = tempfile.mkdtemp(prefix="candid-startups-")
os.environ["CANDID_DATA_DIR"] = _TMP

from candid import jobs_startup_filters as SF  # noqa: E402
from candid import config as _C  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

_C.DATA_DIR = _Path(_TMP)


def _posting(company="Acme", title="", description=""):
    return {"company": company, "title": title, "description": description}


def _reset_registry():
    SF._REGISTRY_CACHE = None


def _write_registry(obj):
    _reset_registry()
    with open(os.path.join(_TMP, "startups.json"), "w", encoding="utf-8") as fh:
        json.dump(obj, fh)


def _clear_registry():
    _reset_registry()
    p = os.path.join(_TMP, "startups.json")
    if os.path.exists(p):
        os.remove(p)
    _reset_registry()


# ---------------------------------------------------------------------------
# stage inference
# ---------------------------------------------------------------------------

def test_stage_seed_keywords():
    _clear_registry()
    assert SF.infer_stage(_posting(description="Seed-funded fintech")) == "seed"
    assert SF.infer_stage(_posting(description="We are a seed stage startup")) == "seed"


def test_stage_pre_seed_beats_seed():
    _clear_registry()
    assert SF.infer_stage(_posting(description="pre-seed startup, raised seed round")) == "pre-seed"


def test_stage_series_letters():
    _clear_registry()
    assert SF.infer_stage(_posting(description="Series A company")) == "series-a"
    assert SF.infer_stage(_posting(description="just closed our series b")) == "series-b"
    assert SF.infer_stage(_posting(description="Series C")) == "series-c"
    assert SF.infer_stage(_posting(description="Series D startup")) == "series-d+"


def test_stage_series_a_beats_seed():
    _clear_registry()
    assert SF.infer_stage(_posting(description="seed stage Series A fintech")) == "series-a"


def test_stage_stealth():
    _clear_registry()
    assert SF.infer_stage(_posting(description="stealth-mode AI startup")) == "stealth"


def test_stage_founding_engineer():
    _clear_registry()
    assert SF.infer_stage(_posting(title="Founding Engineer")) == "seed"
    assert SF.infer_stage(_posting(description="join our founding team")) == "seed"


def test_stage_unknown_is_none():
    _clear_registry()
    assert SF.infer_stage(_posting(description="We build cloud software.")) is None
    assert SF.infer_stage(_posting()) is None


def test_registry_stage_overrides_text():
    _write_registry({
        "startups": [{"name": "Acme", "stage": "series-b", "employees": 80}],
    })
    p = _posting(company="Acme", description="Seed-funded rocket ship")
    assert SF.infer_stage(p) == "series-b"
    _clear_registry()


def test_registry_case_insensitive_and_list_shape():
    _write_registry([
        {"name": "BEAM inc", "stage": "stealth", "employees": 5},
    ])
    assert SF.infer_stage(_posting(company="beam INC")) == "stealth"
    _clear_registry()


def test_registry_mapping_shape():
    _write_registry({
        "Nova": {"stage": "seed", "employees": 12},
    })
    assert SF.infer_stage(_posting(company="nova")) == "seed"
    _clear_registry()


def test_missing_registry_is_text_only():
    _clear_registry()
    assert SF.infer_stage(_posting(description="seed stage")) == "seed"


def test_corrupt_registry_is_text_only():
    p = os.path.join(_TMP, "startups.json")
    _reset_registry()
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    _reset_registry()
    assert SF.infer_stage(_posting(description="series b")) == "series-b"
    _clear_registry()


# ---------------------------------------------------------------------------
# size-band inference
# ---------------------------------------------------------------------------

def test_size_explicit_ranges():
    _clear_registry()
    assert SF.infer_size_band(_posting(description="1-10 employees")) == "1-10"
    assert SF.infer_size_band(_posting(description="11-50 employees")) == "11-50"
    assert SF.infer_size_band(_posting(description="51-200 people")) == "51-200"
    assert SF.infer_size_band(_posting(description="201-500 headcount")) == "201-500"


def test_size_plus():
    _clear_registry()
    assert SF.infer_size_band(_posting(description="500+ employees")) == "501+"
    assert SF.infer_size_band(_posting(description="501+ people")) == "501+"


def test_size_team_of():
    _clear_registry()
    assert SF.infer_size_band(_posting(description="a team of 7 engineers")) == "1-10"
    assert SF.infer_size_band(_posting(description="team of ~40")) == "11-50"
    assert SF.infer_size_band(_posting(description="grown to 120 people")) == "51-200"


def test_size_founding_team():
    _clear_registry()
    assert SF.infer_size_band(_posting(description="join our founding team")) == "1-10"


def test_size_unknown_is_none():
    _clear_registry()
    assert SF.infer_size_band(_posting(description="great benefits")) is None


def test_registry_employees_overrides_text():
    _write_registry({
        "startups": [{"name": "Acme", "stage": "series-b", "employees": 130}],
    })
    p = _posting(company="Acme", description="small team of 5")
    assert SF.infer_size_band(p) == "51-200"
    _clear_registry()


def test_registry_employees_boundary_values():
    _write_registry({
        "startups": [
            {"name": "A", "employees": 10},
            {"name": "B", "employees": 11},
            {"name": "C", "employees": 500},
            {"name": "D", "employees": 501},
        ],
    })
    assert SF.infer_size_band(_posting(company="A")) == "1-10"
    assert SF.infer_size_band(_posting(company="B")) == "11-50"
    assert SF.infer_size_band(_posting(company="C")) == "201-500"
    assert SF.infer_size_band(_posting(company="D")) == "501+"
    _clear_registry()


# ---------------------------------------------------------------------------
# filter_postings
# ---------------------------------------------------------------------------

_POSTINGS = [
    _posting(company="SeedCo", title="Founding Engineer", description="seed stage, 1-10 employees"),
    _posting(company="GrowthCo", description="Series B, 51-200 people"),
    _posting(company="MegaCorp", description="Series D, 500+ employees"),
    _posting(company="MysteryCo", description="we do stuff"),
]


def test_filter_by_stage():
    _clear_registry()
    out = SF.filter_postings(_POSTINGS, stages=["seed"])
    assert [p["company"] for p in out] == ["SeedCo"]


def test_filter_by_size_band():
    _clear_registry()
    out = SF.filter_postings(_POSTINGS, size_bands=["51-200"])
    assert [p["company"] for p in out] == ["GrowthCo"]


def test_filter_coarse_size_range():
    _clear_registry()
    out = SF.filter_postings(_POSTINGS, size_bands=["1-50"])
    assert [p["company"] for p in out] == ["SeedCo"]


def test_filter_size_open_ended():
    _clear_registry()
    out = SF.filter_postings(_POSTINGS, size_bands=["500+"])
    assert [p["company"] for p in out] == ["MegaCorp"]


def test_filter_stage_and_size():
    _clear_registry()
    out = SF.filter_postings(_POSTINGS, stages=["series-b", "series-d+"], size_bands=["51-200", "501+"])
    assert [p["company"] for p in out] == ["GrowthCo", "MegaCorp"]


def test_filter_excludes_unknown_when_filtered():
    _clear_registry()
    out = SF.filter_postings(_POSTINGS, stages=["seed"])
    assert "MysteryCo" not in [p["company"] for p in out]
    out = SF.filter_postings(_POSTINGS, size_bands=["1-10"])
    assert "MysteryCo" not in [p["company"] for p in out]


def test_filter_no_filters_returns_all():
    _clear_registry()
    assert SF.filter_postings(_POSTINGS) == _POSTINGS


def test_filter_unknown_stage_raises():
    _clear_registry()
    try:
        SF.filter_postings(_POSTINGS, stages=["bogus"])
    except SF.StartupFilterError:
        pass
    else:
        raise AssertionError("expected StartupFilterError")


def test_filter_bad_size_raises():
    _clear_registry()
    try:
        SF.filter_postings(_POSTINGS, size_bands=["huge"])
    except SF.StartupFilterError:
        pass
    else:
        raise AssertionError("expected StartupFilterError")


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def test_add_filter_args_registers_flags():
    parser = argparse.ArgumentParser()
    SF.add_filter_args(parser)
    args = parser.parse_args(["--stage", "seed,series-a", "--size", "1-50,51-200"])
    assert args.stage == "seed,series-a"
    assert args.size == "1-50,51-200"
    args = parser.parse_args([])
    assert args.stage is None and args.size is None


def test_apply_filters_end_to_end():
    _clear_registry()
    parser = argparse.ArgumentParser()
    SF.add_filter_args(parser)
    args = parser.parse_args(["--stage", "seed,series-b", "--size", "1-50,51-200"])
    out = SF.apply_filters(args, _POSTINGS)
    assert [p["company"] for p in out] == ["SeedCo", "GrowthCo"]


def test_apply_filters_noop_when_unset():
    _clear_registry()
    args = argparse.Namespace(stage=None, size=None)
    assert SF.apply_filters(args, _POSTINGS) == _POSTINGS


if __name__ == "__main__":
    sys.exit("run with: python3 -m pytest tests/test_batch21_filters.py -q")

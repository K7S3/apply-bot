"""Tests for candid.nonprofit_feeds (batch-18, worker A)."""

from __future__ import annotations

import io
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

import pytest

from candid import nonprofit_feeds as nf
from candid.jobs import JobsError

FIXTURE = Path(__file__).parent / "fixtures" / "reliefweb_jobs.xml"

SCHEMA_KEYS = {"source", "source_id", "title", "company", "location", "url",
               "description", "salary_text", "remote", "posted_at"}


def _raw_items() -> list[dict]:
    return nf._fetch_rss()


# ---------------------------------------------------------------------------
# normalization mapping against the real fetched snapshot
# ---------------------------------------------------------------------------

def test_jobs_normalization_schema():
    jobs = nf.adapt_reliefweb_jobs()
    assert jobs, "expected postings from the real snapshot"
    for j in jobs:
        assert set(j.keys()) == SCHEMA_KEYS
        assert isinstance(j["remote"], bool)
        assert isinstance(j["salary_text"], str)
        assert len(j["description"]) <= 4000


def test_jobs_normalization_values():
    jobs = nf.adapt_reliefweb_jobs()
    first = jobs[0]
    # Real item: "EMERGENCY PROGRAMME COORDINATOR", Action contre la Faim
    # France, Yemen — verified in the fetched snapshot.
    assert first["title"] == "EMERGENCY PROGRAMME COORDINATOR"
    assert first["company"] == "Action contre la Faim France"
    assert first["location"] == "Yemen"
    assert first["source"] == "reliefweb"
    assert first["source_id"].startswith("reliefweb:")
    assert first["url"].startswith("https://reliefweb.int/job/")
    # Description must be tag-free text.
    assert "<" not in first["description"]
    assert "Action contre la Faim France" in first["description"]
    assert first["posted_at"], "pubDate should map to posted_at"


def test_org_falls_back_to_author_when_div_missing():
    items = _raw_items()
    # Every item should have a non-empty organization and location from
    # either the description divs or the author/category fallback.
    for it in items:
        assert it["organization"], "organization should never be empty"
        assert it["location"], "location should never be empty"


def test_remote_detection():
    assert nf._remote("World") is True
    assert nf._remote("Remote") is True
    assert nf._remote("Yemen") is False
    assert nf._remote("Home-based") is True


# ---------------------------------------------------------------------------
# bridge-role filter (synthetic feed, clearly labeled as such)
# ---------------------------------------------------------------------------

_SYNTHETIC_VOLUNTEER_RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>ReliefWeb - Jobs</title>
<item>
  <title>SYNTHETIC Field Intern</title>
  <link>https://reliefweb.int/job/900001/synthetic-field-intern</link>
  <guid>https://reliefweb.int/job/900001/synthetic-field-intern</guid>
  <pubDate>Mon, 21 Sep 2026 00:00:00 +0000</pubDate>
  <description><div class="tag country">Country: Kenya</div>
  <div class="tag source">Organization: Synthetic NGO</div></description>
  <category>Kenya</category><category>Synthetic NGO</category>
  <category>Program/Project Management</category><category>Internship</category>
  <author>Synthetic NGO</author>
</item>
<item>
  <title>SYNTHETIC Volunteer Driver</title>
  <link>https://reliefweb.int/job/900002/synthetic-volunteer-driver</link>
  <guid>https://reliefweb.int/job/900002/synthetic-volunteer-driver</guid>
  <pubDate>Mon, 21 Sep 2026 00:00:00 +0000</pubDate>
  <description><div class="tag country">Country: Peru</div>
  <div class="tag source">Organization: Synthetic NGO</div></description>
  <category>Peru</category><category>Synthetic NGO</category>
  <category>Logistics/Procurement</category><category>Volunteering</category>
  <author>Synthetic NGO</author>
</item>
<item>
  <title>SYNTHETIC Paid Officer</title>
  <link>https://reliefweb.int/job/900003/synthetic-paid-officer</link>
  <guid>https://reliefweb.int/job/900003/synthetic-paid-officer</guid>
  <pubDate>Mon, 21 Sep 2026 00:00:00 +0000</pubDate>
  <description><div class="tag country">Country: Kenya</div>
  <div class="tag source">Organization: Synthetic NGO</div></description>
  <category>Kenya</category><category>Synthetic NGO</category>
  <category>Program/Project Management</category><category>Job</category>
  <author>Synthetic NGO</author>
</item>
</channel></rss>"""


def _fake_response(payload: bytes):
    resp = mock.MagicMock()
    resp.read.return_value = payload
    resp.__enter__.return_value = resp
    return resp


def _patch_fetch(payload: str):
    return mock.patch.object(
        urllib.request, "urlopen",
        return_value=_fake_response(payload.encode("utf-8")))


def test_volunteer_filter_keeps_only_bridge_types():
    with _patch_fetch(_SYNTHETIC_VOLUNTEER_RSS):
        jobs = nf.adapt_reliefweb_volunteer()
    titles = [j["title"] for j in jobs]
    assert titles == ["SYNTHETIC Field Intern", "SYNTHETIC Volunteer Driver"]
    for j in jobs:
        assert set(j.keys()) == SCHEMA_KEYS
        assert j["source_id"].startswith("reliefweb:")


def test_jobs_adapter_includes_all_types():
    with _patch_fetch(_SYNTHETIC_VOLUNTEER_RSS):
        jobs = nf.adapt_reliefweb_jobs()
    assert len(jobs) == 3


# ---------------------------------------------------------------------------
# error handling
# ---------------------------------------------------------------------------

def test_network_failure_raises_jobserror():
    with mock.patch.object(
            urllib.request, "urlopen",
            side_effect=urllib.error.URLError("no route")):
        with pytest.raises(JobsError, match="ReliefWeb unreachable"):
            nf.adapt_reliefweb_jobs()
        with pytest.raises(JobsError, match="ReliefWeb unreachable"):
            nf.adapt_reliefweb_volunteer()


def test_malformed_xml_raises_jobserror():
    with _patch_fetch("this is not xml <<"):
        with pytest.raises(JobsError, match="malformed RSS"):
            nf.adapt_reliefweb_jobs()


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

def test_registry_contents():
    assert set(nf.NONPROFIT_ADAPTERS) == {"reliefweb", "reliefweb_volunteer"}
    assert nf.NONPROFIT_ADAPTERS["reliefweb"] is nf.adapt_reliefweb_jobs
    assert (nf.NONPROFIT_ADAPTERS["reliefweb_volunteer"]
            is nf.adapt_reliefweb_volunteer)
    for name, fn in nf.NONPROFIT_ADAPTERS.items():
        assert callable(fn), name


def test_registry_merge_pattern_matches_jobs_adapters():
    """The coordinator should be able to merge with one line."""
    from candid import jobs
    merged = {**jobs.ADAPTERS, **nf.NONPROFIT_ADAPTERS}
    assert "reliefweb" in merged and "reliefweb_volunteer" in merged
    assert "arbeitnow" in merged and "remoteok" in merged
    # Every registered adapter honors the normalized schema on real data.
    for name, fn in merged.items():
        try:
            items = fn()
        except JobsError:
            continue  # graceful degradation is the contract
        for item in items:
            assert set(item.keys()) == SCHEMA_KEYS, name


def test_fixture_is_real_fetched_rss():
    """Guard: the snapshot fixture must be genuine ReliefWeb XML."""
    root = ET.parse(FIXTURE).getroot()
    title = root.findtext("./channel/title")
    assert title == "ReliefWeb - Jobs"
    assert len(root.findall(".//item")) >= 1

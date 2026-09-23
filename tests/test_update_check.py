"""Tests for candid.update_check. No real network access."""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.error import URLError

import pytest

from candid import __version__ as CANDID_VERSION

from candid import update_check as uc


@pytest.fixture
def datadir(tmp_path, monkeypatch):
    """Isolated DATA_DIR for settings/cache tests (paths resolve lazily)."""
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    return tmp_path


# --- version parsing / comparison --------------------------------------------


@pytest.mark.parametrize(
    "s, expected",
    [
        ("1.2.3", (1, 2, 3)),
        ("v2.0.1", (2, 0, 1)),
        ("V1.0", (1, 0)),
        ("0.2.0", (0, 2, 0)),
        ("1.2", (1, 2)),
        ("10", (10,)),
        ("  1.2.3  ", (1, 2, 3)),
        ("1.2.3rc1", (1, 2)),  # non-numeric parts ignored
        ("1.2.beta", (1, 2)),
        ("abc", ()),
        ("", ()),
        ("v", ()),
        ("1..2", (1, 2)),
    ],
)
def test_parse_version(s, expected):
    assert uc.parse_version(s) == expected


@pytest.mark.parametrize(
    "latest, current, expected",
    [
        ("0.3.0", "0.2.0", True),
        ("0.2.0", "0.2.0", False),
        ("0.1.9", "0.2.0", False),
        ("1.0.0", "0.9.9", True),
        ("v0.3", "0.2.9", True),  # v-prefix handled
        ("1.2.0", "1.2", False),  # unequal lengths pad to equal
        ("1.2.1", "1.2", True),
        ("1.10.0", "1.9.0", True),  # numeric, not lexicographic
        ("0.2.0", "v0.3.0", False),
    ],
)
def test_is_newer(latest, current, expected):
    assert uc.is_newer(latest, current) is expected


# --- security detection --------------------------------------------------------


@pytest.mark.parametrize(
    "name, body, expected",
    [
        ("v0.3.0 - Security fix", "", True),
        ("v0.3.0", "patches CVE-2024-12345", True),
        ("release", "SECURITY: token handling hardened", True),
        ("v0.3.0", "cve-2026-0001 fixed", True),  # case-insensitive
        ("v0.3.0", "new matcher, dashboard v2", False),
        ("", "", False),
    ],
)
def test_is_security_release(name, body, expected):
    assert uc.is_security_release(name, body) is expected


# --- settings ------------------------------------------------------------------


def test_settings_defaults(datadir):
    assert uc.get_settings() == {"check_enabled": True, "frequency": "daily"}


def test_settings_roundtrip(datadir):
    assert uc.set_settings(enabled=False)["check_enabled"] is False
    assert uc.get_settings()["check_enabled"] is False
    assert uc.set_settings(frequency="weekly")["frequency"] == "weekly"
    assert uc.get_settings() == {"check_enabled": False, "frequency": "weekly"}
    assert uc.set_settings(frequency="never")["frequency"] == "never"


def test_settings_invalid_frequency(datadir):
    with pytest.raises(ValueError):
        uc.set_settings(frequency="monthly")
    with pytest.raises(ValueError):
        uc.set_settings(frequency="")
    # previous value untouched
    assert uc.get_settings()["frequency"] == "daily"


def test_settings_invalid_enabled(datadir):
    with pytest.raises(ValueError):
        uc.set_settings(enabled="yes")
    assert uc.get_settings()["check_enabled"] is True


def test_settings_ignores_corrupt_file(datadir, monkeypatch):
    (datadir / "update_settings.json").write_text("{not json", encoding="utf-8")
    assert uc.get_settings() == {"check_enabled": True, "frequency": "daily"}


def test_settings_recovers_bad_stored_frequency(datadir):
    (datadir / "update_settings.json").write_text(
        json.dumps({"check_enabled": True, "frequency": "hourly"}), encoding="utf-8"
    )
    assert uc.get_settings()["frequency"] == "daily"


# --- cache ---------------------------------------------------------------------


def _info(**over):
    base = dict(
        current_version=CANDID_VERSION,
        latest_version="9.9.9",
        update_available=True,
        security=False,
        release_url="https://github.com/K7S3/candid/releases/tag/v9.9.9",
        notes="new matcher",
        checked_at=datetime.now(timezone.utc).isoformat(),
        error=None,
    )
    base.update(over)
    return uc.UpdateInfo(**base)


def test_cache_roundtrip(datadir):
    info = _info()
    uc.save_cache(info)
    loaded = uc.load_cache()
    assert loaded is not None
    assert loaded["latest_version"] == "9.9.9"
    assert loaded["update_available"] is True
    assert loaded["checked_at"] == info.checked_at


def test_cache_load_missing(datadir):
    assert uc.load_cache() is None


def test_cache_load_corrupt(datadir):
    (datadir / "update_check.json").write_text("oops", encoding="utf-8")
    assert uc.load_cache() is None


def test_cache_fresh(datadir):
    uc.save_cache(_info())
    assert uc.cache_is_fresh() is True


def test_cache_stale(datadir):
    old = datetime.now(timezone.utc) - timedelta(hours=25)
    uc.save_cache(_info(checked_at=old.isoformat()))
    assert uc.cache_is_fresh() is False  # daily ttl is 24h


def test_cache_ttl_override(datadir):
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    uc.save_cache(_info(checked_at=old.isoformat()))
    assert uc.cache_is_fresh(ttl_hours=1.0) is False
    assert uc.cache_is_fresh(ttl_hours=3.0) is True


def test_cache_weekly_ttl(datadir):
    uc.set_settings(frequency="weekly")
    old = datetime.now(timezone.utc) - timedelta(hours=30)
    uc.save_cache(_info(checked_at=old.isoformat()))
    assert uc.cache_is_fresh() is True  # weekly ttl is 168h


def test_cache_never_fresh_for_never_frequency(datadir):
    uc.set_settings(frequency="never")
    uc.save_cache(_info())
    assert uc.cache_is_fresh() is False


def test_cache_bad_timestamp(datadir):
    uc.save_cache(_info(checked_at="not-a-date"))
    assert uc.cache_is_fresh() is False


# --- check_now (monkeypatched network) -------------------------------------------


class _FakeResp:
    def __init__(self, payload: str):
        self._payload = payload.encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_urlopen(monkeypatch, payload: str | Exception):
    def fake(req, timeout=None):
        if isinstance(payload, Exception):
            raise payload
        return _FakeResp(payload)

    monkeypatch.setattr(urllib.request, "urlopen", fake)


_RELEASES_JSON = json.dumps(
    [
        {"tag_name": "v0.4.0", "draft": True, "name": "draft", "body": ""},
        {
            "tag_name": "v9.9.9",
            "draft": False,
            "name": "candid 9.9.9",
            "body": "deeper matching, security fixes for token storage",
            "html_url": "https://github.com/K7S3/candid/releases/tag/v9.9.9",
        },
        {
            "tag_name": "v0.2.0",
            "draft": False,
            "name": "candid 0.2.0",
            "body": "older",
            "html_url": "https://github.com/K7S3/candid/releases/tag/v0.2.0",
        },
    ]
)


def test_check_now_success(monkeypatch):
    _patch_urlopen(monkeypatch, _RELEASES_JSON)
    info = uc.check_now()
    assert isinstance(info, uc.UpdateInfo)
    assert info.current_version == CANDID_VERSION
    assert info.latest_version == "9.9.9"  # skipped the draft
    assert info.update_available is True  # 9.9.9 > current
    assert info.security is True  # body mentions security
    assert info.release_url == "https://github.com/K7S3/candid/releases/tag/v9.9.9"
    assert info.error is None
    assert info.checked_at is not None


def test_check_now_no_update_when_same_version(monkeypatch):
    payload = json.dumps(
        [{"tag_name": f"v{CANDID_VERSION}", "draft": False, "name": "x", "body": "y"}]
    )
    _patch_urlopen(monkeypatch, payload)
    info = uc.check_now()
    assert info.latest_version == CANDID_VERSION
    assert info.update_available is False
    assert info.error is None


def test_check_now_sends_user_agent(monkeypatch):
    seen = {}

    def fake(req, timeout=None):
        seen["ua"] = req.get_header("User-agent")
        return _FakeResp(_RELEASES_JSON)

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    uc.check_now()
    assert seen["ua"] == "candid-update-check"


def test_check_now_network_error_degrades(monkeypatch):
    _patch_urlopen(monkeypatch, URLError("offline"))
    info = uc.check_now()
    assert info.update_available is None
    assert info.latest_version is None
    assert info.error  # error field set, no raise


def test_check_now_bad_json_degrades(monkeypatch):
    _patch_urlopen(monkeypatch, "<html>not json</html>")
    info = uc.check_now()
    assert info.update_available is None
    assert info.error


def test_check_now_no_releases_degrades(monkeypatch):
    _patch_urlopen(monkeypatch, json.dumps([]))
    info = uc.check_now()
    assert info.update_available is None
    assert info.error


def test_check_now_unexpected_shape_degrades(monkeypatch):
    _patch_urlopen(monkeypatch, json.dumps({"oops": 1}))
    info = uc.check_now()
    assert info.update_available is None
    assert info.error


# --- maybe_startup_nudge -----------------------------------------------------------


def test_nudge_disabled_returns_none(datadir):
    uc.set_settings(enabled=False)
    assert uc.maybe_startup_nudge() is None


def test_nudge_never_frequency_returns_none(datadir):
    uc.set_settings(frequency="never")
    assert uc.maybe_startup_nudge() is None


def test_nudge_fresh_cache_with_update(datadir):
    uc.save_cache(_info())
    nudge = uc.maybe_startup_nudge()
    assert isinstance(nudge, str)
    assert "9.9.9" in nudge
    assert "\n" not in nudge  # one line


def test_nudge_mentions_security(datadir):
    uc.save_cache(_info(security=True))
    nudge = uc.maybe_startup_nudge()
    assert "security" in nudge.lower()


def test_nudge_fresh_cache_no_update(datadir):
    uc.save_cache(_info(latest_version=CANDID_VERSION, update_available=False))
    assert uc.maybe_startup_nudge() is None


def test_nudge_stale_cache_attempts_check(datadir, monkeypatch):
    old = datetime.now(timezone.utc) - timedelta(hours=30)
    uc.save_cache(_info(checked_at=old.isoformat()))
    calls = []

    def fake_check_now(timeout=8.0):
        calls.append(timeout)
        return _info()

    monkeypatch.setattr(uc, "check_now", fake_check_now)
    nudge = uc.maybe_startup_nudge()
    assert calls == [2.5]  # short timeout for startup path
    assert nudge is not None and "9.9.9" in nudge
    # cache was refreshed by the check
    assert uc.load_cache()["checked_at"] != old.isoformat()


def test_nudge_stale_cache_failure_caches_and_returns_none(datadir, monkeypatch):
    old = datetime.now(timezone.utc) - timedelta(hours=30)
    uc.save_cache(_info(checked_at=old.isoformat()))

    def fake_check_now(timeout=8.0):
        return _info(
            latest_version=None, update_available=None, error="offline"
        )

    monkeypatch.setattr(uc, "check_now", fake_check_now)
    assert uc.maybe_startup_nudge() is None
    loaded = uc.load_cache()
    assert loaded["update_available"] is None
    assert loaded["error"] == "offline"  # saved even on failure


def test_nudge_swallows_all_exceptions(datadir, monkeypatch):
    def boom():
        raise RuntimeError("settings exploded")

    monkeypatch.setattr(uc, "get_settings", boom)
    assert uc.maybe_startup_nudge() is None


# --- install mode / upgrade steps --------------------------------------------------


def test_detect_install_mode_git():
    # this repo is a git checkout
    assert uc.detect_install_mode() == "git"


def test_detect_install_mode_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr(uc.C, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        uc.metadata, "distribution", lambda name: (_ for _ in ()).throw(
            uc.metadata.PackageNotFoundError()
        )
    )
    assert uc.detect_install_mode() == "unknown"


def test_upgrade_steps_git(monkeypatch, tmp_path):
    monkeypatch.setattr(uc, "detect_install_mode", lambda: "git")
    steps = uc.upgrade_steps()
    assert any("git pull --ff-only origin main" in s for s in steps)


def test_upgrade_steps_pip(monkeypatch):
    monkeypatch.setattr(uc, "detect_install_mode", lambda: "pip")
    steps = uc.upgrade_steps()
    assert any("pip install -U candid" in s for s in steps)


def test_upgrade_steps_unknown(monkeypatch):
    monkeypatch.setattr(uc, "detect_install_mode", lambda: "unknown")
    steps = uc.upgrade_steps()
    assert any("github.com/K7S3/candid" in s for s in steps)


def test_no_em_dashes_in_nudge(datadir):
    uc.save_cache(_info(security=True))
    nudge = uc.maybe_startup_nudge()
    assert "\u2014" not in nudge

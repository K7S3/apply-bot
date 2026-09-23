"""Tests for candid.sync.rules."""

import os

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-sync-e"
os.environ["CANDID_CONFIG_DIR"] = "/tmp/candid-test-sync-e-config"

import json
from pathlib import Path

import pytest

from candid.sync import categories, rules
from candid.sync.errors import SyncError

DATA_DIR = Path("/tmp/candid-test-sync-e")

# Rebind config dirs explicitly: in a shared pytest process another test
# module may import candid first, which would make the env vars above too
# late (config binds them at import time). rules reads config.DATA_DIR
# dynamically, so rebinding keeps these tests hermetic in any run order.
import candid.config

candid.config.DATA_DIR = DATA_DIR
candid.config.CONFIG_DIR = Path("/tmp/candid-test-sync-e-config")


@pytest.fixture(autouse=True)
def clean_state():
    import shutil

    # Hermetic config: rebind for this test, restore afterwards (all sync
    # modules read config.DATA_DIR / CONFIG_DIR dynamically).
    old_data, old_cfg = candid.config.DATA_DIR, candid.config.CONFIG_DIR
    candid.config.DATA_DIR = DATA_DIR
    candid.config.CONFIG_DIR = Path("/tmp/candid-test-sync-e-config")
    shutil.rmtree(DATA_DIR / "sync", ignore_errors=True)
    yield
    shutil.rmtree(DATA_DIR / "sync", ignore_errors=True)
    candid.config.DATA_DIR, candid.config.CONFIG_DIR = old_data, old_cfg


def test_defaults_are_auto():
    got = rules.get_rules()
    assert set(got) == set(categories.all_categories())
    assert all(v == "auto" for v in got.values())


def test_set_and_get_rule():
    merged = rules.set_rule("tracker", "local-wins")
    assert merged["tracker"] == "local-wins"
    assert rules.strategy_for("tracker") == "local-wins"
    assert rules.strategy_for("profile") == "auto"
    on_disk = json.loads(
        (DATA_DIR / "sync" / "rules.json").read_text())
    assert on_disk == {"tracker": "local-wins"}


def test_set_rule_validation():
    with pytest.raises(SyncError, match="unknown sync category"):
        rules.set_rule("not-a-category", "auto")
    with pytest.raises(SyncError, match="unknown strategy"):
        rules.set_rule("tracker", "coin-flip")
    with pytest.raises(SyncError, match="unknown sync category"):
        rules.strategy_for("not-a-category")


def test_clear_rule():
    rules.set_rule("prep", "remote-wins")
    merged = rules.clear_rule("prep")
    assert merged["prep"] == "auto"
    assert rules.strategy_for("prep") == "auto"
    # clearing an unset category is a harmless no-op
    merged = rules.clear_rule("gmail")
    assert merged["gmail"] == "auto"


def test_apply_auto_three_way():
    base = b'{"a": 1}'
    # both unchanged / identical edits
    assert rules.apply_strategy(base, base, base, "auto", 1.0, 1.0) == "local"
    # only remote changed
    assert rules.apply_strategy(base, b'{"a": 2}', base, "auto", 1.0, 2.0) == "remote"
    # only local changed
    assert rules.apply_strategy(b'{"a": 3}', base, base, "auto", 3.0, 1.0) == "local"
    # both changed differently
    assert rules.apply_strategy(b'{"a": 3}', b'{"a": 2}', base, "auto", 3.0, 2.0) \
        == "conflict"
    # works on str too
    assert rules.apply_strategy("x", "y", "z", "auto", 0.0, 0.0) == "conflict"


def test_apply_overrides():
    base = "base"
    assert rules.apply_strategy("l", "r", base, "local-wins", 1.0, 9.0) == "local"
    assert rules.apply_strategy("l", "r", base, "remote-wins", 9.0, 1.0) == "remote"
    assert rules.apply_strategy(base, base, base, "manual", 1.0, 1.0) == "conflict"
    assert rules.apply_strategy("l", "r", base, "manual", 1.0, 2.0) == "conflict"


def test_apply_newer_wins():
    base = "base"
    assert rules.apply_strategy("l", "r", base, "newer-wins", 5.0, 3.0) == "local"
    assert rules.apply_strategy("l", "r", base, "newer-wins", 3.0, 5.0) == "remote"
    # documented tie-break: exact tie keeps local
    assert rules.apply_strategy("l", "r", base, "newer-wins", 4.0, 4.0) == "local"
    # missing mtimes: unknown (None) loses to a known timestamp
    assert rules.apply_strategy("l", "r", base, "newer-wins", None, 4.0) == "remote"
    assert rules.apply_strategy("l", "r", base, "newer-wins", 4.0, None) == "local"
    # both unknown: tie, local wins
    assert rules.apply_strategy("l", "r", base, "newer-wins", None, None) == "local"


def test_apply_strategy_rejects_unknown():
    with pytest.raises(SyncError, match="unknown strategy"):
        rules.apply_strategy("l", "r", "b", "best-of-three", 1.0, 2.0)

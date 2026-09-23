"""Tests for candid.sync.pairing."""

import os

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-sync-e"
os.environ["CANDID_CONFIG_DIR"] = "/tmp/candid-test-sync-e-config"

import hashlib
import json
from pathlib import Path

import pytest

from candid.sync import pairing
from candid.sync.errors import SyncError
from candid.sync.machine import get_machine_id

DATA_DIR = Path("/tmp/candid-test-sync-e")

# Rebind config dirs explicitly: in a shared pytest process another test
# module may import candid first, which would make the env vars above too
# late (config binds them at import time). pairing/rules/machine all read
# config.DATA_DIR and config.CONFIG_DIR dynamically, so rebinding the
# module attributes keeps these tests hermetic in any run order.
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


def make_pairing_file(tmp_path, name="other-machine", machine_id="m-peer"):
    """Write a well-formed pairing doc for a fake peer machine."""
    doc = {
        "format": "candid-pairing/1",
        "machine_id": machine_id,
        "name": name,
        "token": "secret-token-value-12345",
        "created_at": "2026-09-22T20:00:00",
    }
    p = tmp_path / "pair.json"
    p.write_text(json.dumps(doc))
    return p


def test_round_trip_registers_peer(tmp_path):
    out = tmp_path / "carry" / "pair.json"
    ret = pairing.init_pairing("my laptop", out)
    assert ret == out
    doc = json.loads(out.read_text())
    assert doc["format"] == "candid-pairing/1"
    assert doc["machine_id"] == get_machine_id()
    assert doc["name"] == "my laptop"
    assert doc["token"]  # token present in the carried file

    # simulate the other machine accepting: rewrite the doc with a peer id
    doc["machine_id"] = "m-peer-1"
    out.write_text(json.dumps(doc))
    peer_id = pairing.accept_pairing(out)
    assert peer_id == "m-peer-1"
    peers = pairing.list_peers()
    assert "m-peer-1" in peers
    assert peers["m-peer-1"]["name"] == "my laptop"
    assert peers["m-peer-1"]["paired_at"]


def test_self_pairing_refused(tmp_path):
    out = tmp_path / "self.json"
    pairing.init_pairing("me", out)
    with pytest.raises(SyncError, match="cannot pair with yourself"):
        pairing.accept_pairing(out)


def test_token_never_stored_plaintext(tmp_path):
    token = "super-secret-plaintext-token"
    doc = {
        "format": "candid-pairing/1",
        "machine_id": "m-peer-2",
        "name": "phone",
        "token": token,
        "created_at": "2026-09-22T20:00:00",
    }
    p = tmp_path / "pair.json"
    p.write_text(json.dumps(doc))
    pairing.accept_pairing(p)
    registry = (DATA_DIR / "sync" / "peers.json").read_text()
    assert token not in registry
    stored = pairing.list_peers()["m-peer-2"]
    assert stored["token_sha256"] == hashlib.sha256(token.encode()).hexdigest()
    assert len(stored["token_sha256"]) == 64


def test_reaccept_updates_name(tmp_path):
    p = make_pairing_file(tmp_path, name="old-name", machine_id="m-peer-3")
    pairing.accept_pairing(p)
    p2 = make_pairing_file(tmp_path, name="new-name", machine_id="m-peer-3")
    pairing.accept_pairing(p2)
    assert pairing.list_peers()["m-peer-3"]["name"] == "new-name"
    assert len(pairing.list_peers()) == 1


def test_bad_pairing_files_rejected(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json at all")
    with pytest.raises(SyncError):
        pairing.accept_pairing(p)
    p.write_text(json.dumps({"format": "candid-pairing/1"}))
    with pytest.raises(SyncError, match="machine_id"):
        pairing.accept_pairing(p)
    p.write_text(json.dumps({"format": "wrong-format/9", "machine_id": "x",
                             "name": "n", "token": "t"}))
    with pytest.raises(SyncError, match="unsupported pairing format"):
        pairing.accept_pairing(p)


def test_remove_peer(tmp_path):
    pairing.accept_pairing(make_pairing_file(tmp_path, machine_id="m-peer-4"))
    assert pairing.remove_peer("m-peer-4") is True
    assert pairing.list_peers() == {}
    with pytest.raises(SyncError, match="unknown peer"):
        pairing.remove_peer("m-peer-4")


def test_unknown_peer_bundle_refused_when_peers_exist(tmp_path):
    pairing.accept_pairing(make_pairing_file(tmp_path, machine_id="m-peer-5"))
    manifest = {"machine_id": "m-stranger", "peer_id": None}
    with pytest.raises(SyncError, match="unpaired machine"):
        pairing.check_incoming_manifest(manifest)


def test_zero_peers_trust_on_first_use():
    assert pairing.list_peers() == {}
    manifest = {"machine_id": "m-anyone", "peer_id": None}
    pairing.check_incoming_manifest(manifest)  # no error


def test_known_peer_bundle_allowed(tmp_path):
    pairing.accept_pairing(make_pairing_file(tmp_path, machine_id="m-peer-6"))
    pairing.check_incoming_manifest(
        {"machine_id": "m-peer-6", "peer_id": None})  # no error


def test_bundle_addressed_to_another_machine(tmp_path):
    pairing.check_incoming_manifest(
        {"machine_id": "m-peer-6", "peer_id": get_machine_id()})  # no error
    with pytest.raises(SyncError, match="addressed to another machine"):
        pairing.check_incoming_manifest(
            {"machine_id": "m-peer-6", "peer_id": "m-someone-else"})

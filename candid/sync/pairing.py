"""Peer pairing bootstrap for file-based sync.

Pairing is a one-time handshake so two machines recognise each other:

1. On machine A: ``init_pairing("laptop", Path("/tmp/pair.json"))`` writes a
   pairing file carrying A's machine id and a random token.
2. The user carries that file to machine B (USB drive, AirDrop, whatever
   channel they trust) and B runs ``accept_pairing(Path("/tmp/pair.json"))``.
3. Repeat in the other direction if B's bundles also need to be trusted by A.
   Pairing is per-machine, not symmetric: each side keeps its own peers.json.

Security notes (read these):

- The pairing file contains the token in *plaintext*. Move it over a channel
  you trust and delete it from both ends after accepting.
- ``peers.json`` stores only the sha256 of the token, never the token itself.
- Bundles are integrity-checked (sha256) but NOT encrypted, by design:
  candid is stdlib-only, so encryption would be homegrown and weak. Move
  bundles over a channel you trust.

Enforcement: once at least one peer is registered, bundles from unregistered
machines are refused (trust-on-first-use). With zero peers registered, any
bundle is accepted, so the very first sync works without ceremony.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime
from pathlib import Path

from candid import config
from candid.sync import categories, machine
from candid.sync.errors import SyncError

PAIRING_FORMAT = "candid-pairing/1"

_PEERS_FILENAME = "peers.json"


def _sync_state_dir() -> Path:
    d = Path(config.DATA_DIR) / categories.SYNC_STATE_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _peers_path() -> Path:
    return _sync_state_dir() / _PEERS_FILENAME


def _load_peers() -> dict:
    path = _peers_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise SyncError(f"peer registry {path} is corrupt: {exc}") from exc
    if not isinstance(data, dict):
        raise SyncError(f"peer registry {path} is corrupt")
    return data


def _save_peers(peers: dict) -> None:
    _peers_path().write_text(
        json.dumps(peers, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def init_pairing(name: str, out_path: str | Path) -> Path:
    """Create a pairing file this machine's owner carries to a peer machine.

    Writes ``{"format": "candid-pairing/1", "machine_id", "name", "token",
    "created_at"}`` to ``out_path`` and returns the path. The token is a
    one-time shared secret: the accepting machine stores only its sha256.
    """
    out = Path(out_path)
    pairing = {
        "format": PAIRING_FORMAT,
        "machine_id": machine.get_machine_id(),
        "name": name,
        "token": secrets.token_urlsafe(24),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pairing, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    return out


def accept_pairing(pair_file: str | Path) -> str:
    """Accept a pairing file produced by ``init_pairing`` on another machine.

    Validates the format and required fields, refuses to pair with ourselves,
    and registers the peer in ``DATA_DIR/sync/peers.json`` storing only the
    sha256 of the token. Re-accepting the same peer updates its name (and the
    stored token hash). Returns the peer's machine id.
    """
    pair_file = Path(pair_file)
    try:
        pairing = json.loads(pair_file.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise SyncError(f"cannot read pairing file {pair_file}: {exc}") from exc
    if not isinstance(pairing, dict):
        raise SyncError(f"pairing file {pair_file} is not a pairing document")
    if pairing.get("format") != PAIRING_FORMAT:
        raise SyncError(
            f"unsupported pairing format {pairing.get('format')!r}; "
            f"this candid understands {PAIRING_FORMAT!r}"
        )
    for field in ("machine_id", "name", "token"):
        if not pairing.get(field):
            raise SyncError(
                f"pairing file {pair_file} is missing required field {field!r}"
            )
    peer_id = pairing["machine_id"]
    if peer_id == machine.get_machine_id():
        raise SyncError("cannot pair with yourself")
    peers = _load_peers()
    peers[peer_id] = {
        "name": pairing["name"],
        "paired_at": datetime.now().isoformat(timespec="seconds"),
        "token_sha256": hashlib.sha256(
            pairing["token"].encode("utf-8")
        ).hexdigest(),
    }
    _save_peers(peers)
    return peer_id


def list_peers() -> dict:
    """Return the peer registry: ``{peer_machine_id: {name, paired_at,
    token_sha256}}``. Never contains plaintext tokens."""
    return _load_peers()


def remove_peer(peer_id: str) -> bool:
    """Remove a peer from the registry. Raises SyncError if unknown."""
    peers = _load_peers()
    if peer_id not in peers:
        raise SyncError(f"unknown peer {peer_id!r}; nothing to remove")
    del peers[peer_id]
    _save_peers(peers)
    return True


def check_incoming_manifest(manifest: dict) -> None:
    """Gate an incoming bundle manifest on the pairing registry.

    - If the manifest is addressed to a specific machine (``peer_id`` set) and
      that machine is not us, the bundle is refused.
    - If we have registered peers and the bundle's source machine is not
      among them, the bundle is refused. With zero registered peers, anything
      goes (trust-on-first-use, so the first sync needs no ceremony).

    Raises SyncError on violation; returns None when the bundle may proceed.
    """
    ours = machine.get_machine_id()
    addressed_to = manifest.get("peer_id")
    if addressed_to and addressed_to != ours:
        raise SyncError(
            "bundle is addressed to another machine "
            f"(addressed to {addressed_to!r}, we are {ours!r})"
        )
    peers = _load_peers()
    source = manifest.get("machine_id")
    if peers and source not in peers:
        raise SyncError(
            f"bundle is from an unpaired machine {source!r}; "
            "pair first or remove pairing enforcement"
        )

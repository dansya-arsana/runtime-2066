"""Trust-store pinning: which grant ISSUERS the runtime accepts.

The hole this closes: an ed25519 signature proves a file wasn't edited —
it does not prove the signer is anyone you trust. An attacker can
generate a keypair, sign a self-serving grant, and pass naive "is it
signed" checks. The trust store is the fix: the human pins the public
keys of accepted issuers in a JSON file, and (with `--require-signed`)
the runtime refuses any delegation whose issuer key is not pinned there.

Trust-store file (JSON):
{
  "version": 1,
  "issuers": [
    {"agent_id": "human-ronel", "public_key": "<64 hex>"}
  ]
}

Fail-closed: a missing/malformed store is an error when required; an
issuer not in the store refuses the whole grant file. The store itself
should live on the same key disk as the issuer (or be distributed with
deployments) — a store the attacker can edit is equivalent to no store.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import identity


class TrustStore:
    def __init__(self, entries: list[dict] | None = None):
        self.issuers: dict[str, str] = {}  # public_key hex -> agent_id
        for entry in entries or []:
            self.add(entry.get("agent_id", ""),
                     entry.get("public_key", ""))

    @classmethod
    def from_file(cls, path: str) -> "TrustStore":
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict) or \
                "issuers" not in payload:
            raise ValueError(f"trust store {path!r} must be a JSON object "
                             f"with an 'issuers' list")
        store = cls()
        for entry in payload["issuers"]:
            if not isinstance(entry, dict):
                raise ValueError(f"trust store entry must be objects")
            public_key = entry.get("public_key", "")
            agent_id = entry.get("agent_id", "")
            try:
                identity._check_hex(public_key, 32, "public_key")
            except ValueError as exc:
                raise ValueError(f"trust store: {exc}") from exc
            store.issuers[public_key] = agent_id
        return store

    def add(self, agent_id: str, public_key: str) -> None:
        identity._check_hex(public_key, 32, "public_key")
        self.issuers[public_key] = agent_id

    def pins(self, public_key: str) -> bool:
        return public_key in self.issuers

    def agent_for(self, public_key: str) -> str | None:
        return self.issuers.get(public_key)


def check_issuer_pinned(envelope: dict, store: "TrustStore | None",
                        require_signed: bool) -> None:
    """Fail closed when the issuer of a signed envelope is not pinned.

    Called only for signed envelopes; unsigned files are governed by
    require_signed. E405 = issuer not in the trust store.

    Multisig envelopes (a `signatures` list) are checked per signer:
    EVERY signature must come from a pinned key — one unpinned signer
    refuses the whole file, so an attacker's key cannot lend quorum
    weight to a partially trusted file.
    """
    if isinstance(envelope.get("signatures"), list):
        if store is None:
            raise ValueError(
                "multisig capability file cannot be checked: no trust "
                "store is configured — pin accepted issuers in a "
                "trust-store file and pass it with --trust-store")
        for index, entry in enumerate(envelope["signatures"]):
            agent_id = entry.get("agent_id", "?") \
                if isinstance(entry, dict) else "?"
            public_key = entry.get("public_key", "") \
                if isinstance(entry, dict) else ""
            if not store.pins(public_key):
                raise ValueError(
                    f"multisig signer {index + 1} ({agent_id!r}, "
                    f"public_key {public_key[:12]}…) is NOT in the trust "
                    f"store — refusing the capability file "
                    f"(pin every signer to accept)")
        return
    if "signature" not in envelope:
        return  # unsigned acceptance is governed by require_signed
    issuer = envelope.get("issued_by") or {}
    public_key = issuer.get("public_key", "")
    if store is None:
        raise ValueError(
            "signed capability file cannot be checked: no trust store "
            "is configured — pin accepted issuers in a trust-store file "
            "and pass it with --trust-store")
    if not store.pins(public_key):
        raise ValueError(
            f"issuer {issuer.get('agent_id', '?')!r} "
            f"(public_key {public_key[:12]}…) is NOT in the trust store — "
            f"refusing the capability file (pin the issuer to accept)")

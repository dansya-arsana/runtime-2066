"""Key-copying defenses (spec/key-copying.md):
- hash-bound approvals: a delegation binds to ONE program hash
- revocation list: kill stolen delegations early; hash-chained
- split-trust keys: signing key = f(disk seed, host pinned secret) —
  a copied disk alone derives a useless key
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .errors import StructuredError

_GENESIS = "0" * 64


def _chain_hash(record: dict) -> str:
    payload = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()


def derive_two_factor_seed(disk_seed_hex: str, host_pinned_secret: str) -> str:
    """Split-trust derivation: signing seed = H(disk factor ‖ host factor).

    A copied disk without the pinned host secret — and a compromised host
    without the disk — each derive a useless key.
    """
    key = hashlib.sha256(host_pinned_secret.encode("utf-8")).digest()
    material = bytes.fromhex(disk_seed_hex)
    return hashlib.sha256(b"2066-split-trust" + key + material).hexdigest()


class Revocations:
    """Append-only, hash-chained revocation list."""

    def __init__(self, path: str):
        self.path = Path(path)

    def revoke(self, grant_or_token_id: str, reason: str = "") -> dict:
        seq, prev = self._tail()
        record = {
            "seq": seq + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            "revoke": grant_or_token_id,
            "reason": reason,
            "prev_hash": prev,
        }
        record["hash"] = _chain_hash(record)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    def is_revoked(self, grant_or_token_id: str) -> bool:
        if not self.path.exists():
            return False
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line).get("revoke") \
                    == grant_or_token_id:
                return True
        return False

    def verify_chain(self) -> dict:
        if not self.path.exists():
            return {"ok": True, "records": 0}
        prev = _GENESIS
        records = 0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            records += 1
            if record.get("prev_hash") != prev:
                return {"ok": False, "records": records,
                        "reason": "chain link mismatch"}
            if _chain_hash(record) != record.get("hash"):
                return {"ok": False, "records": records,
                        "reason": "record hash mismatch"}
            prev = record["hash"]
        return {"ok": True, "records": records}

    def _tail(self) -> tuple[int, str]:
        if not self.path.exists():
            return 0, _GENESIS
        lines = [line for line
                 in self.path.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
        if not lines:
            return 0, _GENESIS
        last = json.loads(lines[-1])
        return int(last["seq"]), last["hash"]


def grant_id(envelope: dict) -> str:
    """Stable identifier of a delegation: hash of its canonical payload."""
    payload = envelope.get("payload", envelope)
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()


def bind_to_hash(payload: dict, program_hash: str) -> dict:
    """Bind a grants payload to exactly one canonical program hash.
    Returns a new payload; the signature (applied afterwards) covers it."""
    bound = dict(payload)
    bound["bound_program_hash"] = program_hash
    return bound


def check_hash_binding(envelope: dict, actual_program_hash: str) -> None:
    """E408 if the delegation is bound to a different program hash —
    a hash-bound approval cannot be reused on other artifacts."""
    bound = envelope.get("payload", {}).get("bound_program_hash")
    if bound and bound != actual_program_hash:
        raise StructuredError(
            code="E408",
            detail=f"denied: delegation is bound to program {bound} but "
                   f"the running program is {actual_program_hash} — "
                   f"a hash-bound approval cannot be reused")

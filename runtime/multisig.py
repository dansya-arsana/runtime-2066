"""Multisig approvals (Phase 11 prep): m-of-n key disks.

An envelope signed by m distinct pinned keys with m >= threshold
accepts; anything less is refused. Each signature covers the same
canonical payload, so the human key disks from spec/hardware-key.md
sign the same file in turn (pass-around signing), and the runtime
counts distinct, trusted, verifying signatures.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from . import identity
from .errors import StructuredError


def sign_multisig(payload: dict, signers: list[tuple[identity.Identity, str]],
                  issued_at: str) -> dict:
    """Collect m signatures over one payload.

    signers: [(identity, secret_hex), ...] — order preserved for
    determinism; duplicate keys are ignored.
    """
    signatures: list[dict] = []
    seen: set[str] = set()
    for ident, secret_hex in signers:
        if ident.public_key in seen:
            continue
        seen.add(ident.public_key)
        sig = identity.sign(secret_hex,
                            identity.canonical_json({"payload": payload,
                                                     "issued_at": issued_at}))
        signatures.append({"agent_id": ident.agent_id,
                           "algorithm": ident.algorithm,
                           "public_key": ident.public_key,
                           "signature": sig})
    return {"issued_at": issued_at, "payload": payload,
            "signatures": signatures}


def stamp_multisig(payload: dict, threshold: int, total: int) -> dict:
    """Record m-of-n metadata INSIDE the payload (mutates and returns it).

    The threshold must be part of the signed bytes — a top-level,
    unsigned `threshold` field could be lowered after the fact, letting
    one signer pass off an incomplete quorum as complete. Because
    sign_multisig signs the whole payload, embedding it here makes any
    later edit break every signature.
    """
    if not isinstance(payload, dict):
        raise ValueError("multisig payload must be a JSON object")
    payload["multisig"] = {"threshold": int(threshold), "total": int(total)}
    return payload


def recorded_threshold(payload) -> int | None:
    """The threshold stamped into a payload, or None when absent/invalid."""
    spec = payload.get("multisig") if isinstance(payload, dict) else None
    if isinstance(spec, dict):
        threshold = spec.get("threshold")
        if isinstance(threshold, int) and not isinstance(threshold, bool) \
                and threshold >= 1:
            return threshold
    return None


def verify_multisig(envelope: dict, threshold: int,
                    trust_keys: set[str] | None = None) -> dict:
    """Verify at least `threshold` signatures from distinct trusted keys.

    trust_keys: pinned public keys (hex). None = accept any verifying key.
    Returns {"ok": True, "signers": [agent_id, ...]} or raises E602/E604.
    """
    signatures = envelope.get("signatures")
    if not isinstance(signatures, list):
        raise StructuredError(
            code="E604", detail="multisig envelope missing 'signatures' list")
    payload = envelope.get("payload")
    issued_at = envelope.get("issued_at")
    body = identity.canonical_json({"payload": payload,
                                    "issued_at": issued_at})
    accepted: list[str] = []
    for sig_entry in signatures:
        if not isinstance(sig_entry, dict):
            continue
        public_key = sig_entry.get("public_key", "")
        if trust_keys is not None and public_key not in trust_keys:
            continue
        if identity.verify(public_key, sig_entry.get("signature", ""), body):
            accepted.append(sig_entry.get("agent_id",
                                          public_key[:12] + "…"))
    if len(accepted) < threshold:
        raise StructuredError(
            code="E602",
            detail=f"multisig threshold not met: {len(accepted)} valid "
                   f"signature(s), threshold {threshold}")
    return {"ok": True, "signers": accepted}

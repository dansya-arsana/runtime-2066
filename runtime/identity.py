"""Agent cryptographic identity (roadmap §26, crypto agility §64).

Identity ABI: everything is algorithm-tagged so implementations can rotate
(§64); ed25519 is the V1 implementation, provided by the `cryptography`
package — the project's first third-party dependency, adopted per the
reuse-first principle (hand-rolled crypto is the one thing worse than a
dependency) and recorded in DEPENDENCIES.md with a replacement plan.

Signing convention: signatures cover `canonical_json(obj)` — UTF-8 JSON
with sorted keys and compact separators — so identical data always produces
identical signatures (ed25519 is deterministic) and any byte flipped
anywhere in the signed object breaks verification.

File formats (spec/identity.md):
  identity file  {"agent_id", "algorithm", "public_key", "created"}
  secret file    {"agent_id", "algorithm", "secret_key"}   (NEVER commit)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

ALGORITHM = "ed25519"
SUPPORTED_ALGORITHMS = (ALGORITHM,)

_SECRET_KEY_HEX_LEN = 32   # ed25519 raw seed = 32 bytes (64 hex chars)
_PUBLIC_KEY_HEX_LEN = 32   # ed25519 raw public = 32 bytes (64 hex chars)


@dataclass(frozen=True)
class Identity:
    agent_id: str
    algorithm: str
    public_key: str  # hex
    created: str | None = None


def canonical_json(obj) -> bytes:
    """The canonical byte form signatures cover (deterministic)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def generate_identity(agent_id: str) -> tuple[Identity, str]:
    """Fresh keypair: (public identity, secret key hex)."""
    if not agent_id:
        raise ValueError("agent_id must be a non-empty string")
    private = Ed25519PrivateKey.generate()
    public_hex = private.public_key().public_bytes_raw().hex()
    secret_hex = private.private_bytes_raw().hex()
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return Identity(agent_id=agent_id, algorithm=ALGORITHM,
                    public_key=public_hex, created=created), secret_hex


def parse_identity(payload) -> Identity:
    if not isinstance(payload, dict):
        raise ValueError("identity file must be a JSON object")
    try:
        agent_id = payload["agent_id"]
        algorithm = payload["algorithm"]
        public_key = payload["public_key"]
    except KeyError as exc:
        raise ValueError(f"identity file missing field {exc}") from exc
    _check_algorithm(algorithm)
    _check_hex(public_key, _PUBLIC_KEY_HEX_LEN, "public_key")
    return Identity(agent_id=str(agent_id), algorithm=algorithm,
                    public_key=public_key,
                    created=payload.get("created"))


def load_secret_key(payload) -> tuple[str, str]:
    """Secret file -> (agent_id, secret hex)."""
    if not isinstance(payload, dict):
        raise ValueError("secret key file must be a JSON object")
    try:
        agent_id = payload["agent_id"]
        algorithm = payload["algorithm"]
        secret_key = payload["secret_key"]
    except KeyError as exc:
        raise ValueError(f"secret key file missing field {exc}") from exc
    _check_algorithm(algorithm)
    _check_hex(secret_key, _SECRET_KEY_HEX_LEN, "secret_key")
    return str(agent_id), secret_key


def sign(secret_hex: str, data: bytes) -> str:
    private = Ed25519PrivateKey.from_private_bytes(
        _check_hex(secret_hex, _SECRET_KEY_HEX_LEN, "secret_key"))
    return private.sign(data).hex()


def verify(public_hex: str, signature_hex: str, data: bytes) -> bool:
    try:
        public = Ed25519PublicKey.from_public_bytes(
            _check_hex(public_hex, _PUBLIC_KEY_HEX_LEN, "public_key"))
        public.verify(bytes.fromhex(signature_hex), data)
        return True
    except (InvalidSignature, ValueError):
        return False


def _check_algorithm(algorithm) -> None:
    if algorithm not in SUPPORTED_ALGORITHMS:
        raise ValueError(f"unsupported identity algorithm {algorithm!r} "
                         f"(supported: {', '.join(SUPPORTED_ALGORITHMS)})")


def _check_hex(value, expected_bytes: int, name: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a hex string")
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"{name} is not valid hex: {exc}") from exc
    if len(raw) != expected_bytes:
        raise ValueError(f"{name} must be {expected_bytes * 2} hex chars "
                         f"({expected_bytes} bytes), got {len(raw)} bytes")
    return raw

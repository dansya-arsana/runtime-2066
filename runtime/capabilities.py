"""Capability objects and grant enforcement (roadmap §17–§19, Appendix C.3).

The runtime — never the program — holds and checks authority (§17):
grants are loaded once at process start from a JSON file the human/policy
layer provides, and the instruction set contains no operation that can
create, read, widen, or revoke a capability (Constitution: agents cannot
mint their own authority).

Default deny: executing an effectful operation with no capability system
attached is denied (§20 forbidden defaults). Expiry checks run against the
wall clock — the authority plane is intentionally time-based; `--now`
freezes the clock for deterministic tests.

Scope semantics are component-wise prefix match on normalized absolute
paths: a grant on `/incoming` covers `/incoming/a.txt` but neither
`/incoming.txt` nor `/etc`. Comparison is case-sensitive and separator- and
normalization-independent by construction.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from . import identity
from .multisig import recorded_threshold, verify_multisig
from .pinning import TrustStore, check_issuer_pinned
from .revocation import check_hash_binding, grant_id, Revocations
from .errors import StructuredError

ACTIONS = ("filesystem.read", "filesystem.write",
           "data.read", "data.write", "data.delete",
           "net.request")


def normalize_path(path: str) -> str:
    """Deterministic absolute form: forward slashes, no `.`/`..`, no fs access."""
    absolute = os.path.abspath(path)
    return os.path.normpath(absolute).replace("\\", "/")


def parse_timestamp(raw: str) -> datetime:
    """ISO 8601; naive timestamps are interpreted as UTC."""
    text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class Capability:
    action: str
    resource: str  # normalized absolute scope
    id: str = ""
    expires: datetime | None = None
    max_bytes: int | None = None


@dataclass(frozen=True)
class GrantSet:
    subject: str
    capabilities: tuple[Capability, ...]

    @classmethod
    def empty(cls) -> "GrantSet":
        return cls(subject="anonymous", capabilities=())

    @classmethod
    def from_file(cls, path: str, require_signed: bool = False,
                  revocations=None, program_hash: str | None = None,
                  trust_store: "TrustStore | None" = None
                  ) -> "GrantSet":
        """Load and verify a capability file (spec/identity.md,
        spec/key-copying.md).

        Signed envelopes are always verified — any verification failure
        refuses the whole file (fail closed). Unsigned files are accepted
        unless `require_signed` is set (transition default; the threat
        model recommends signed grants everywhere). With `revocations`
        attached, revoked capability sets or individual grants are
        refused; with `program_hash` given, hash-bound delegations
        (`approve --for-hash`) verify against the running program (E408
        on mismatch).
        """
        import hashlib as _hashlib

        with open(path, "r", encoding="utf-8") as handle:
            envelope = json.load(handle)
        payload = verify_envelope(envelope, require_signed=require_signed)
        if trust_store is not None:
            check_issuer_pinned(envelope, trust_store, require_signed)
        if revocations is not None:
            if revocations.is_revoked(grant_id(envelope)):
                raise ValueError(
                    "capability set is REVOKED — a revocation record "
                    "names this delegation")
            for entry in payload.get("grants", []):
                gid = _hashlib.sha256(json.dumps(
                    entry, sort_keys=True, separators=(",", ":"),
                    ensure_ascii=False).encode("utf-8")).hexdigest()
                if revocations.is_revoked(gid):
                    raise ValueError(
                        f"capability REVOKED: grant for "
                        f"{entry.get('action')}@{entry.get('resource')} "
                        f"appears in the revocation list")
        if program_hash:
            check_hash_binding(envelope, program_hash)
        return cls.from_dict(payload)

    @classmethod
    def from_dict(cls, payload) -> "GrantSet":
        if not isinstance(payload, dict):
            raise ValueError("capability file must be a JSON object")
        grants: list[Capability] = []
        for index, entry in enumerate(payload.get("grants", [])):
            grants.append(_parse_grant(entry, index))
        return cls(subject=str(payload.get("subject", "anonymous")),
                   capabilities=tuple(grants))

    def check(self, action: str, path: str, now: datetime | None = None,
              nbytes: int | None = None, node: str | None = None) -> Capability:
        """Authorize one effect on one resource; raise E401/E402/E403.

        `path` must already be normalized. Deterministic: candidates are
        evaluated in grant-declaration order and the first survivor wins.
        """
        if action == "net.request":
            candidates = [
                cap for cap in self.capabilities
                if cap.action == action and _host_covers(cap.resource, path)
            ]
        else:
            candidates = [
                cap for cap in self.capabilities
                if cap.action == action and _scope_covers(cap.resource, path)
            ]
        if not candidates:
            raise StructuredError(
                code="E401", node=node, operation=action,
                detail=f"denied: no capability grants {action} on {path}",
            )
        moment = now if now is not None else datetime.now(timezone.utc)
        unexpired = [cap for cap in candidates
                     if cap.expires is None or moment <= cap.expires]
        if not unexpired:
            earliest = min(cap.expires for cap in candidates)
            raise StructuredError(
                code="E402", node=node, operation=action,
                detail=f"denied: capability for {path} expired at "
                       f"{earliest.isoformat()}",
            )
        if nbytes is not None:
            within_limit = [cap for cap in unexpired
                            if cap.max_bytes is None or nbytes <= cap.max_bytes]
            if not within_limit:
                tightest = min(cap.max_bytes for cap in unexpired
                               if cap.max_bytes is not None)
                raise StructuredError(
                    code="E403", node=node, operation=action,
                    detail=f"denied: {nbytes} bytes exceeds capability limit "
                           f"({tightest} bytes) for {path}",
                )
        return unexpired[0]


def sign_capabilities(payload: dict, issuer: identity.Identity,
                      secret_hex: str, issued_at: str) -> dict:
    """Wrap a grants payload in a signed envelope (spec/identity.md)."""
    core = {
        "issued_by": {
            "agent_id": issuer.agent_id,
            "algorithm": issuer.algorithm,
            "public_key": issuer.public_key,
        },
        "issued_at": issued_at,
        "payload": payload,
    }
    signature = identity.sign(secret_hex, identity.canonical_json(core))
    return {**core, "signature": signature}


def verify_envelope(envelope, require_signed: bool = False) -> dict:
    """Verify a capability file's envelope; return the grants payload.

    Two envelope shapes are accepted:
    - single-signature: `issued_by` + `signature` (sign_capabilities)
    - multisig: a `signatures` list (multisig.sign_multisig); the m-of-n
      threshold is read from the SIGNED payload (multisig.stamp_multisig)

    Fail closed: missing issuer fields, unsupported algorithms, and bad
    signatures all raise ValueError — the caller must refuse the file.
    """
    if not isinstance(envelope, dict):
        raise ValueError("capability file must be a JSON object")
    if isinstance(envelope.get("signatures"), list):
        return _verify_multisig_envelope(envelope)
    if "signature" not in envelope:
        if require_signed:
            raise ValueError("capability file is not signed; "
                             "signed grants are required")
        return envelope
    issuer = envelope.get("issued_by")
    if not isinstance(issuer, dict):
        raise ValueError("signed capability file missing 'issued_by'")
    if issuer.get("algorithm") not in identity.SUPPORTED_ALGORITHMS:
        raise ValueError("signed capability file: unsupported algorithm "
                         f"{issuer.get('algorithm')!r}")
    core = {
        "issued_by": issuer,
        "issued_at": envelope.get("issued_at"),
        "payload": envelope.get("payload"),
    }
    if not identity.verify(issuer.get("public_key", ""), envelope["signature"],
                           identity.canonical_json(core)):
        raise ValueError("capability signature verification FAILED — "
                         "the file was modified or is not from the claimed "
                         "issuer; refusing all grants")
    return envelope["payload"]


def _verify_multisig_envelope(envelope) -> dict:
    """m-of-n envelope: at least `threshold` signatures must verify.

    The threshold comes from the signed payload (stamped by
    multisig.stamp_multisig at approval time), so it cannot be lowered
    after the fact without breaking every signature.
    """
    payload = envelope.get("payload")
    threshold = recorded_threshold(payload)
    if threshold is None:
        raise ValueError("multisig capability file has no valid signed "
                         "'payload.multisig.threshold' (integer >= 1) — "
                         "refusing the file")
    try:
        verify_multisig(envelope, threshold)
    except StructuredError as exc:
        raise ValueError(f"capability multisig verification FAILED — "
                         f"{exc.detail}; refusing all grants") from exc
    return payload


def _parse_grant(entry, index: int) -> Capability:
    if not isinstance(entry, dict):
        raise ValueError(f"grant {index} must be a JSON object")
    try:
        action = entry["action"]
        resource = entry["resource"]
    except KeyError as exc:
        raise ValueError(f"grant {index} missing field {exc}") from exc
    if action not in ACTIONS:
        raise ValueError(f"grant {index}: unknown action {action!r} "
                         f"(allowed: {', '.join(ACTIONS)})")
    if not isinstance(resource, str) or not resource.strip():
        raise ValueError(f"grant {index}: empty resource is ambiguous "
                         f"and refused — name an explicit scope")
    # filesystem scopes are paths; data resources are bare entity names;
    # net.request scopes are hostnames (egress allowlist)
    if action.startswith("filesystem."):
        resource = normalize_path(resource)
    elif action == "net.request":
        resource = resource.strip().lower()
        labels = resource.split(".")
        if (len(labels) < 2
                or not all(l and l.replace("-", "").isalnum()
                           for l in labels)):
            raise ValueError(
                f"grant {index}: net.request resource must be a hostname "
                f"(e.g. \"api.example.com\"), received {resource!r}")
    elif not resource.strip().isidentifier():
        raise ValueError(f"grant {index}: data resource must be an entity "
                         f"name, received {resource!r}")
    max_bytes = entry.get("max_bytes")
    if max_bytes is not None and not isinstance(max_bytes, int):
        raise ValueError(f"grant {index}: max_bytes must be an integer")
    expires_raw = entry.get("expires")
    try:
        expires = parse_timestamp(expires_raw) if expires_raw else None
    except ValueError as exc:
        raise ValueError(f"grant {index}: bad expires timestamp: {exc}") from exc
    return Capability(
        action=action,
        resource=resource,
        id=str(entry.get("id", f"grant-{index}")),
        expires=expires,
        max_bytes=max_bytes,
    )


def _scope_covers(scope: str, path: str) -> bool:
    return scope == path or path.startswith(scope + "/")


def _host_covers(scope: str, host: str) -> bool:
    """net.request matching: exact host, or scope covers its subdomains."""
    return host == scope or host.endswith("." + scope)

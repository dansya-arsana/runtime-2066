"""Delegation chains (Stage C, Human Trust Layer): human -> agent ->
sub-agent, every link signed.

An agent holding a delegation from a human may pass PART of it down —
never more. The rules enforced here are the ones the threat model
demands of bearer authority:

- the delegating agent must BE the parent delegation's subject (an
  agent cannot re-delegate authority that was issued to someone else);
- the parent must verify and be unexpired at delegation time;
- the child's resource scope may only stay equal or narrow — never
  widen (a sub-agent sees at most what its delegator held);
- the child may not outlive its parent (expiry is capped per grant);
- hash bindings (`approve --for-hash`) are inherited, so a bound
  approval cannot be re-delegated onto other programs;
- each child records `payload.delegated_by = {issuer, grant_id,
  parent}` — INSIDE the payload, so the reference itself is covered by
  the agent's signature and cannot be rewritten without detection.

`walk_chain` follows those references upward and reports, for every
level: who signed, what was delegated, and whether the link is
expired, revoked, signed by the wrong party, or points at a parent
that cannot be produced.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import identity
from .capabilities import normalize_path, parse_timestamp, sign_capabilities, \
    verify_envelope
from .revocation import grant_id


def scope_narrows(parent: str, child: str, action: str = "") -> bool:
    """True when `child` scope equals or sits inside `parent` scope.

    Filesystem actions use component-wise prefix semantics (same rule as
    GrantSet.check); data actions name bare entities, where the only
    non-widening relation is identity.
    """
    if not isinstance(parent, str) or not isinstance(child, str):
        return False
    if action.startswith("filesystem."):
        parent_n = normalize_path(parent)
        child_n = normalize_path(child)
        return child_n == parent_n or child_n.startswith(parent_n + "/")
    return parent == child


def envelope_issuer(envelope: dict):
    """Issuer display id(s): a string, or a list for multisig files."""
    if isinstance(envelope.get("signatures"), list):
        return [entry.get("agent_id")
                for entry in envelope["signatures"]
                if isinstance(entry, dict)]
    issuer = envelope.get("issued_by") or {}
    return issuer.get("agent_id", "?")


def grant_entry_id(entry: dict) -> str:
    """Per-grant identifier used by revoke (revocation.py convention)."""
    return hashlib.sha256(json.dumps(
        entry, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()


def _child_expires(grant: dict, moment: datetime,
                   ttl_minutes: int | None) -> str | None:
    """Child expiry: inherited from the parent, capped by any TTL.

    Never later than the parent's own expiry — a sub-delegation cannot
    outlive the authority it derives from.
    """
    expires = None
    raw = grant.get("expires")
    if raw:
        expires = parse_timestamp(raw)
    if ttl_minutes is not None:
        ttl_at = moment + timedelta(minutes=ttl_minutes)
        expires = ttl_at if expires is None else min(expires, ttl_at)
    return expires.isoformat(timespec="seconds") \
        if expires is not None else None


def build_delegation(parent_envelope: dict, parent_path, agent: identity.Identity,
                     agent_secret_hex: str, subject: str,
                     ttl_minutes: int | None = None,
                     narrows: list[dict] | None = None,
                     issued_at: str | None = None,
                     now: datetime | None = None) -> dict:
    """Verify a parent delegation and mint a narrowed child, signed by
    the agent's key (NOT the human's).

    parent_envelope: the signed parent file, parsed as JSON
    parent_path:    where the parent lives (recorded in delegated_by)
    agent/secret:   the delegating agent's identity + key
    subject:        the sub-agent receiving the narrowed authority
    ttl_minutes:    optional expiry cap counted from `now`
    narrows:        optional [{'action','resource'}] requests — each must
                    be covered by the parent or ValueError (widen refusal)

    Returns the signed child envelope; raises ValueError on any refusal
    (bad parent signature, expired parent, wrong agent, widening).
    """
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("delegation needs a non-empty --subject "
                         "(the sub-agent receiving the authority)")
    parent_payload = verify_envelope(parent_envelope, require_signed=True)
    moment = now or datetime.now(timezone.utc)

    parent_subject = str(parent_payload.get("subject", "anonymous"))
    if parent_subject != agent.agent_id:
        raise ValueError(
            f"agent {agent.agent_id!r} cannot delegate: the parent "
            f"delegation is for subject {parent_subject!r} — only the "
            f"subject of a delegation may pass it on")

    parent_grants = parent_payload.get("grants", [])
    if not isinstance(parent_grants, list):
        parent_grants = []
    for grant in parent_grants:
        raw = grant.get("expires") if isinstance(grant, dict) else None
        if raw and parse_timestamp(raw) <= moment:
            raise ValueError(f"parent capability expired at {raw} — "
                             f"an expired delegation cannot be passed on")

    if narrows is None:
        # same scope (never wider): copy the parent's grants, capping
        # expiry by the requested TTL where one was given
        child_grants = []
        for grant in parent_grants:
            if not isinstance(grant, dict):
                continue
            child = dict(grant)
            expires = _child_expires(grant, moment, ttl_minutes)
            if expires is None:
                child.pop("expires", None)
            else:
                child["expires"] = expires
            child_grants.append(child)
    else:
        child_grants = []
        for request in narrows:
            action = request.get("action")
            resource = request.get("resource")
            covering = [g for g in parent_grants if isinstance(g, dict)
                        and g.get("action") == action
                        and scope_narrows(g.get("resource", ""), resource,
                                          action or "")]
            if not covering:
                raise ValueError(
                    f"widening refused: {action} on {resource!r} is not "
                    f"within the parent delegation's scope — a "
                    f"sub-delegation may only keep or narrow resources")
            child = {"action": action, "resource": resource}
            limits = [g["max_bytes"] for g in covering
                      if isinstance(g.get("max_bytes"), int)]
            if limits:
                child["max_bytes"] = min(limits)
            parent_exps = [parse_timestamp(g["expires"]) for g in covering
                           if g.get("expires")]
            expires = min(parent_exps) if parent_exps else None
            if ttl_minutes is not None:
                ttl_at = moment + timedelta(minutes=ttl_minutes)
                expires = ttl_at if expires is None else min(expires, ttl_at)
            if expires is not None:
                child["expires"] = expires.isoformat(timespec="seconds")
            child_grants.append(child)

    payload = {
        "subject": subject,
        "grants": child_grants,
        "delegated_by": {
            "issuer": envelope_issuer(parent_envelope),
            "grant_id": grant_id(parent_envelope),
            "parent": str(parent_path),
        },
    }
    inherited = parent_payload.get("bound_program_hash")
    if inherited:
        # a hash-bound approval stays bound down the chain
        payload["bound_program_hash"] = inherited

    stamp = issued_at or datetime.now(timezone.utc).isoformat(
        timespec="seconds")
    return sign_capabilities(payload, agent, agent_secret_hex, stamp)


def walk_chain(path, revocations=None,
               now: datetime | None = None) -> list[dict]:
    """Follow delegated_by references from `path` up to the human root.

    Returns one record per level (leaf first). Every level's envelope
    signature is verified; a bad signature raises ValueError. Link
    integrity problems do not raise — they are reported as flags on the
    levels so the caller can show the whole picture:

      expired         a grant on this level is past its expiry
      revoked         this level (set or individual grant) is revoked
      issuer_mismatch the level below was signed by someone who is not
                      this level's subject (forged link)
      parent_mismatch the parent file produced does not hash to the
                      referenced grant_id (substituted parent)
      parent_missing  the referenced parent file is not available
    """
    moment = now or datetime.now(timezone.utc)
    levels: list[dict] = []
    seen: set[str] = set()
    current = str(path)
    pending_ref: dict | None = None
    while current:
        envelope = json.loads(
            Path(current).read_text(encoding="utf-8"))
        payload = verify_envelope(envelope, require_signed=True)
        gid = grant_id(envelope)
        if pending_ref is not None and gid != pending_ref.get("grant_id"):
            levels[-1]["parent_mismatch"] = True
            break
        if gid in seen:
            raise ValueError(f"delegation cycle detected at {current}")
        seen.add(gid)

        grants = payload.get("grants", [])
        grants = [g for g in grants if isinstance(g, dict)]
        expired_at = [g["expires"] for g in grants if g.get("expires")
                      and parse_timestamp(g["expires"]) <= moment]
        revoked = (revocations is not None
                   and (revocations.is_revoked(gid)
                        or any(revocations.is_revoked(grant_entry_id(g))
                               for g in grants)))
        reference = payload.get("delegated_by")
        if not isinstance(reference, dict):
            reference = None
        level = {
            "file": current,
            "issuer": envelope_issuer(envelope),
            "subject": str(payload.get("subject", "anonymous")),
            "grants": [{"action": g.get("action"),
                        "resource": g.get("resource"),
                        "expires": g.get("expires")} for g in grants],
            "grant_id": gid,
            "expired": bool(expired_at),
            "expired_at": expired_at,
            "revoked": revoked,
            "delegated_by": reference,
            "parent_missing": False,
            "parent_mismatch": False,
            "issuer_mismatch": False,
        }
        if levels:
            # the level below was signed by this level's SUBJECT —
            # anything else is a forged link
            child = levels[-1]
            issuers = child["issuer"] if isinstance(child["issuer"], list) \
                else [child["issuer"]]
            child["issuer_mismatch"] = level["subject"] not in issuers
        levels.append(level)

        if reference is None:
            break
        parent_file = reference.get("parent")
        if not parent_file or not Path(parent_file).exists():
            level["parent_missing"] = True
            break
        pending_ref = reference
        current = parent_file
    return levels


def chain_ok(levels: list[dict]) -> bool:
    """True when every level and link is healthy."""
    return not any(level.get("expired") or level.get("revoked")
                   or level.get("parent_missing")
                   or level.get("parent_mismatch")
                   or level.get("issuer_mismatch")
                   for level in levels)

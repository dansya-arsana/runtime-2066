# spec/identity.md — Agent Cryptographic Identity (Phase 7, §26)

Status: normative for Milestone 4a. Implements roadmap §26 (agent identity)
and the crypto-agility rule (§64); groundwork for signed proposals (§28).

## Principles

1. **Crypto agility (§64).** Everything is algorithm-tagged. V1 supports
   `ed25519` only; unsupported tags fail closed. Future algorithms
   (including post-quantum) slot in without changing file formats' shape.
2. **Reuse-first (§6, Appendix A).** Signing is provided by the
   `cryptography` package (Apache-2.0/BSD-3) — the project's first
   third-party dependency, recorded in DEPENDENCIES.md with a replacement
   plan. Hand-rolled cryptography is not an option.
3. **Fail closed.** Verification failure of any kind — malformed keys,
   unsupported algorithms, bad signatures — refuses the whole artifact.
   `verify()` returns a boolean; nothing partial ever loads.
4. **Determinism.** ed25519 is deterministic: the same bytes + key always
   produce the same signature, so signed artifacts are reproducible.

## Canonical signing bytes

All signatures cover `canonical_json(obj)`: UTF-8 JSON with sorted keys,
compact separators. Any change to any signed value — including reordering
that changes canonical form — breaks the signature.

## File formats

Identity file (public — commit/share freely):

```json
{"agent_id": "agent-A91", "algorithm": "ed25519",
 "public_key": "<64 hex chars = 32 bytes>", "created": "<iso-8601>"}
```

Secret key file (**never commit, never share**):

```json
{"agent_id": "agent-A91", "algorithm": "ed25519",
 "secret_key": "<64 hex chars = 32-byte ed25519 seed>"}
```

## Signed grant envelopes (§18 signature field)

`sign-caps` wraps a plain grants payload:

```json
{
  "issued_by": {"agent_id": "...", "algorithm": "ed25519",
                "public_key": "<64 hex>"},
  "issued_at": "<iso-8601>",
  "payload": { ...the grants object... },
  "signature": "<128 hex chars over canonical_json of the three fields above>"
}
```

Rules:

- `run --caps signed.json` **always verifies signed envelopes** and refuses
  the entire file on any failure (exit 3).
- Unsigned grant files remain accepted for the transition period, but
  `--require-signed` refuses them; the threat model recommends signed
  grants everywhere. Unsigned acceptance is scheduled for removal once
  identity-backed issuance is the default.
- The signature covers the payload exactly; widening a scope, raising a
  limit, or editing a timestamp invalidates it. Whoever can edit the file
  still cannot forge the issuer's signature.

## CLI

```bash
python -m runtime keygen agent.json --id agent-A91   # writes agent.json + agent.key
python -m runtime sign-caps caps.json --agent agent.json --key agent.key --out signed.json
python -m runtime verify-caps signed.json            # OK / issued_by / grants count
python -m runtime run program.ai --caps signed.json --require-signed
```

## Identity vs authority (roadmap §54)

Possessing an identity — even the issuer's secret key — grants no execution
authority by itself. Identity makes grants *attributable*; capabilities
remain the only path to effects. `agent_self_elevation = forbidden`
(§58) stays structural: no instruction can mint or widen anything.

# The 2066 Trusted Computing Base (plan SS6)

> A reviewer can audit the TCB without reading the ecosystem. Layer
> membership is ENFORCED by tests/architecture/test_boundaries.py.

## In the TCB (must be correct for security to hold)

| Module | Role |
|---|---|
| `runtime/parser.py` | untrusted text → semantic graph (grammar gate) |
| `runtime/types.py` | literal parsing/rendering (canonical identity) |
| `runtime/serialize.py` + `hashing.py` | canonical form + program identity |
| `runtime/validator.py` | deterministic validation, effect resolution |
| `runtime/capabilities.py` | grant loading, scope/expiry checks, envelopes |
| `runtime/identity.py` | ed25519 sign/verify (algorithm-tagged ABI) |
| `runtime/ops.py` + `interpreter.py` + `plan_vm.py` | execution semantics incl. guards |
| `runtime/session.py` | token verification (mint stays in hosts) |
| `runtime/evidence.py` | hash-chained audit rules |
| `runtime/proposals.py` | signed mutation + deterministic merge |
| `runtime/packages.py` | semantic addressing (traversal-proof) |
| `runtime/ports.py` | the contracts adapters must satisfy |

## Outside the TCB (replaceable, never trusted for authority)

`data.py`/`memory_store.py` (storage adapters — differentially proven
interchangeable), `fsops.py`, `keydisk.py`, `multisig.py`,
`delegation.py`, `pinning.py`, `sbom.py`/`release.py`/`backup.py`/
`bundle.py` (release tooling), `apps/**` (HTTP shells + UI — §58: UI is
never an authority source), `examples/**`, CLI UX, everything external
(HTTP, TLS, Docker, Cloudflare, LLM providers).

## Review guide

1. Read CONSTITUTION.md + BOUNDARIES.md + this file.
2. Audit the TCB table top-to-bottom (~3.5k lines total).
3. The security claim is exactly: untrusted programs cannot cause an
   effect outside an explicitly granted, unexpired, unrevoked,
   hash-bound scope. Every TCB module exists to enforce that sentence.
4. Known accepted risks live in THREAT_MODEL.md — including the
   unsigned-grant transition (closed by `--profile production`).

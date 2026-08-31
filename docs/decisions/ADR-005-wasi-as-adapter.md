# ADR-005 — WASI is an adapter, not the authority model

Date: 2026-08-31 · Status: accepted (implementation deferred, plan SS53)

## Decision
2066 capabilities map DOWN onto WASI resource handles; WASI never
defines 2066 authority. The semantic capability check happens first,
WASI is one enforcement boundary underneath.

## Consequences
- Future WASI executor is a conformant executor (SS72) and must pass
  the shared conformance corpus unchanged.
- No capability semantics may be delegated to the sandbox.

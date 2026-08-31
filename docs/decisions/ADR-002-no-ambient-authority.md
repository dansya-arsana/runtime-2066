# ADR-002 — No ambient authority

Date: 2026-08-30 · Status: accepted

## Decision
Every effectful operation requires an explicit capability grant checked
at the effect boundary; absent grants mean denial (E401), never a
fallback. No `admin`/`root`/`*` catch-alls exist or will be added
(SS46). Time (SS39), transport, storage, and randomness are injected —
the core reads nothing ambient.

## Consequences
- Programs carry their authority requirements statically (`2066
  inspect` capabilities; `2066 effects` manifest).
- The security test matrix (tests/security) pins refusal behavior for
  expired/scoped/forged authority.
- Hosts (servers) hold the secrets programs structurally cannot mint.

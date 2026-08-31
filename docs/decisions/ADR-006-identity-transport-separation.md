# ADR-006 — Identity is separate from transport

Date: 2026-08-31 · Status: accepted

## Decision
Agent identity is algorithm-tagged cryptographic keys (ed25519 today,
PQC-ready shape); messages are signed semantic objects. Transport
(LAN/Tor/offline bundle, M10+) resolves reachability and MUST NOT alter
semantic identity: same payload, same hash, on every transport.

## Consequences
- Signed envelopes (grants, proposals, releases, bundles) are already
  transport-independent artifacts verified end-to-end today.
- Resource identity is semantic (`sales::business::12`, SS47), not a
  URL; transport resolves where, never what.

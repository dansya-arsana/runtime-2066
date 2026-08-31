# ADR-001 — The semantic graph is the source of truth

Date: 2026-08-30 (ratified H-cycle 2026-08-31) · Status: accepted

## Context
Conventional stacks make generated code the artifact humans and agents
edit; the "real" intent becomes archaeology.

## Decision
`.ai` canonical semantic programs are the single source of truth.
Python/JavaScript exports are disposable generated artifacts (roadmap
§4.10); conventional languages may never become authoritative.

## Consequences
- Identity = canonical SHA-256 (formatting-insensitive; P1/P2 property
  tests pin this).
- Conformance corpus (protocol/conformance) freezes identity: changing
  program content is a protocol event.
- Exports may lag or diverge; they are compatibility surfaces, not
  conformant executors (backend classification, plan SS72).

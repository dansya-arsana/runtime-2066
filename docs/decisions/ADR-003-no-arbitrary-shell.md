# ADR-003 — No arbitrary shell / escape hatches

Date: 2026-08-30 · Status: accepted

## Decision
No eval, raw_python, raw_js, shell, or native_code ops (SS74). The
protocol's answer to "but sometimes you just need X" is a new NAMED,
capability-gated effect — never a generic escape.

## Consequences
- The op set grows only by protocol decision with authority review
  (change classification, BOUNDARIES.md).
- `net.fetch` (SS73-compliant) is the precedent: outbound effects are
  allowlisted by host, transport host-supplied, runtime owns no sockets.

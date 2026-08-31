# ADR-004 — Functional core, imperative shell

Date: 2026-08-31 · Status: accepted (enforced by
tests/architecture/test_boundaries.py)

## Decision
Parse/validate/canonicalize/hash/plan are pure functions over immutable
values; effects (SQLite, filesystem, network, clock) live behind
injected adapters conforming to runtime/ports.py contracts.

## Consequences
- The core imports no storage/network/process machinery — import
  analysis fails the suite on violation.
- Two execution adapters (tree, plan VM) and two stores (SQLite,
  memory) already prove replaceability differentially.
- The path to the independent Rust core (H8) is the same seam.

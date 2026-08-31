# 2066 Specification — Protocol 0.2

Status: normative. The whitepaper explains; this tree defines. Every
behavior claim is testable against the conformance corpus
(protocol/conformance) and the 394-test suite. A second, independent
implementation (rust-canonicalizer) reproduces canonical identity for
the entire corpus — the spec, not any codebase, is the source of truth.

2066 programs are **semantic graphs**, not source code in a conventional
language. The runtime parses, validates, and executes them directly; no
JavaScript, Python, Rust, or shell is ever generated (roadmap §12 success
condition).

Pipeline:

```text
program.ai
   ↓ Parser        (spec/graph.md)
Semantic Graph (main + functions)
   ↓ Validator     (spec/instructions.md)
Analysis (scopes, topo orders, types)
   ↓ canonical serialization + SHA-256 identity   (§15)
   ↓ Adapter       (tree-walking interpreter | compiled-plan stack VM)
Emitted Results — identical across adapters (Appendix F.3)
   ↑
repair loop      (spec/errors.md; `python -m runtime repair`)
```

Normative modules:

- [spec/graph.md](spec/graph.md) — file grammar, node model, scopes, ordering, emit
- [spec/instructions.md](spec/instructions.md) — the V0 instruction set and semantics
- [spec/types.md](spec/types.md) — primitive types, literals, arithmetic rules
- [spec/errors.md](spec/errors.md) — structured error protocol, exit codes, repair loop
- [spec/identity.md](spec/identity.md) — agent identity, signed grants
- [spec/capabilities.md](spec/capabilities.md) — the capability model (actions, scopes, expiry, delegation)
- [spec/effects.md](spec/effects.md) — effect classes and their authority
- [spec/packages.md](spec/packages.md) — semantic packages: package::module::unit
- [spec/canonicalization.md](spec/canonicalization.md) — canonical form + program identity
- [spec/ir.md](spec/ir.md) — the semantic IR
- [spec/proposals.md](spec/proposals.md) — signed proposals + deterministic merge
- [spec/evidence.md](spec/evidence.md) — hash-chained evidence
- [spec/hardware-key.md](spec/hardware-key.md) · [spec/key-copying.md](spec/key-copying.md) — human authority

Design invariants for everything below:

1. **One canonical form per construct** (roadmap §8). No syntactic synonyms.
2. **Deterministic** — same program + same runtime version ⇒ byte-identical
   output and byte-identical errors, always (roadmap §4.9).
3. **Fail fast on the first error**, reported structurally with repair hints
   (roadmap §13); `cast` repairs are mechanically applicable by the runtime.
4. **Every effect is explicit and capability-gated** (Phase 3–4, §17–§20):
   `python -m runtime effects <file>` states what authority a program needs
   before it runs; the runtime enforces grants and denies by default.
5. **Pure by default; effects are explicit.** Filesystem, data
   (SQLite/memory adapters), and outbound network (`net.fetch`,
   hostname-allowlisted) exist ONLY behind capability grants. Processes
   and arbitrary shell are rejected permanently (ADR-003).
6. **Engine independence** (Appendix F.3): two in-runtime adapters
   (tree, plan VM) plus two storage adapters (SQLite, memory) are
   proven equivalent by differential tests, and an independent Rust
   implementation reproduces canonical hashes for the whole corpus
   (tests/independent).

7. **Protocol versioning.** `PROTOCOL_VERSION = 0.2` is separate from
   runtime version; programs may declare `protocol 0.2` and incompatible
   runtimes refuse (E109) rather than misread.

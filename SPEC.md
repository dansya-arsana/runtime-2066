# 2066 Specification — V0 (Milestone 1)

Status: Working draft for the interpreter foundation (master roadmap §10–§14).

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
- [spec/identity.md](spec/identity.md) — agent identity, signed grants (Phase 7)

Design invariants for everything below:

1. **One canonical form per construct** (roadmap §8). No syntactic synonyms.
2. **Deterministic** — same program + same runtime version ⇒ byte-identical
   output and byte-identical errors, always (roadmap §4.9).
3. **Fail fast on the first error**, reported structurally with repair hints
   (roadmap §13); `cast` repairs are mechanically applicable by the runtime.
4. **Every effect is explicit and capability-gated** (Phase 3–4, §17–§20):
   `python -m runtime effects <file>` states what authority a program needs
   before it runs; the runtime enforces grants and denies by default.
5. **V0+ is pure by default.** Only capability-gated filesystem effects
   exist today; the network, processes, and data layer arrive only behind
   the same explicit model.
6. **Engine independence** (roadmap §102, Appendix F.3): the canonical form
   is the primary artifact; any number of execution adapters may consume it,
   and equivalent results across adapters are enforced by tests.

# research/bootstrap_comparison.md

Master roadmap §102 requires the first engineering sprint to compare three
bootstrap approaches and select the smallest that preserves 2066 semantics
and security boundaries. This note records that comparison (Appendix G
research-before-build rule). Date: 2026-08-30. Status: decision made for
the current stage; two options carry explicit revisit triggers.

```text
A   minimal custom interpreter           — implemented (runtime/interpreter.py)
A′  compiled-plan stack VM adapter       — implemented (runtime/plan_vm.py)
B   WASI/WebAssembly-backed executor     — evaluated, deferred (trigger below)
C   existing semantic-runtime adapter    — evaluated, deferred (trigger below)
```

## Criteria (from §79 and Appendix A.3)

1. Semantics preservation: deterministic, total operations; structured
   errors identical across engines (§13, §4.9).
2. Security-boundary fit: no ambient authority at the host boundary (§20,
   B.2). Decisive only once effects/capabilities exist (Phase 4–5).
3. Dependency risk: replaceable, offline-viable, permissive license; no
   hidden constitutional authority.
4. Evidence determinism: same program ⇒ same result and same errors.

## Findings

### A — minimal custom interpreter (chosen baseline)

Zero dependencies; full V0 semantics in ~250 lines; the reference engine
for every spec statement. Weakness: a single engine cannot prove that the
semantic representation outlives its implementation — §102's final
requirement ("the same semantic program can execute through more than one
adapter") needs a second engine.

### A′ — compiled-plan stack VM (implemented this sprint)

Compiles the validated Analysis into a linear, serializable plan
(`LOAD/CONST/ADD/.../CALL/EMIT/RETURN` over SSA-like slots) and executes it
on a separate stack machine. Still dependency-free, but a genuinely
different engine shape (linear plan vs tree walk).

Result — Appendix F.3 satisfied with two real adapters:

- Operation semantics are shared by construction (`runtime/ops.py` is the
  single dispatcher both engines call).
- Equivalence is proven by tests over the full example corpus plus
  adversarial runtime-error programs (`tests/runtime/test_adapters.py`):
  identical emitted values — NaN/inf compared by canonical rendering — and
  identical structured errors (same code, node, operation, rendering).
- CLI: `python -m runtime run <file> --adapter plan` vs `--adapter tree`.

This demonstrates the §102 thesis at engine level: **the semantic
representation outlives its implementation** — the same canonical program
hashes identically and executes equivalently regardless of engine.

### B — WASI/WebAssembly-backed executor (deferred)

Strongest long-term fit for the trust boundary: WASI's "no ambient
authority" is exactly the host-boundary principle 2066 requires (roadmap
B.2), and a plan → Wasm lowering is the naturalOptimizer/JIT path (§10).

Deferred because:

- Embedding a Wasm runtime (e.g. wasmtime) adds a large native dependency
  before 2066 has any external effect to sandbox — DEPENDENCIES.md is
  intentionally stdlib-only at this stage, and a sandbox guarding pure
  computation buys nothing.
- The engine-independence requirement F.3 is already met by A + A′.

Revisit trigger: **Phase 4–5 (capability runtime)** — when filesystem or
network capabilities must be enforced at a real host boundary, spike
`plan → Wasm` against wasmtime/WASIP2 and re-run the F.3 corpus plus
capability-denial tests (Appendix F.4).

### C — existing semantic-runtime adapter (deferred; e.g. AIKernel, roadmap B.3)

Coupling the bootstrap to a foreign runtime before the canonical form,
hashing, and error protocol are stable would make 2066 semantics
implementation-defined — the opposite of §102's intent.

Deferred because:

- The 2066 IR is now self-describing (canonical serializer + SHA-256
  identity), which is precisely what an external adapter would consume.
- No mature open implementation of comparable semantics (deterministic
  total arithmetic + structural validation + scoped functions) was
  identified in the roadmap's August-2026 survey (Appendix A.2).

Revisit trigger: when an external tool first consumes 2066 programs (the
hash or the plan), evaluate an AIKernel-style adapter as a third engine in
the F.3 matrix instead of hand-porting.

## Decision

Proceed with **A + A′** as the execution substrate for Stage A. Record
every program's canonical hash (`python -m runtime hash`). B and C stay on
the roadmap with the triggers above; neither becomes a dependency without
passing the same corpus-equivalence and capability-denial gates.

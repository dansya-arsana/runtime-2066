# The 2066 Philosophy — Trust Over Tokens

Distilled from the master roadmap (§1–§4, §8, §44, §86–§92, §101) and
confirmed by our own measurements (benchmarks/RESULTS.md, 2026-08-30).

## The economics: compute is abundant, trust is scarce

Tokens are the cheapest thing in the system. An agent can burn 9× more
tokens authoring a canonical semantic program than writing the same logic
in Python — and should, when those tokens buy:

- **validation before execution** — a bad program is rejected
  deterministically, with machine-usable repairs, never with a runtime
  surprise;
- **one artifact, many backends** — Python and JavaScript compiled from
  the same graph cannot drift apart, because neither was authored
  separately;
- **provenance** — a canonical hash, so "which program is running?" has a
  cryptographic answer, not a Best Effort;
- **capability-bounded effects** — what the program may *do* is policy,
  enforced by the runtime, invisible to the model that proposed it.

Roadmap §4.8 says it as a rule: *verification should be cheaper than
trust.* The 2026 benchmark made it concrete: 579 tokens plus 3.7 ms of
regeneration plus 6.7 s of tests buys what the conventional route pays for
in debugging cycles — the cost that never shows up in a token count.

## The assumptions behind the rule

1. **AI intelligence ≠ AI authority** (§3.2). The system must be safe even
   when the model is wrong, adversarial, compromised, or hallucinating.
   Nothing in the pipeline may rely on the model being careful.
2. **No undefined behavior** (§4.9). Deterministic semantics are what make
   verification mechanical. If outcomes were ambiguous, trust would require
   a human reading code again — the exact cost 2066 exists to remove.
3. **Conventional source is an artifact** (§4.10). Python, JavaScript, and
   future targets are compiled outputs. You audit the graph and the
   evidence, not the dialect.
4. **Open proposal, closed authority** (§92). Anyone — any model — may
   draft. Nothing executes without verification and, where effects are
   involved, explicit capability.

## What this philosophy is not

- Not "more tokens are always better." Verbosity is a current format
  property, not the product. If a compact canonical form emerges in
  Phase 2, burn fewer tokens for the same trust.
- Not "human review is obsolete." Humans set policy, delegate authority,
  and approve what policy flags (§94). What becomes obsolete is *re-reading
  code as the trust mechanism*.
- Not safety through the model being aligned, capable, or honest. The
  runtime assumes none of those things — that is the entire design
  constraint (§1: "AI intelligence ≠ AI authority").

## Breaking the revise–pentest–burn loop

The expensive cycle in AI-driven software is not drafting — it is the loop:
draft → test → revise → pentest → *hacked anyway* → rewrite. And when a new
model ships, the loop restarts, because the asset was the generated code,
which the next model regenerates differently. Infrastructure providers get
paid for every lap.

2066 breaks the loop by making **the semantic program the asset**:

1. **Model churn becomes cheap.** `engine.ai` does not change when models
   change. A new model re-drafts at most the UI shell; the verified engine
   re-compiles to every backend in milliseconds (`export`, `--library`),
   and the canonical hash proves nothing drifted. Migration is
   `export + test suite`, measured in seconds — not a rewrite.
2. **The pentest loop shrinks.** Attack surface is grammar-checked
   structure: no injection surface (values are bound parameters —
   `x'; DROP TABLE user;--` is inert data, verified in
   tests/runtime/test_data.py), no ambient authority (effects exist only
   behind signed, scoped, expiring capabilities), no undefined behavior to
   fuzz for. When a hack *does* land, capabilities bound the blast radius
   and deterministic evidence says exactly what ran.
3. **Fixes are structural, not per-model.** A validated repair to one .ai
   program fixes every backend, every deployment, every consumer of the
   hash — once. In the conventional loop, the same class of bug is
   re-discovered (and re-paid for) in every generated variant.

Measured on this repository: regenerate both backends 3.7 ms; full
verification suite 6.7 s; exported JavaScript within ~9× of V8-native on
straight-line code (benchmarks/RESULTS.md).

## One sentence

> Spend tokens on the machine's draft; spend **trust** only on what the
> verifier proved. Everything else is negotiation.

## Evidence from this repository

- benchmarks/RESULTS.md — the 9× authoring cost, the 3.7 ms multi-backend
  regeneration, and the 6.7 s full-suite verification, measured.
- tests/runtime/test_identity.py — tamper-evident grants: edit one byte of
  a signed capability file and the runtime refuses all of it.
- tests/runtime/test_fs_effects.py — a program reaching outside its grant
  scope is denied with the real normalized path in the error (§82 beat).
- tests/runtime/test_adapters.py — one semantic program, two independent
  engines, identical results and identical errors.


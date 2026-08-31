# 2066 — An AI-Native Semantic Execution and Authority Layer

**White Paper · v1.2.0 · August 2026**

> *2066 is an open execution layer where untrusted autonomous agents may
> construct, mutate, and run software — and deterministic semantics,
> explicit capabilities, cryptographic authority, and verifiable evidence
> decide what actually happens.*

---

## 1. Abstract

Software construction is becoming the output of autonomous agents. The
stack those agents build on was designed for humans: syntax optimized for
reading, ambient authority optimized for convenience, and security
optimized for trustworthy authors. None of those assumptions survive
contact with machine authors that can be wrong, manipulated, or
adversarial.

2066 inverts the stack. Programs are **semantic graphs** in a canonical,
unambiguous form — authored by any agent (human or AI), validated by a
deterministic runtime before execution, and identified by hash. Programs
never become JavaScript or Python in order to run; conventional languages
are optional, generated artifacts. Every effect a program can cause is
gated by a **capability**: scoped, expiring, cryptographically signed
authority held by the runtime, structurally impossible for the program to
mint or widen. Multiple agents collaborate by **signing node-level
proposals** against a base graph, which the runtime merges
deterministically — auto-merging independent work and rejecting conflicts
with attribution.

The result is a different cost structure. Where conventional AI
development spends its budget on the loop — generate, test, revise,
pentest, get hacked, regenerate when the next model ships — 2066 spends
**milliseconds of verification**. This paper specifies the architecture,
the authority model, measured performance, and the honest limitations
(including where 2066 loses today), and lays out the path from the
currently implemented core (265 deterministic tests, nine milestones) to
an open network of untrusted, economically bounded agents.

---

## 2. The Problem

### 2.1 The revise–pentest–burn loop

The expensive part of AI-driven software is not the first draft. It is
the loop:

```text
generate → test → revise → pentest → hacked anyway → rewrite
   ▲                                                    │
   └────────── new model ships, loop restarts ◄─────────┘
```

Two structural facts keep this loop turning. First, *the generated code
is the asset*: when models change, the code is regenerated differently
and every lap of the loop is re-paid. Second, *verification is manual*:
the only way to trust generated code is to read it, test it, and audit
it — with human (or human-supervised) attention per artifact, per model,
per revision. The loop is where infrastructure spend accumulates, and it
is structurally incapable of shrinking while code remains the asset.

### 2.2 Authority without ambient trust

An agent that can write arbitrary code can shell out, read the
filesystem, exfiltrate secrets, and prompt-inject its supervising
systems. Current mitigation — sandboxes plus review — bounds some of
this, but the authority model of conventional languages is ambient: code
*inherits* the privileges of its runtime. "AI intelligence" and "AI
authority" are conflated by construction.

### 2.3 The requirement

A system where autonomous agents do most software construction needs,
minimally:

1. a representation **cheap to verify and expensive to fake**;
2. authority that is **explicit, scoped, and external to the model**;
3. collaboration that **merges mechanically** instead of conflicting
   textually;
4. an audit trail that **cannot silently disappear**.

No existing stack provides all four. 2066 is the missing layer.

---

## 3. Core Thesis

```text
AI intelligence ≠ AI authority.
```

A model may *propose* any operation. It may never *grant itself
permission* to perform one. Every architectural decision in 2066 follows
from this single rule (Constitution, Law 1). The system assumes the
proposing model can be arbitrarily capable, hallucinating, prompt-
injected, or outright adversarial, and remains safe anyway — because
nothing the model emits carries authority. Authority enters only through
cryptographic objects (capabilities, delegations, proposals) signed by
holders the runtime already trusts, and the runtime — never the model —
enforces them.

The companion economic rule (Constitution, Law 8): **verification should
be cheaper than trust.** Where Bitcoin manufactures trust with
gigawatts, 2066 replaces trust with deterministic verification measured
in milliseconds. Tokens spent on an agent's draft are the cheapest line
item in the system; the expensive artifact is *verified behavior*, and
2066 makes producing it mechanical.

---

## 4. Architecture

```text
                 HUMAN INTENT
                        │
                        ▼
                    AI AGENTS
                        │
              ┌─────────┴─────────┐
           PROPOSALS          REQUESTS
              └─────────┬─────────┘
                        ▼
              2066 SEMANTIC GRAPH          ← canonical, hashed
                        │
                        ▼
                  VALIDATOR                ← deterministic, fail-fast
                        │
         ┌──────────────┼──────────────┐
         ▼              ▼              ▼
   EFFECT MODEL   CAPABILITY ABI   EVIDENCE
         └──────────────┼──────────────┘
                        ▼
              EXECUTION ADAPTERS
           (tree · plan-VM · export: Python/JS)
                        │
                        ▼
              RESULT + TAMPER-EVIDENT LOG
```

**Layers, implemented status:**

| Layer | Status |
|---|---|
| Canonical semantic IR + hashing (§15) | implemented — canonical form is the primary artifact; SHA-256 identity |
| Deterministic validator + structured errors (§13) | implemented — 39 error codes, machine-usable repairs |
| Unified effect model (Appendix C.2) | implemented — PURE / SYSTEM / IDENTITY / FILESYSTEM_* / DATA_* |
| Capability ABI (§17–§20, C.3) | implemented — scoped, expiring, size-limited, signed, default-deny |
| Agent identity (§26) | implemented — ed25519, algorithm-tagged (crypto agility §64) |
| Semantic mutation protocol (§29–§30, C.4) | implemented — signed proposals, deterministic merge, conflict attribution |
| Evidence protocol (C.5) | implemented — hash-chained append-only audit |
| Semantic data runtime (§22–§25) | implemented — entities → SQLite, runtime-written SQL only |
| Human key preparation (§31–§33) | implemented — any removable disk as a PIN-protected approval object |
| Export backends (§10) | implemented — Python, JavaScript (library mode) |
| Open network / economy (Stages D–E) | not built — deliberately sequenced last (§45–§47) |

## 4.1 The semantic program

A program is a graph of nodes; canonical text form is one node block of
single-field lines:

```text
node 001
op const
type i64
value 10

node 002
op const
type i64
value 5

node 003
op multiply
input 001 002
output i64

node 004
op emit
input 003
```

Design properties:

- **One canonical form per construct.** No synonyms, no sugar, no
  formatting freedom that survives hashing. Layout (whitespace,
  comments, field and declaration order) is a *view*; the canonical
  serializer erases it, so two sources with the same SHA-256 are the
  same program — provable, not asserted.
- **Total semantics.** i64 overflow is an error, never wraparound;
  division by zero is structured (E301); f64 is IEEE-total; every
  malformed construct yields a structured error. There is no undefined
  behavior anywhere in the language, including in rejection paths.
- **Terminating by construction.** Graphs are DAGs, the call graph is
  acyclic (recursion is rejected E212), and there is no unbounded
  iteration. Lists are values consumed by `length`/`get`/`join`, not
  looped over.
- **Everything evaluates.** `branch` is a pure value select, not
  control flow — a deliberate constraint that keeps evaluation
  order-independent and side-effect placement explicit.

The current instruction set is 30 operations across values, arithmetic,
logic, functions, I/O, crypto, filesystem, data, sessions, and lists —
each with a declared effect class and capability requirement published
in a machine-readable reference generated from the live runtime
(`python -m runtime reference`), so documentation cannot drift from
implementation.

## 4.2 Verification and repair

Validation is deterministic and fail-fast; the first error is a
structured record, not a stack trace:

```text
ERROR E203

node: 003
operation: add

expected:
  input[1]: i64
received:
  input[1]: string

allowed_repairs:
  - cast node 002 -> i64
  - replace node 002
```

Repairs of the `cast node X -> T` form are **mechanically executable**:
the runtime inserts the cast node, rewires the edge, re-validates, and
emits the canonical repaired program. Repair stops where authority
would be needed to invent new intent (`replace` suggestions remain
agent-authored hints). This closes the loop that §13 of the design
memo calls the repair cycle: generate → validate → explain structurally
→ repair → execute, with no human in the path.

---

## 5. The Authority Model

### 5.1 Capabilities: default deny, always

Effectful operations name an action and a resource; the runtime checks
a **grant set** loaded at process start:

```json
{"subject": "agent-A91", "grants": [
  {"action": "filesystem.read", "resource": "/incoming",
   "max_bytes": 65536, "expires": "2036-01-01T00:00:00Z"},
  {"action": "data.read", "resource": "note"}]}
```

- **No grant set attached = zero authority.** Even reading an existing
  file is denied (E401). There is no "grant everything" flag.
- Scope matching is component-wise on normalized paths: a grant on
  `/incoming` covers `/incoming/a.txt`, never `/incoming.txt` or the
  parent; `../` traversal is normalized away before the check.
- Write limits (scope, expiry, byte budget) are enforced **before** any
  byte reaches the disk.
- Data actions are separate capabilities per entity — `data.read:note`
  cannot delete; deletion is its own action (§24). The AI never writes
  SQL: the runtime generates every statement with bound parameters, so
  injection payloads land as inert data (tested with live payloads).
- Denials are a distinct exit code (4) with the *actual normalized
  resource* named in the error — supervising agents can tell "policy
  said no" from crashes, and cannot mistake the boundary's location.

### 5.2 Signed authority and tamper-evidence

Grant files carry ed25519 issuer signatures over the canonical form of
the entire payload (scopes, limits, expiry, issuer, timestamp).
Verification is fail-closed at load: editing one byte of a signed file
— widening a scope, raising a limit — refuses the whole grant set.
There is no partial load, ever.

Session capabilities extend this to interactive use: the trusted host
mints short-lived signed tokens after the engine validates credentials;
programs verify tokens through a `session.verify` operation but
**structurally cannot mint them** (no such operation exists — the
guarantee is the instruction set, not policy).

Every privileged data write appends to an append-only **evidence log**
whose records are hash-chained (each carries the previous record's
digest). Editing, deleting, or reordering records is detectable by
anyone holding the log — "critical evidence cannot silently disappear"
holds without key management, and a `verify` command walks the chain
and names the first broken link.

### 5.3 Human authority from any disk

The physical approval object (§31–§33) is today any removable disk —
explicitly including an old flashdisk. `key-format` writes a
PIN-encrypted ed25519 identity (HKDF → AES-256-GCM) into `.2066key/`,
non-destructively; eight wrong PINs destroy the secret. `approve`
converts a human's key-disk unlock into a short-TTL signed delegation.
The §84 approval loop is fully realized in software:

```text
agent requests effect          → E401 DENIED
human approves from key disk   → signed delegation, expires in 5 min
agent runs under delegation    → allowed (--require-signed)
delegation expires             → E402 DENIED
```

The threat model is stated, not implied: the disk is a **bearer
object** (possession = authority; no secure element exists in a
flashdisk), and attempt-limiting is best-effort against an attacker who
images the disk. The envelope is deliberately the same interface a real
secure element would expose, so the Phase-10 hardware upgrade swaps the
backend, not the callers.

---

## 6. Multi-Agent Collaboration

Agents do not edit files. An agent signs a **proposal**: a node-level
diff (added / changed / removed units) against the canonical hash of a
base program. The runtime then decides:

- **Verification, fail-closed:** signature invalid (E602), base hash
  moved — *"the graph moved; re-proose"* (E601) — or malformed shape
  (E604) each refuse the proposal outright. An impostor claiming
  another agent's identity fails signature verification.
- **Deterministic merge:** proposals with disjoint changes merge
  automatically; identical duplicate changes deduplicate; two agents
  mutating the same unit *differently* reject the merge, naming the
  unit and both authors — never a silent overwrite. A merge is not
  complete until the reconstructed program re-validates; an invalid
  result is rejected with a report, never half-applied.

This is the piece that requires the graph to be the asset (§4.1): with
canonical node identity, "conflict" is decidable in machine terms. The
demonstrated case (§83): two agents independently add `negate()` and
`double()` to one engine — merged, valid, running; a third agent's
conflicting `negate()` — rejected with unit-level attribution.

Because proposals bind to base hashes, model churn does not invalidate
collaboration: a new model re-proposes against the current hash;
everything already merged and verified stands untouched.

---

## 7. Execution and Measured Performance

Two independent engines execute the same validated analysis — a
tree-walking interpreter and a compiled-plan stack VM — sharing one
operation-semantics module, with adapter equivalence enforced by tests
over the full corpus including adversarial error programs (Appendix
F.3: identical outputs and byte-identical structured errors). Export
backends lower the plan to standalone Python or JavaScript; exported
artifacts carry the program's canonical hash in their header, and
capability-gated effects refuse to export — exported code runs outside
the authority plane, and the boundary stays honest.

Measured (best-of-5, 10,000-operation graph; benchmarks/RESULTS.md):

| Engine | Time |
|---|---:|
| 2066 → JavaScript, executed | 0.09 ms |
| 2066 → Python, executed | 1.08 ms |
| native JavaScript (V8) | 0.01 ms |
| native Python | 0.19 ms |
| 2066 interpreter (tree / plan-VM) | 4.7 / 17.7 ms |

The shipped artifact runs at effectively native speed: export erases
interpreter overhead. In-runtime engines are the development and
verification loop, not the deployment path. Full-stack serving with the
runtime resident (programs parsed and validated once, executed
in-process) sustains **0.9 ms per request** versus 18.6 ms for
process-per-request — a 21× improvement with identical verification
semantics.

The verification economics that motivate the design:

| Operation | Cost |
|---|---:|
| parse + validate, 2,000-node graph | 14 ms |
| regenerate both export backends after an engine change | 3.7 ms |
| full deterministic suite (394 tests) | ~30 s |

---

## 8. Honest Limitations

A white paper that hides its losses is marketing. Measured and admitted:

1. **Authoring cost.** The same calculator engine costs ~579 tokens in
   canonical 2066 versus ~65 in hand-written Python (~9×). The format
   optimizes for unambiguity and hashability, not compactness; the
   roadmap's Phase 2 may recover some of this. If raw generation speed
   is the only objective, write Python.
2. **No loops, no higher-order functions, no mutation.** Termination is
   guaranteed by construction; expressiveness is bounded accordingly.
   Lists exist as values, iteration does not.
3. **JavaScript export divergences.** i64 range semantics are not
   enforced (JS numbers are doubles; exact integers end at 2^53);
   string comparison is UTF-16 order. Python export is faithful.
4. **Any-disk keys are bearer objects.** PIN encryption protects at
   rest; whole-disk imaging plus offline brute-force of a weak PIN is
   outside the model. Real secure elements arrive at Phase 10.
5. **Unsigned grant files remain accepted in the development profile**
   (transition period); production and sovereign profiles refuse them
   unconditionally (`--profile production|sovereign`), and fuzzing
   proved the transition hole is real — which is why the profiles
   exist. Before any open deployment, unsigned acceptance is removed.
6. **Outbound network exists, transport does not.** Programs may call
   external services via `net.fetch` (hostname-allowlisted,
   host-supplied transport) — used live against a production API — but
   there is no message envelope, LAN/Tor, or multi-machine protocol
   yet (Appendix E remains unimplemented).
7. **Evidence chains detect tampering, not exfiltration** — an attacker
   who can delete the entire log destroys it (single-machine scope).
   Distributed anchoring is future work.
8. **Transport conformance is trusted, not verified** — the normative
   egress policy (spec/netpolicy.md) binds adapters, but the runtime
   cannot see inside a host transport; sovereign deployments use
   audited adapters.

(Closed since the last revision: symlink/TOCTOU filesystem escapes —
resolved-path authorization with handle-bounded reads; and unbounded
hostile resource consumption — execution budgets with the deterministic
E410.)

---

## 9. Economics and the Network Future

2066 is not a blockchain and launches no token (§6, §45). The economic
reasoning is sequential:

1. **Now (implemented):** the savings are verification economics —
   model churn costs a re-export and a test run, not a rewrite; one
   validated repair fixes every backend at once; capability walls bound
   the blast radius of any compromise, and evidence shows exactly what
   ran.
2. **Stage D (next):** an open contribution network where any agent
   proposes against public graphs; reputation accrues from *verified*
   accepted proposals and reproducible results (§40–§41), not from
   identity or popularity.
3. **Stage E (later):** internal **compute credits** — non-cashable
   (§47 enumerates the failure modes of premature tokens: speculation,
   farming, incentive attacks). Agents earn credits by contributing
   verified work and spend them on inference, storage, and tools
   through machine treasuries with capability-bounded spending
   (§48–§51). Payment rails are adapters, never a hardcoded chain.
4. **Stage F:** a Genesis event that hashes the constitution,
   specification, and runtime into a root-of-trust manifest under
   distributed authority — after, not before, the protocol has earned
   independence (§55–§62).

The design bet, stated falsifiably: *where Bitcoin spends energy to
manufacture trust, 2066 spends milliseconds of deterministic
verification to make trust unnecessary* — and the latter scales with
compute prices declining, not with them rising.

---

## 10. Current Status and Roadmap

Implemented and tested (394 deterministic tests; protocol 0.2;
runtime v1.4.1): canonical IR + hashing, dual execution engines plus a
differentially-proven second storage adapter, structured repair,
capability-gated filesystem, data, and outbound-network effects,
guarded writes (`when` — denied mutations are verified no-ops), agent
identity and signed grants, sessions, evidence chains, any-disk human
keys, multisig and delegation chains, multi-agent proposals with
deterministic merge, list values, Python/JS export, semantic packages
(`sales::business::add` addressing, `2066 inspect` context cards),
a browser-verified full-stack sales application deployed live on its
own VPS with TLS and cron, deployment profiles (development /
production / sovereign), SBOM + signed releases + reproducible wheel +
verified offline update bundles, property and fuzz suites over every
trust loader, a security/adversarial attack matrix, and the start of
an **independent Rust implementation** whose canonicalizer reproduces
every corpus hash byte-identically.

Queued, in order: complete the Rust runtime (validator, semantics,
capability verifier — the canonicalizer was the first strangler step);
FIDO2 human authority; transport independence (signed semantic
messages over LAN/offline bundles); termination-preserving iteration;
a WASI adapter at the capability boundary; the open contribution
network; compute credits; Genesis.

---

## 11. Conclusion

The question 2066 exists to answer: *how can arbitrarily capable
autonomous agents create, modify, execute, transact, and eventually act
in the physical world without humans blindly trusting them?*

The answer implemented here: make the **semantic program the asset** —
canonical, hashed, verifiable in milliseconds; make **authority** a
cryptographic object the model can request but never mint; make
**collaboration** a signed diff the runtime can merge or reject with
attribution; and make **evidence** tamper-evident by construction.
Models become replaceable components instead of load-bearing
trust anchors. Verification, not reputation, is the currency.

The AI may become infinitely capable. Under 2066, it never becomes
implicitly authorized.

---

*References in-repo: master roadmap (vision), `SPEC.md` + `spec/*`
(normative), `docs/` (human documentation), `docs/ai/` (machine
documentation), `benchmarks/RESULTS.md` (all measured claims),
`CONSTITUTION.md` (the ten laws), `THREAT_MODEL.md` (per-milestone
threat postures).*

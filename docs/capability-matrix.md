# Capability Matrix — what 2066 can and cannot do (v1.3.0, honest)

Compared against conventional languages (Python/JavaScript as the
baseline for "normal"), organized by what matters when an AI agent
builds software. No marketing: every "cannot" is a real current limit.
Fact-checked against the live runtime: **29 operations, 7 effect
classes, 43 error codes** (numbers from `runtime reference`, not from
this document).

## 1. Language core

| Capability | 2066 | Python/JS | Why |
|---|:---:|:---:|-----|
| Constants & literals (6 types) | ✅ | ✅ | bool, i64, f64, string, bytes, null |
| Arithmetic + comparison | ✅ | ✅ | total semantics: overflow/÷0 are structured errors, never UB |
| Explicit type conversion | ✅ | ✅ | `cast` only; no implicit coercion (by design) |
| Conditionals (value select) | ✅ | ✅ | `branch` — pure select, everything still evaluates |
| Functions with parameters/return | ✅ | ✅ | one return per function, positional binding |
| Multi-function programs | ✅ | ✅ | acyclic call graph (recursion rejected E212) |
| **Loops / iteration** | ❌ | ✅ | none — termination guaranteed by construction |
| **Recursion** | ❌ | ✅ | rejected E212 (same guarantee) |
| **Variables / mutable state** | ❌ | ✅ | dataflow-only: nodes bind values |
| **Exceptions inside programs** | ❌ | ✅ | errors are runtime-level structured records, not catchable |
| String building | ⚠️ | ✅ | `concat` + `list.join` only; no interpolation, no methods (upper/split/replace) |
| Collections | ⚠️ | ✅ | lists from `data.list` only; `length`/`get`/`join`; no map/filter/reduce, no dicts |
| Randomness | ❌ | ✅ | no random op — programs are deterministic |
| Clock / time inside program | ❌ | ✅ | time exists only in the authority layer (`--now` freezes it) |
| Modules / imports between .ai files | ❌ | ✅ | one file = one program; schema duplication is manual today |
| User-defined types (beyond entities) | ❌ | ✅ | entities are DB tables, not in-memory types |
| Null-safety | ✅ | ⚠️ | null only via `data.select` defaults; no null-propagating bug class |

## 2. I/O and effects

| Capability | 2066 | Notes |
|---|:---:|-------|
| stdout print (batch) | ✅ | `emit` — ordered by node id |
| stdout print (immediate) | ✅ | `system.write` — interactive prompts |
| stdin read | ✅ | `system.read` — line-based, EOF-safe |
| Read/write files | ✅ | capability-gated, scope-matched, size-limited, pre-write checks |
| SQLite database (CRUD + list) | ✅ | `data.*` — runtime-written parameterized SQL; injection-inert |
| Schema migrations | ✅ | additive auto-applied; destructive refused with data-loss report |
| HTTP client (outbound GET) | ✅ | `net.fetch` — hostname-allowlisted by `net.request` grants; transport host-supplied; E560 on failure |
| HTTP server | ⚠️ | shell provides it; programs expose pure/auth logic |
| Spawn processes / shell | ❌ | forbidden (§20) — and there is no op to do it |
| Env variables / secrets in program | ❌ | forbidden — authority enters via grants only |

## 3. Trust & authority (where 2066 is unique)

| Capability | 2066 | Conventional |
|---|:---:|---|
| Program identity (content hash) | ✅ `runtime hash` | ❌ (needs extra tooling; formatting changes it) |
| Validated-before-run with structured errors | ✅ | ❌ (runtime exceptions after deploy) |
| Machine-usable repair hints | ✅ E203 + `allowed_repairs` | ❌ |
| Capability-scoped effects | ✅ | ⚠️ (OS perms only; in-process code is all-powerful) |
| Default deny without grants | ✅ | ❌ (code runs with the user's full rights) |
| Delegations signed by human key disk | ✅ | ⚠️ (possible with effort; not language-level) |
| Per-delegation program-hash binding | ✅ | ❌ |
| Token revocation list (chained, tamper-checked) | ✅ | ⚠️ (session stores exist, not hash-chained) |
| Multisig (m-of-n) approvals | ⚠️ library | ⚠️ (GNUPG-style, not language-level) |
| Tamper-evident audit of every DB write | ✅ | ❌ (needs external SIEM) |
| **Agents minting their own authority** | ❌ structurally impossible | ❌ also impossible — parity, but here it's by instruction-set |

## 4. Agent workflow economics (measured)

| Metric | 2066 | Conventional prompt |
|---|---|---|
| Revision cycle cost (validate+effects+hash) | **1 spawn, ~80 ms** (`check`) | N/A — trust is manual review |
| Engine change → both backends regenerated | 3.7 ms | rewrite both by hand |
| Full verification suite | 394 tests, ~30 s | manual QA per artifact |
| Context to modify a unit safely | **~2.2 KB** (`2066 context` card + unit) vs ~21 KB file-reading — **9.5× less** (measured, benchmarks/context_efficiency.py) | read files until it feels safe |
| Second implementation agreeing on identity | ✅ Rust canonicalizer, 28/28 corpus hashes identical | n/a — one implementation is the truth |
| Structured first-draft errors | ✅ code/node/expected/received/repairs | stack traces or silent bugs |
| Determinism (same input → same output) | ✅ byte-identical | usually, but error paths differ |
| Engine authoring token cost | ~9× higher on this benchmark | 1× |
| Expressiveness ceiling | low (no loops/state) | full language |

## 5. Verified live (evidence, not claims)

| Demo | Status |
|---|✅/❌|
| Hello world → direct execution, no generated code | ✅ |
| Interactive calculator (stdin/stdout, guarded ÷0) | ✅ |
| Styled HTML page written via capability-gated FS | ✅ |
| Calculator engine compiled to JS, running in browser | ✅ |
| Two-agent proposal merge + conflict rejection (§83) | ✅ |
| Full-stack notes app: register/login/CRUD + ownership | ✅ |
| SQL injection payloads inert | ✅ tested |
| Read-grant cannot delete (§24) | ✅ tested |
| Logout actually revokes server-side | ✅ tested |
| Standalone binary (`bin/2066.exe`, no host toolchain) | ✅ Windows |

## 6. Cannot do — the honest list

1. **Anything iterative** — no loops; batch = one-shot or shell-driven repetition.
2. **Anything stateful in-memory** — state lives in SQLite/memory adapters or the session layer.
3. **Arbitrary networking from inside a program** — outbound GET to
   *allowlisted* hosts only (`net.fetch`); no listeners, no arbitrary
   protocols. Servers are shells; programs decide, hosts transmit.
4. **Anything with rich text/data manipulation** — no split/regex/format strings beyond canonical rendering.
5. **Anything requiring speed in-runtime** — use the exported artifacts for hot paths (0.09 ms vs 4.7 ms on 10k ops).
6. **Anything requiring a human to be trusted** — the human is the *root*, but the runtime verifies even human-signed files for scope/expiry/limits.
7. **Transport/network distribution of programs** — proposals and evidence are local/signed artifacts; the multi-machine transport layer (Appendix E) is unbuilt. Offline *bundles* exist (signed, hash-verified) — a network does not.

## Bottom line

2066 today is a **verified computation + authority core with release
engineering**: it excels at deterministic, auditable,
permission-bounded logic — calculators, rules engines, auth flows, data
validation, DB transactions, allowlisted egress — and it ships with the
sovereign kit (SBOM, signed releases, reproducible wheel, offline
bundles). It cannot yet express general-purpose software (loops, rich
collections, listeners, text processing), and its authoring cost is ~9×
a conventional language by tokens. Those are the boundaries the roadmap
attacks next: the Rust second runtime, iteration design, the transport
layer, and richer collections — in that order, because each unlocks the
next.

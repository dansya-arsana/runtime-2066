# ROADMAP.md — 2066 Implementation Status

Master plan: [docs/master_roadmap_v0.2.md](docs/master_roadmap_v0.2.md)
This file tracks engineering progress against it. Updated: 2026-08-31 (Stages A–D complete).

## Milestone checklist

### M0 — Hello world / first proof of concept (§12, §14, §78, §80) — ✅ DONE

- [x] Canonical `.ai` text representation (§7): node blocks, stable digit ids
- [x] V0 pure core (§11): `const copy add subtract multiply divide compare branch emit`
- [x] Primitive types (§11): `bool i64 f64 string bytes null`
- [x] Parser → semantic graph → validator → interpreter → result (§10)
- [x] Direct execution — no JS/Python/Rust/shell generated (§12 success condition)
- [x] Structured error protocol with `expected`/`received`/`allowed_repairs` (§13)
- [x] Deterministic execution + deterministic errors, byte-for-byte (§80)
- [x] `examples/hello.ai` → `Hello, World!`; `examples/arithmetic.ai` → `50` (§12)

### M1 — Complete V0 + repair loop (§13, §80, §81) — ✅ DONE

- [x] `call` / `param` / `return`: named subgraphs, positional binding,
      acyclic call graph (recursion rejected E212), scope placement rules
- [x] `cast` operation: i64⇄f64, string→number (E304), number/bool→string,
      f64→i64 representability (E303); the executable form of §13 repairs
- [x] Basic repair loop: `python -m runtime repair` mechanically applies
      `cast` repairs (insert node + rewire), re-validates, emits the
      canonical repaired program
- [x] Canonical serializer (fixed field order, re-canonicalized literals,
      idempotent round-trip) — seed of Phase 2 canonical IR
- [x] Demo 1 (§81): `(100 * 1.05)^10` via explicit multiply chain
      (`examples/compound_interest.ai`), deliberate `multiply i64 string`
      error injection (`examples/compound_interest_error.ai`), repair →
      identical result
- [x] 81 deterministic tests green (was 43 at M0)

### M2 — Canonical IR + bootstrap comparison (§15, §102) — ✅ DONE

- [x] Deterministic program hashing: canonical form + SHA-256 identity
      (`python -m runtime hash`); insensitive to comments, whitespace,
      field order, and declaration order — source text is a view
- [x] Canonical serialization promoted to primary artifact: nodes sorted by
      id, functions by name; idempotent round-trip
- [x] §102 comparison recorded (`research/bootstrap_comparison.md`):
      A custom interpreter (implemented), A′ compiled-plan stack VM
      (implemented this milestone), B WASI executor (deferred — revisit at
      Phase 4–5 capability boundary), C existing semantic-runtime adapter
      (deferred — revisit when external tooling consumes the hash/plan)
- [x] Appendix F.3 proven: same canonical program → equivalent results AND
      equivalent structured errors through both adapters
      (`tests/runtime/test_adapters.py` corpus; `--adapter tree|plan`)
- [x] Shared operation semantics extracted (`runtime/ops.py`) so adapter
      equivalence holds by construction, not just by test
- [x] 98 deterministic tests green (was 81 at M1)

### M3 — Effects + capability runtime (Phase 3–5, demo §82) — ✅ DONE

- [x] Effect taxonomy per operation (Appendix C.2): PURE / SYSTEM /
      FILESYSTEM_READ / FILESYSTEM_WRITE; static manifest via
      `python -m runtime effects` (call nodes inherit callee effects)
- [x] Effectful ops: `filesystem.read` (→ string), `filesystem.write`
      (→ bytes-written i64), shared by both adapters via runtime/fsops.py
- [x] Capability objects (§18): action, resource scope, id, expires,
      max_bytes; runtime-held grants loaded from JSON (`--caps`)
- [x] Enforcement (§17, §20): component-wise scope matching (grant on
      `/incoming` covers `/incoming/a.txt`, not `/incoming.txt` nor `/etc`),
      default deny with zero grants, write limits checked before any byte
      hits disk, path normalization defeats `..` escapes
- [x] Denials as structured errors: E401 no grant / E402 expired / E403
      over-limit / E305 io error, exit code 4; `--now` freezes the
      authority clock for deterministic capability tests
- [x] §82 demo beats proven: scoped read allowed; escape to `examples/README.md`
      denied with the real normalized path in the error; no mint/widen
      operations exist in the instruction set
- [x] 132 deterministic tests green (was 98 at M2)

### M4a — Agent identity + signed grants (Phase 7, §26–§28 groundwork) — ✅ DONE

- [x] Appendix G research spike: `cryptography` 50.0.1 (Apache-2.0/BSD-3)
      already present → adopted for ed25519; hand-rolled crypto rejected;
      recorded as the project's first third-party dependency
- [x] Identity ABI (§64 crypto agility): algorithm-tagged identity/secret
      files, `keygen` CLI, deterministic ed25519 signatures over canonical
      JSON
- [x] Signed grant envelopes: signature covers scopes, limits, expiry,
      issuer, and `issued_at`; verification is fail-closed at load
- [x] CLI: `keygen` / `sign-caps` / `verify-caps`; `--caps` auto-verifies;
      `--require-signed` refuses unsigned files; double-signing refused
- [x] Tamper tests: payload widening, timestamp edits, issuer swaps, key
      corruption — all refused; ed25519 determinism asserted
- [x] 153 deterministic tests green (was 132 at M3)

### M4c — Stress test: real applications + export backend — ✅ DONE

Stress objective: prove the language can build something beyond hello world,
produce non-text output (HTML+CSS), and run through a conventional-language
toolchain.

- [x] New ops: `system.read` / `system.write` (implicit-grant stdio; the
      interactive channels) and `concat` (Phase 3 `string.concat`) — wired
      through both adapters
- [x] Output-channel rule generalized: main needs `emit` **or**
      `system.write` (E206)
- [x] Cast usability fix from real testing: string→f64 accepts canonical
      integer input (`"12"` → `12.0`); program literals stay stricter
- [x] **Calculator app** (`examples/calculator.ai`, 45 nodes): interactive
      prompts, operator dispatch via compare/branch select-tree (no
      if-statements exist), guarded division, invalid-operator rejection —
      verified on both adapters
- [x] **Styled HTML generation** (`examples/calculator_page.ai`): computes
      in the graph, assembles a CSS-styled page via concat chains, writes it
      through the capability-gated `filesystem.write` (browser-ready)
- [x] **Export backend** (§10/§4.10): `python -m runtime export --target
      python` lowers the plan to standalone Python with a
      semantics-preserving preamble (E301/E302/E303/E304, canonical
      rendering); deterministic output, canonical hash in the header;
      FILESYSTEM_* effects refused (exported code is outside the authority
      plane — boundary kept honest)
- [x] **Export parity proven**: calculator run via runtime vs exported
      Python — byte-identical stdout across all input cases
- [x] **Stress**: generated 2,001-node graph through parse → validate →
      both adapters → export → standalone execution: parse+validate 0.014s,
      tree 0.001s, plan 0.004s, export 0.006s
- [x] 155 deterministic tests green (was 153)

### M4d — Real calculator app: 2066-compiled engine + proper UI/UX — ✅ DONE

- [x] JavaScript export target (§10/§4.10): f64-native (JS numbers are IEEE
      doubles — float semantics map natively); `--library` mode emits a
      `globalThis.Calc2066` binding and omits main; documented divergences
      (no i64 range enforcement, UTF-16 string order, no bytes)
- [x] `examples/calculator_app/engine.ai`: the calculation core as a
      semantic library — guarded division, unknown-operator rejection,
      canonical display strings, built-in self-test main
- [x] `engine.js`: generated, hash-stamped artifact; a test proves the
      committed artifact matches what the current `engine.ai` compiles to
- [x] Full UI/UX shell: dark-theme display with expression line, key grid,
      chained operations, keyboard input, pending-operator highlight,
      error states, aria-live/focus-visible accessibility, responsive
- [x] Verified in a real browser via a browser driver: clicks → 12+3.5=15.5,
      chained 15.5×2=31, division-by-zero error state, keyboard 10/4=2.5
- [x] Verified under node: all six engine cases (all four operators +
      both error paths) through the exported JavaScript
- [x] 177 deterministic tests green (was 155)

### M5 — Full-stack: semantic data runtime + auth (§22–§24) — ✅ DONE

- [x] Entity declarations (§22 grammar): `entity user { ... }` — grammar-
      checked identifiers/types compiled by the runtime to SQLite; the AI
      never writes SQL
- [x] Data ops: `data.insert / count / select / update / delete` — scalar
      in/out, fully parameterized (`?` bindings), per-entity capabilities
      (`data.read` / `data.write` / `data.delete` as separate actions)
- [x] `crypto.digest` (sha256) — password hashing for the auth demo
- [x] §24 beat proven: a `data.read:note` grant CANNOT delete; per-entity
      scoping (user grant ≠ note grant); SQL injection stored as inert
      data with the table intact; default deny without `--db`
- [x] Identity-column protection (E503), unknown entity/column (E501/E502),
      sqlite errors (E505), schema-only programs legal (E206 relaxation)
- [x] **Full-stack demo** (`examples/notes_app/`): register / login /
      add note / read note with ownership enforcement — all logic in four
      .ai programs executed by the runtime (SQLite + signed-capable
      grants); server is a logic-free HTTP↔stdin shell; browser-verified
      end-to-end via a browser driver (register bob → note → carol denied
      ownership → wrong password rejected)
- [x] Thesis codified: docs/philosophy.md §"Breaking the revise–pentest–
      burn loop" — the semantic program persists across model churn;
      migration = re-export + re-verify in seconds
- [x] 210 deterministic tests green (was 177)

### M6 — Production-grade full-stack (sessions, persistence, migrations, evidence) — ✅ DONE

- [x] **Session capabilities** (§4.6, §18): ed25519-signed expiring tokens
      minted by the trusted host; `session.verify` op (IDENTITY effect,
      E406 forged / E407 expired) executes in both adapters; programs
      structurally cannot mint tokens — the notes app no longer trusts a
      client-claimed user id
- [x] **Persistent runtime**: the notes server parses/validates each
      engine program once at startup and executes the cached analysis
      in-process with stdio capture — **0.9 ms/request vs 18.6 ms
      subprocess-per-request (~21×)**, identical verification semantics
- [x] **Schema migrations** (§25): `python -m runtime migrate --db` diffs
      program entities against the database; additive changes apply
      (CREATE/ADD COLUMN, rows preserved); destructive changes (drop/
      type-change) are reported with data-loss detail and REFUSED —
      destructive migration is a human decision, never an agent's
- [x] **Evidence protocol** (Appendix C.5): `--evidence log.jsonl` —
      every data write appends a hash-chained record (action, resource,
      subject, canonical program hash, timestamp, prev-hash link);
      `python -m runtime evidence <log>` verifies the chain — edits,
      deletions, and reordering are all detected (tests prove each)
- [x] Browser end-to-end re-verified: register mints token → token-gated
      add/read; empty and forged tokens denied E406 in-browser
- [x] 233 deterministic tests green (was 193)

### M7 — Multi-agent collaboration (§29–§30, C.4, demo §83) — ✅ DONE

- [x] **Signed proposals**: `python -m runtime propose new.ai --base base.ai
      --agent id.json --key secret.key` — node-level diff (added/changed/
      removed units) against the base's canonical hash, ed25519-signed
- [x] **Fail-closed verification** (`verify-proposal`): signature (E602),
      base-hash match — "the graph moved; re-propose" (E601), malformed
      shape (E604); an impostor claiming another agent's id fails
- [x] **Deterministic merge** (`merge --proposals a.json,b.json`):
      disjoint changes auto-merge and the reconstruction must re-validate
      (an invalid merge is rejected with a report, never half-applied);
      identical duplicate changes dedupe; same-unit different-content
      conflicts are rejected naming the unit and BOTH agents (exit 1)
- [x] **§83 demo** (`examples/proposals/`): agent-A adds `negate`,
      agent-B adds `double` to the same engine → merged program valid,
      all three functions, runs; agent-C's conflicting `negate` → rejected
      with `func/negate/202` attribution
- [x] 14 proposal tests + live demo verification

### M8 — Collections: list values — ✅ DONE

- [x] `list<T>` as a first-class value type (from `data.list`; canonical
      newline-joined rendering; no list literals — lists come from data)
- [x] `data.list` (DATA_READ, `data.read` cap): all matching rows' column
      values in id order — the runtime still writes all SQL
- [x] `list.length` / `list.get` (E308 out of range) / `list.join` —
      PURE ops; no iteration construct (termination preserved)
- [x] Both adapters (a real pre-existing plan-VM insert bug — reversed
      args + stack leak — was found and fixed by the new tests)
- [x] Exporters: pure list ops emit native array expressions;
      `data.list` refused like all capability-gated effects
- [x] Notes app: `list_notes.ai` + "List my notes" — browser-verified
      (gina → `1. alpha / 2. beta`), forged tokens denied E406
- [x] 11 list tests (semantics, empty lists, injection inertness via
      where-values, type rules, caps, export refusal)

### M10 — Security hardening (S4/S9 hardening pass) — ✅ DONE

- [x] Trust-store pinning: grant issuers must be pinned keys; unpinned
      issuers refused even with valid signatures (closes self-signed hole)
- [x] Real logout: minted session token_ids registered per subject;
      `--logout-user` revokes all outstanding sessions of a user
- [x] Runtime self-hash (S9): `python -m runtime digest` — deterministic
      digest of the runtime package, publishable and re-verifiable
- [x] Program-format versioning: `format-version 1` header accepted,
      mismatched versions refused (E109); canonical output carries it
- [x] Multisig approvals (Phase 11 prep): m-of-n signed envelopes,
      distinct-key counting, untrusted-key ignoring

### M9 — Any-disk human keys + §84 in software (§31–§33 prep) — ✅ DONE

Direction: software first; hardware *preparation* — any removable disk,
including an old flashdisk, becomes the physical approval object.

- [x] **KEY v1 format** (`runtime/keydisk.py`, spec/hardware-key.md):
      non-destructive `.2066key/` on any disk — PIN-encrypted ed25519
      (HKDF→AES-256-GCM), public identity, plain KEYFORMAT marker,
      wrong-PIN counter with 8-strike self-destruct; danger-path refusal
      (system drive, home, missing paths)
- [x] CLI: `key-format` / `key-inspect` / `approve` — the human approves
      grant files as delegations (`issued_by: human-…`) with optional
      `--ttl-minutes`
- [x] **§84 demo, all four beats in software**: denied (E401) → key-disk
      approval (5-min TTL) → allowed (`--require-signed`) → expired
      (E402); tampered approvals refused by signature
- [x] Honest threat model in the spec: bearer object, best-effort attempt
      limiting, same-envelope upgrade path to real secure elements
      (Phase 10) — callers never change
- [x] 268 deterministic tests green (was 254)

### M11 - MCP server (open integration) - DONE

- [x] MCP stdio server: JSON-RPC 2.0 over stdin/stdout; initialize,
      tools/list, tools/call, ping, notifications
- [x] 6 tools from 5 .ai programs: calculate, notes register/login/add/
      get/list - compiled once at startup, executed in-process per call
- [x] Structured errors surfaced as MCP error results (isError: true);
      guarded division returns readable messages, never crashes
- [x] 13 protocol tests green (handshake, tool calls, guarded division,
      structured errors, unknown method/tool, clean EOF shutdown)

### Next frontiers (post-M9, software-first)

- Network/transport layer (Appendix E): signed semantic messages over
  LAN / offline bundles — same message, different transport
- Multisig grants (Phase 11): m-of-n key disks to approve widening
  (GrantSet extension, machinery exists)
- Iteration/loops as bounded graph constructs (termination-preserving)
- WASI adapter spike at the Phase-4 capability boundary trigger

### Later stages

Data runtime (Phase 6–7) → identity (Phase 7–8) → collaboration (Phase 8–9)
→ hardware delegation (Phase 10+) — per the master roadmap; nothing else
starts before its stage (§77 development priority rule, §102 "do not build
Genesis/wallets/robots/blockchain first").

### M12 — VPS deployment + public-readiness battle test (2026-08-31) — ✅ DONE

- [x] GitHub: dansya-arsana/runtime-2066 (public, tag v1.4.0), secrets
      hardened out via .gitignore/.dockerignore (no *.key/*.db ever)
- [x] Full suite green on clean Linux containers (Ubuntu 24.04, Docker
      29, Python 3.12) — node-dependent JS tests now skip cleanly
- [x] Cross-machine canonical hashes identical (Win/Py3.14 == Ubuntu/Py3.12)
- [x] Notes app live: 43.129.49.56:8618 (Docker, restart unless-stopped,
      volumes 2066-keys + 2066-data) — data, signing key, and session
      tokens survive restarts AND image replacement
- [x] FIX (live-found): MCP session tools dead (no verifier/mint) —
      rebuilt on engine-verifies/shell-mints split, key in ~/.2066/mcp
- [x] FIX (live-found): engine stdin race under parallel load
      (5/12 E406 -> 12/12 ok); SessionRegistry RMW lock; SQLite WAL +
      busy_timeout
- [x] MCP battery: 27 checks (protocol edges, garbage JSON, isolated-db
      full auth flow, forged-token fail-closed)
- [x] Remote MCP session demo: PC agent -> ssh -> VPS stdio MCP
      (examples/mcp/remote_session.py)
- [x] Standalone battery on VPS: benchmarks/standalone.py — 200x
      dual-adapter replay deterministic, check cycle 0.5ms/2000 per sec
      at 0 LLM tokens, 300 fuzzer mutants 0 unhandled crashes

### M13 — Sales app: the real-app test + `when` guard (2026-08-31) — ✅ DONE

- [x] Studied the real sales-machine (live OpenAPI: 75 endpoints, 23
      modules) and rebuilt the core pipeline on 2066: businesses with
      deterministic in-graph scoring, opportunity pipeline with the
      stage state machine IN-GRAPH, activities, follow-ups, funnel.
- [x] LANGUAGE FIX found by the app: `branch` is eager — denied writes
      in untaken arms still executed. Added `when <node-ref>` guarded
      effects to data.insert/update/delete; false guard = verified
      no-op in BOTH adapters; guard refs ordered + type-checked.
      (tests/runtime/test_when_guard.py)
- [x] StructuredError.__str__ renders code+detail (was empty in traces).
- [x] examples/sales_app/: 15 programs, server shell, dashboard UI,
      discover_osm.py (Overpass -> verified engines).
- [x] 338 tests green; deployed https://dev-2066sales.arsana.cloud
      (loopback :8628, TLS edge, volumes); OSM discovery fed 5 real
      Bandung cafes through the live pipeline.

### H — High-assurance hardening cycle (plan §85–§89, 2026-08-31)

- [x] H0 snapshot: tag `prototype-v1.1-snapshot`; 17 sales program
      hashes recorded pre-move, byte-identical post-move (proof in
      session log); conformance corpus frozen (28 programs)
- [x] H1 repository cleanup: `programs/sales/*` semantic package,
      `policies/deployment/` grants, `apps/sales/` shell; root stays
      boring (BOUNDARIES.md)
- [x] H2 architecture boundaries: layer map + import-analysis tests;
      core verified free of storage/network/process imports; inward-only
      dependency rule enforced by suite
- [x] H3 semantic packages: manifests, `package::module::unit`,
      `2066 list`, `2066 inspect` (context card per §16); spec/packages.md
- [x] H4 production profile: `--profile production` ⇒ unsigned grants
      always rejected (tested)
- [x] Docs: SECURITY.md, CHANGELOG.md, DEPENDENCIES index (§25 fields)
- [ ] H5 finish notes_app migration to a package (next cycle)
- [x] H6 testing expansion: property suite (idempotence, hash-stability,
      sign/verify, no-widening) + fuzz campaign over grants/envelopes/
      proposals/evidence/manifests (980+ mutants classified; found and
      fixed verify_evidence crash; pinned the unsigned-transition hole)
- [x] H7 release engineering: `2066 sbom` (SPDX 2.3, deterministic),
      `2066 release`/`verify-release` (signed file-by-file tree proof),
      `2066 backup`/`restore` (§60 fail-closed bundles), wheel verified
      REPRODUCIBLE with pinned SOURCE_DATE_EPOCH
      (tools/release/REPRODUCIBILITY.md)
- [x] §29 protocol version 0.2 separated from runtime version
- [ ] H8 Rust core; H9 FIDO2 — sequenced per plan §93–§94

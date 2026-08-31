# Changelog

## [unreleased] — external-review fixes: host hardening + doc truth

Security-relevant fixes from an independent review (adopted as the
P-sequence in ROADMAP.md):

- **P1 filesystem boundary closed**: authorization now covers the
  symlink-RESOLVED path; opens act on the resolved target with
  O_NOFOLLOW (where available); non-regular objects refused; read size
  limits enforced as bounded reads ON THE OPEN HANDLE — the
  check-then-open TOCTOU and symlink-escape classes are gone
  (tests/security/test_fs_boundaries.py, 5 cases incl. escape-deny and
  in-scope-alias-works).
- **P2 execution budgets**: ExecutionBudget (max_nodes/steps/
  literal_bytes/list_items/call_depth/io_bytes/rows) enforced at
  identical semantic points in BOTH adapters; exhaustion is the
  canonical deterministic E410 (same program+budget -> identical
  refusal, cross-adapter — proven in tests/runtime/test_budget.py).
  Termination was never bounded resource consumption; now it is.
- **Net egress policy (normative)**: spec/netpolicy.md defines
  transport-adapter duties (resolve-once, forbidden address classes,
  redirect refusal, IDN normalization, response caps, TLS policy);
  runtime/netpolicy.py is the reference enforcement and now guards the
  live sales app + cron transports (DNS-rebinding-to-localhost,
  metadata endpoints, redirect chains, response bombs: all refused
  pre-connection where possible — 6 tests).
- **P0 doc truth**: SPEC.md no longer contradicts the exporters
  ("execution never requires translation; exports are non-canonical
  artifacts outside the authority plane") + a normative three-class
  backend table (conformant executor / compatibility export /
  accelerator). THREAT_MODEL.md rebuilt versioned (Protocol 0.2 /
  Runtime 1.4.1) as CURRENT guarantees/boundaries/surfaces/gaps +
  closed-history + out-of-scope; the M3/M4 model is archived verbatim
  in docs/security/history/.
- E410 documented everywhere the error namespace lives (airef, manual,
  reference.json, spec/errors.md).

## [previous] whole-plan pass: H8 seed + remaining sections

### The headline
- **Independent Rust canonicalizer (H8/SS36 step 3)**: zero-dependency
  Rust implementation of canonical serialization + SHA-256 (incl. a
  hand-rolled FIPS 180-4 SHA-256), written from spec/canonicalization.md
  sharing no code with Python. **All 28 frozen-corpus programs hash
  byte-identically across the two independent implementations**
  (tests/independent/ — runs whenever cargo is present). 2066 now has
  protocol-level proof, not just a codebase.

### Added
- SS30: programs may declare `protocol 0.2`; newer/older runtimes
  refuse instead of misreading (E109).
- SS14/SS7: in-memory storage adapter (runtime/memory_store.py) +
  differential test proving SQLite/memory interchangeable on the sales
  flow — adapter independence is a tested property.
- SS13/SS42: runtime/ports.py — DataStore/Transport/Clock/
  HumanAuthority contracts (Python Protocols).
- SS21: `--profile sovereign` (offline posture; signed grants
  mandatory) + docs/operations/DEPLOYMENT_PROFILES.md (A/B/C + SS43
  key separation).
- SS24: offline update bundles — `2066 bundle` / `verify-bundle` /
  `install-bundle` (verify signature -> verify hashes -> install ->
  evidence record); tampering refuses with zero files installed.
- SS16: `2066 context <unit>` (machine-shaped inspect).
- SS34: tests/security (9-attack authority matrix incl. SQL injection,
  path traversal, replay, impersonation, egress boundary) and
  tests/adversarial (hostile .ai programs: escalation, guard bypass,
  identity forgery).
- SS81: six ADRs; SS6: docs/security/TCB.md; SS31: spec/{ir,
  canonicalization,effects,capabilities,proposals,evidence}.md;
  SS61-65: DISASTER_RECOVERY + AUDIT docs; SS33: error namespace
  policy; SS47: resource identity rule in spec/packages.md.
- SS70: benchmarks/context_efficiency.py — semantic context is 9.5x
  smaller than file-reading for the same task (measured).

### Fixed
- session.verify: forged tokens crashed with UnboundLocalError
  (function-local `import json` shadowed the except clause) — found by
  the adversarial suite; now a clean E406. 

### Earlier in this cycle


### Added
- **Property tests (H6/§34)**: canonicalization idempotence and
  hash-stability across formatting, sign→verify round-trips with
  mutation always failing, grants-cannot-widen (E401 for ungranted
  actions), package identity independence across the whole sales
  package, protocol/runtime version separation.
- **Fuzz campaign (H6/§34)**: deterministic mutation fuzzing over the
  grant loader, signed envelopes, proposals, evidence chains, and
  package manifests — 980+ mutants, all classified into the allowed
  structured failure set.
- **FIX (found by fuzz)**: `verify_evidence` crashed with
  JSONDecodeError on a corrupted event line; it now REPORTS the
  corruption (`ok: false, reason: event is not valid JSON`).
- **PINNED (found by fuzz)**: destroying an envelope's signature turns
  it into an unsigned envelope — accepted by the development default,
  refused by `--profile production`. Documented transition hole, now a
  named test.
- **Backup/restore (§60)**: `2066 backup` / `2066 restore` —
  hash-verified bundles, fail-closed restore (any mismatch copies
  nothing), secret-bearing files excluded by default and their presence
  in a bundle is itself a verification failure.
- **SBOM (§26)**: `2066 sbom` — SPDX 2.3 JSON, deterministic under a
  fixed clock, package verification code over the runtime tree.
- **Signed releases (§28)**: `2066 release --out --agent --key` hashes
  runtime + spec + conformance corpus and signs (ed25519 envelope);
  `2066 verify-release` proves the running tree matches the signed
  release file-by-file, and refuses other signers.
- **Reproducible builds (§27)**: wheel verified byte-identical across
  rebuilds with pinned SOURCE_DATE_EPOCH — procedure + measured hash in
  tools/release/REPRODUCIBILITY.md.
- **Protocol version (§29)**: `PROTOCOL_VERSION = "0.2"` distinct from
  the runtime version; exposed in the AI reference.

### Earlier in this cycle


### Added
- **Semantic packages (H3)**: `package::module::unit` addressing,
  `package.ai` manifests, `runtime/packages.py`, `2066 list`,
  `2066 inspect` (full semantic context card: hash, nodes, inputs,
  outputs, effects, capabilities, dependencies) — agents no longer
  browse the filesystem to understand programs.
- **Production profile (H4)**: `--profile production` makes unsigned
  grants always rejected (fail closed); development stays the default.
- **Conformance corpus**: `protocol/conformance/corpus.json` freezes
  28 program hashes; suite fails on drift or unlisted programs.
- **Architecture boundaries**: layer map + import-analysis test
  (`tests/architecture/`); core proven free of storage/network/process
  imports; bundle-sync test for wheel-bundled programs.
- SECURITY.md, CHANGELOG.md, spec/packages.md,
  docs/architecture/BOUNDARIES.md.

### Changed
- Repository layout: sales application → `programs/sales/` (semantic
  package), grants → `policies/deployment/`, app shell → `apps/sales/`.
  **All 17 canonical hashes proven identical across the move** (H1).
- `examples/notes_app` remains a demo app (documented exception).

### Fixed
- (prior cycle) `when`-guarded effects, engine stdin race, MCP session
  layer, WAL/busy-timeout — see git log.

### Baseline
- Tag `prototype-v1.1-snapshot` = reference oracle for this cycle.

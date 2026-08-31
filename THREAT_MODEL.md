# THREAT_MODEL.md — Protocol 0.2 / Runtime 1.4.1

> Versioned with the protocol (plan SS80). A security reviewer must
> never wonder whether a statement here is stale: everything is CURRENT
> as of this header. Historical milestone-scoped models live in
> [docs/security/history/](docs/security/history/).
>
> Basis: 412 deterministic tests, the fuzz/property campaigns, the
> security/adversarial suites, and the independent Rust canonicalizer.

## CURRENT GUARANTEES

1. **Semantics**: a program means exactly its validated graph; same
   program + same runtime ⇒ byte-identical results and errors, in both
   execution adapters, and canonical identity reproduces across the
   independent Rust implementation (28/28 corpus).
2. **Authority is capability-only, default-deny**: every effectful op
   (filesystem read/write, data read/write/delete, net.fetch, session
   verify) requires an explicit, unexpired, unrevoked, scope-matched
   grant. No ambient authority, no catch-all scopes, no shell/eval ops
   exist (ADR-002/003).
3. **Filesystem boundary (hardened this cycle)**: authorization covers
   the symlink-RESOLVED target; the open acts on the resolved path with
   O_NOFOLLOW where available; non-regular objects are refused; read
   size limits are enforced on the open handle (bounded read) — the
   check-then-open TOCTOU class is closed
   (tests/security/test_fs_boundaries.py).
4. **Resource authority (new this cycle)**: execution budgets (nodes,
   steps, literal bytes, list items, call depth, io bytes, rows) are
   part of authority with the canonical deterministic **E410**;
   termination-by-construction plus budgets bounds hostile input
   (tests/runtime/test_budget.py).
5. **Network egress**: hostname-allowlisted by `net.request` grants,
   host-supplied transport (runtime owns no sockets); the reference
   transport refuses forbidden address classes, redirects, and
   oversized responses (spec/netpolicy.md,
   tests/security/test_netpolicy.py). Fetched bodies count against the
   io budget.
6. **Evidence**: hash-chained, tamper-evident by verification
   (`2066 evidence`), metadata not payloads; bundle installs are
   recorded events.
7. **Integrity of distribution**: signed release manifests (file-by-file
   tree proof), SPDX SBOM, byte-reproducible wheel, verify-then-install
   offline bundles.
8. **Identity**: ed25519 agent identities; programs verify session
   tokens but structurally cannot mint them; multisig m-of-n and
   narrowing-only delegation chains; issuer pinning.

## CURRENT TRUST BOUNDARIES

- **Untrusted**: every `.ai` program, every grant file's *content*
  (verified, never trusted), every transport response, every bundle
  until signature+hashes verify.
- **Trusted code**: the TCB (docs/security/TCB.md) — enforced by
  import-analysis to import no storage/network/process machinery in the
  core.
- **Trusted humans**: grant issuers and key holders — the root of
  authority, bounded by scope/expiry/multisig, never by trust in a
  model.
- **Host trust**: hosts supply transports, clocks, storage; a malicious
  host can lie to the runtime (out of scope below).

## CURRENT ATTACK SURFACES

| Surface | Enforced by |
|---|---|
| malformed programs (parse/validate) | grammar + typed structured errors; fuzzed |
| authority escalation / scope escape | capability checks at every effect; adversarial + security suites |
| filesystem symlink/TOCTOU | resolved-path authorization, O_NOFOLLOW opens, handle-bounded reads |
| resource exhaustion (graph size, literals, lists, io) | execution budgets, E410 (deterministic) |
| DNS rebinding / redirect abuse / metadata endpoints / response bombs | netpolicy transport duties + io budget |
| grant/envelope/proposal/evidence tampering | signed envelopes, hash chains; 980+ mutant fuzz campaign |
| session forgery/replay | signed expiring tokens, revocation lists (E406/E407) |
| supply chain | signed releases, SBOM, reproducible wheel, verified bundles |
| package-address traversal | identifier-validated semantic addresses |

## CURRENT KNOWN GAPS (honest)

1. **Unsigned grants accepted in the development profile** (transition).
   Production/sovereign refuse unconditionally; the hole is
   fuzz-pinned. Removal date: before any open deployment.
2. **Single-machine evidence**: chains detect edits, not whole-log
   deletion. Distributed checkpoints are gated before open networking
   (plan SS52).
3. **Transport adapter conformance is trusted, not verified**: a
   non-conformant host transport could ignore spec/netpolicy.md duties
   (e.g. follow redirects internally). The runtime cannot see inside a
   transport; sovereign deployments must use audited adapters.
4. **Name-based egress inside an allowed host**: the allowlist is by
   hostname; an allowed host serving attacker content (compromised
   origin) is content-trust, out of the semantic model.
5. **Python runtime as reference oracle**: not memory-safe; the Rust
   runtime (H8, started — canonicalizer done) is the path to a
   memory-safe TCB.
6. **No multi-machine protocol yet**: proposals/evidence/bundles are
   signed files; transport (Appendix E) is unbuilt by sequencing
   decision.
7. **Wall-clock deadlines are host-side** (deliberately outside
   deterministic semantics); countable budgets are the deterministic
   layer.

## CLOSED HISTORICAL GAPS

- ~~path normalization not symlink-aware~~ / ~~TOCTOU on read limits~~
  → closed this cycle (resolved-path auth + handle-bounded reads).
- ~~no resource limits on computation~~ → closed this cycle
  (execution budgets, E410).
- ~~no provenance/evidence~~ → closed (hash-chained evidence,
  verify-evidence command, install events).
- ~~no network egress story~~ → capability-gated net.fetch + normative
  transport policy + reference enforcement (new surface, new policy).
- ~~verify_evidence crashes on corrupt input~~ → reports ok:false
  (fuzz-found, fixed).
- ~~forged session tokens crash verifier~~ → clean E406
  (adversarial-found, fixed).
- ~~unsigned grants accepted everywhere~~ → profile-gated (dev-only).

## OUT OF SCOPE (stated, not hidden)

- Compromised host OS / hardware side-channels.
- Traffic-analysis and anonymity (Tor adapter is future, and is
  transport, not semantics).
- Key-holder complicity within their granted scope (authority, not
  cryptography, problem — mitigated by multisig + narrowing).
- Content correctness of allowed remote hosts.
- Quantum adversaries (crypto agility planned; ed25519 today).
- "Unhackable" claims of any kind.

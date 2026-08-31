# THREAT_MODEL.md — HISTORICAL (Milestone 4a scope)

> ARCHIVED 2026-08-31: superseded by the versioned current model at
> /THREAT_MODEL.md (Protocol 0.2 / Runtime 1.4.1). Kept verbatim for
> audit trail; claims below were true then and several gaps are now
> CLOSED (see the current model's "Closed historical gaps").

> Updated 2026-08-31 (H6/H7 hardening): fuzz campaign over trust loaders complete (one crash fixed: verify_evidence on corrupt lines); signature-stripping pinned as the known transition hole closed by `--profile production`; signed releases + reproducible wheel now give an integrity story for distributed artifacts.

Master roadmap §88/§89 define the long-term threat model. This file states
what the **current** artifact does and does not defend against, so no one
mistakes this runtime for the fully secured 2066.

## Assets

- Integrity of executed semantics (a program must mean exactly what its
  graph says).
- Determinism of results and errors (auditability depends on it).
- **Filesystem integrity** (new in M3): programs may touch only the paths
  the human's grant set covers.

## Trust boundaries

- `.ai` program files are **untrusted input**. The runtime assumes a
  hostile program: malformed structure, deep/huge graphs, extreme literals,
  and — new in M3 — attempts to read or write outside its granted scopes.
- The **grant file is policy**, authored by the human/policy layer, loaded
  once at process start. Programs have no op to read, create, widen, or
  revoke grants; the authority plane is invisible to them. **Signed grant
  envelopes (M4a) are verified fail-closed at load** — editing a scope,
  limit, or timestamp in a signed file invalidates it; `--require-signed`
  refuses unsigned files outright.
- Everything beyond granted filesystem scopes (rest of the disk, network,
  processes) remains unreachable: no ops exist for it.

## What the runtime guarantees (M3)

- No undefined behavior: every malformed construct yields a structured,
  deterministic error; arithmetic is total (E301/E302); casts are total
  (E303/E304).
- Termination: DAG scopes + acyclic call graph.
- **Default deny**: executing an effectful op with no grant set attached is
  denied (E401). A grant on `/incoming` covers `/incoming/a.txt` but not
  `/incoming.txt` (component-wise scope match) and not `/etc`.
- **No partial writes**: `filesystem.write` checks scope, expiry, and size
  limits before writing a single byte.
- **No self-authorization**: denials (E401/E402/E403) are raised by the
  runtime, never by the program; exit code 4 distinguishes "the policy said
  no" from crashes for supervising agents/humans.

## Known gaps (accepted for M3, tracked for later phases)

| Gap | Risk | Planned mitigation (phase) |
|---|---|---|
| No resource limits on computation | a huge/deep pure graph can exhaust host memory/time | runtime budgets as capability constraints (Phase 4–5) |
| Grants are unauthenticated files | ~~anyone who can edit the JSON can widen access~~ **closed in M4a for signed files**: signature covers scopes, limits, expiry; tampering refuses the whole file | **M9**: human approval from any-disk keys (`key-format`/`approve`, spec/hardware-key.md) makes signed delegation cheap — bearer-object limits stated there; real secure element at Phase 10 |
| Path normalization is not symlink-aware | a symlink inside a granted scope can point outside | resolve symlinks (realpath) at enforcement before M3 is used beyond local dev |
| TOCTOU on read limits | file can grow between check and read | read with size cap atomically (open with limit) before production use |
| No provenance/evidence | executions are not signed or hashed into an audit trail | evidence protocol (Appendix C.5) |
| No revocation mid-run | a long-running program keeps its grant until it finishes | per-operation re-check exists; add lease/revocation channel (Phase 5+) |

## Standing rule

Every new effectful operation must land with: an effect classification, a
capability action, scope/limit/expiry enforcement in **both** adapters, and
denial tests — or it does not merge (roadmap §20 forbidden defaults).

## Surfaces added in the hardening cycle (H0–H8 seed)

- **Outbound egress (`net.fetch`)**: hostname-allowlisted by
  `net.request` grants; the runtime owns no sockets (transport is
  host-injected); denied hosts fail closed with zero calls (tested).
  Residual: DNS/IP-level tunneling inside an ALLOWED host is out of
  scope — the allowlist is by name, not content.
- **Semantic addresses**: `package::module::unit` resolution is
  identifier-validated before any filesystem use; traversal payloads
  are refused (tested).
- **Update bundles / releases**: signed envelope + per-file hashes;
  install is verify-everything-then-copy and records evidence.
  Residual: trust roots the operator's key hygiene.
- **Known, documented**: unsigned grants accepted in development
  profile only (fuzz-pinned); single-machine evidence chains detect
  edits, not deletion.


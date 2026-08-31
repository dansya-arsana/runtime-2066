# Security Policy — 2066

## Supported versions

| version | status |
|---|---|
| 1.4.x (main) | supported |
| ≤ 1.3 | prototype, unsupported |

## Reporting a vulnerability

Email the maintainer (see GitHub profile of `dansya-arsana`) with
"2066-security" in the subject. Please include reproduction steps and,
where possible, a failing test or malformed `.ai`/grant/proposal input.

- Acknowledgment: within 72 hours.
- Disclosure: coordinated; we publish an advisory + patch after a fix
  window (90 days default, shortened for actively exploited issues).
- Safe harbor: good-faith research on your own deployments is welcome.

## In scope

The semantic core (`runtime/{parser,validator,serialize,hashing,types,
errors,packages,ops,interpreter,plan_vm,capabilities}.py`), the
capability/identity machinery (`runtime/{identity,session,revocation,
multisig,delegation,keydisk,pinning}.py`), evidence chaining, and the
CLI's handling of untrusted files.

## Out of scope (documented limits — THREAT_MODEL.md)

The HTTP app shells in `apps/` are reference demos, not hardened
services; demo credentials in docs; the Python runtime itself is the
reference oracle, not yet a memory-safe implementation (H8 tracks the
independent core).

## Severity taxonomy

C1 authority escape (unsigned effect succeeds, capability bypass,
hash/canonicalization collision) · C2 identity/evidence forgery ·
C3 crash/DoS on malformed input · C4 information leak.

## Signature keys

Releases are not yet signed artifacts (H7). Until then, verify source
via git history and `python -m runtime digest` (runtime self-hash, S9).

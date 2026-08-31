# Audit — full-stack review + agent-speed pass (2026-08-31, v1.2.1)

Adversarial audit of everything built from M0 to M6, plus an agent-speed
optimization pass. Every finding below is reproduced, fixed, and covered
by a regression test. Nothing was fixed without a test.

## Security findings (fixed)

### F1 · HIGH — unhandled crash on >4300-digit node ids
A node id of 5,000+ digits passed the parser's regex, then crashed the
validator with an unhandled `ValueError` (Python's 4300-digit
int-conversion limit) — an attacker could turn any "every failure is a
structured error" guarantee into a raw traceback.
**Fix:** parser rejects node ids over 40 digits with structured E107.

### F2 · HIGH — merge crashed on hand-crafted unit keys
`merge_proposals` trusted proposal `changes` keys to be well-formed
units. A signed proposal (own keypair, no trust store in the default
flow) containing `func/x/y/z` crashed the merge with an unhandled
`ValueError` mid-rebuild.
**Fix:** merge validates every unit key against strict grammar before
applying; malformed keys are fail-closed E604 naming the agent.

### F3 · MEDIUM — empty capability resource granted the whole tree
`{"action": "filesystem.write", "resource": ""}` normalized to the
*entire working directory* — a policy typo silently became a write-everything
grant.
**Fix:** empty/whitespace resources refused at load; data resources must
be explicit entity names (E-style ValueError at load, exit 3).

### F4 · LOW — `format-version` header accepted mid-file
The version header was honored anywhere, allowing a "version switch" in
the middle of a program. Now only valid as a leading declaration.

## Agent-speed findings (fixed)

### S1 · Agent iteration 3.1× faster
The agent loop previously needed 3 subprocess spawns per revision
(validate + effects + hash, ~80–100 ms of startup each). New combined
command:

```bash
python -m runtime check examples/calculator.ai --json
# → {"effects": [...], "hash": "sha256:…", "ok": true}   (or error + E-code)
```

Measured: 249 ms → 81 ms per iteration (3.1×) on Windows process spawn
costs alone. For agents, *iteration count × spawn cost* is the dominant
compute burn in the dev loop — this directly cuts it.

### S2 · Single-call agent surface
`check` returns validate + effects manifest + canonical hash in one
payload, so an agent's per-revision contract is one call: draft →
`check` → fix from `error.code`/`expected`/`received` → re-check.

## Confirmed-solid areas (probed, held)

- 20,000-node programs: parse+validate 135 ms, both engines agree, no
  recursion blowups (Kahn + iterative DFS).
- Injection payloads as where-values/insert values: inert (bound
  parameters) — re-verified on `data.list` paths.
- Session tokens: `None`, degenerate (`..`, `a.b`, `!!!!.!!!!`), and
  empty-string tokens all rejected E406; signature confusion via
  `algorithm` tampering rejected at envelope load.
- Cyrillic/homoglyph op names rejected by strict ASCII op grammar.
- Revocation chain reordering/deletion/editing detected (E-chain tests).
- Merge results that would fail validation are rejected, never
  half-applied.

## Remaining known gaps (tracked, not hidden)

- THREAT_MODEL rows: symlink/TOCTOU on path checks; no compute resource
  limits; unsigned caps accepted by default (use `--require-signed`).
- JS export: i64 range not enforced; UTF-16 comparison order.
- Evidence log: single-machine scope; no external anchoring.

## Test count

265 → 281 (new: F1/F2/F3 regression tests, `check` CLI tests). Suite
remains deterministic; full run ~14 s.

---

## Postscript — hardening-cycle verification (2026-08-31)

The original audit above predates the H-cycle. Since then, verification
became continuous instead of periodic:

- **Property suite**: canonicalization idempotence, hash stability
  across formatting, sign→verify round-trips, grants-cannot-widen.
- **Fuzz campaign** (grant loader, signed envelopes, proposals,
  evidence chains, package manifests — 980+ mutants, all classified):
  found and fixed `verify_evidence` crashing on corrupt lines; pinned
  the unsigned-envelope transition hole.
- **Adversarial suite**: hostile .ai programs (escalation, guard
  bypass, identity forgery) — found and fixed forged tokens crashing
  `session.verify` (shadowed import in an except clause).
- **Security matrix**: SQL injection (parameterized values), path
  traversal (addresses + fs scopes), replay, impersonation, egress
  boundary — 9 attacks, all structured refusals.
- **Independent implementation**: the Rust canonicalizer agrees with
  the Python oracle on all 28 corpus hashes.


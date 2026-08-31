# spec/proposals.md — Signed proposals & merge (normative)

A proposal is a signed envelope whose payload binds: base program
hash, proposed program hash, node-level diff, author identity, issued
at, format version.

1. Verification: signature over the canonical payload; base hash must
   equal the CURRENT base (E601 — the graph moved); malformed
   proposals E604; bad signatures E602.
2. Merge is deterministic: independent (non-overlapping) node diffs
   merge in node-id order; overlapping mutations of the same unit are
   a conflict (E603) — never silently resolved.
3. Impersonation: the author identity is inside the signed bytes;
   rewriting it breaks the signature (pinned in
   tests/security/test_authority_attacks.py).
4. Proposals are transport-independent artifacts (ADR-006).

# spec/evidence.md — Evidence chain (normative)

An evidence log is an append-only JSONL chain:

```text
event { seq, timestamp, action, resource, detail,
        prev_hash, hash }
hash = SHA-256(canonical(event with hash omitted))
```

1. `prev_hash` of event n+1 = `hash` of event n; genesis prev = 64
   zeros.
2. `verify_evidence` walks the chain and REPORTS (never crashes) on
   corrupt lines, link mismatches, or content-vs-hash drift (H6 fix).
3. Edits to any historical event invalidate everything after it.
4. Events carry metadata and hashes, not payloads (SS65). Full-log
   deletion on a single machine is a known limit; replicated
   checkpoints come before open networking (SS52).
